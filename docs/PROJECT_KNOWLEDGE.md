# 项目知识库（PROJECT_KNOWLEDGE）

> 本文件是本次知识库整理（2026-09-29）新建的核心文档，使用 spec 指定的确切文件名。内容以当前真实代码为最高事实依据；与现有文档（`docs/DEVLOG.md`/`docs/INTERVIEW.md`/`docs/KNOWLEDGE_TREE.md`）冲突的地方，已在 `docs/KNOWLEDGE_TREE.md`"文档与代码不一致"一节列出，此处不再重复。没有代码/测试/脚本证据支撑的内容，一律标注"未找到证据"，不编造。

## 目录

1. [项目目标](#一项目目标)
2. [完整业务流程](#二完整业务流程)
3. [系统架构](#三系统架构)
4. [模块级说明](#四模块级说明)
5. [Agent 知识](#五agent-知识)
6. [LangGraph](#六langgraph)
7. [RAG](#七rag)
8. [Review](#八review)
9. [Modification Agent](#九modification-agent)
10. [V1/V2](#十v1v2)
11. [Diff](#十一diff)
12. [未来持续迭代机制](#十二未来持续迭代机制)

另见：[架构决策](ARCHITECTURE_DECISIONS.md) | [个人能力现状与知识缺口](CAPABILITY_GAPS.md) | [项目状态管理见下方第八节相关小节](#四模块级说明中的技术债务与状态)

---

## 一、项目目标

- **为什么做**：劳动合同审查是一个"需要专业法律知识 + 大量重复劳动"的场景——律师/HR 需要逐条对照《劳动合同法》检查试用期、竞业限制、合同期限等条款是否合规，人工做容易漏检、也很难保证一致性。本项目尝试用"RAG 检索真实法条 + LLM 判断 + 规则补充确定性检查"的组合，做一个能辅助人工审查、而不是替代律师最终判断的工具。
- **解决什么业务问题**：① 条款级风险发现（哪些条款可能违反法律强制性规定）；② 给出法律依据而不是空泛结论；③ 律师确认要修改某条款后，辅助生成修改文本，并保留完整的人工确认闭环（不自动生效）；④ 修改后生成新版本合同（V2），并能对比 V1/V2 之间条款和风险的变化。
- **面向什么用户**：律师、企业 HR/合规人员——需要审查劳动合同、并且愿意在系统给出的建议基础上做最终判断的专业用户，不是面向普通劳动者的自助工具（没有做面向劳动者的解释性 UI，也没有做多用户权限体系）。
- **当前实际做到什么程度**（如实说明边界）：
  - 只能解析 `.txt` 格式合同（`.pdf`/`.docx`/`.ocr` 在 `parser/document_parser.py` 里是占位实现，调用会抛 `NotImplementedError`）。
  - 知识库只有《劳动合同法》14 条节选，规则检查只覆盖试用期工资、试用期期限两类问题。
  - 已经完整跑通"上传 → 解析 → 切分 → 审查 → 律师提出修改 → Modification Agent 生成候选 → 人工确认 → 生成 V2 → V1/V2 Diff/风险 Diff"这条全链路，并有真实浏览器环境验收记录（详见 `docs/PITFALLS.md` P-22/23/24）。
  - 没有用户权限体系、没有鉴权、没有 API 文档发布、没有批量处理能力。

## 二、完整业务流程

以下每一步都标注了对应的代码文件和当前真实实现状态（✅ 已实现且有验证证据 / ⚠️ 已实现但有已知限制 / 📝 未实现）。

1. **合同上传** ✅ —— `POST /contracts`（`api/routes/contracts.py::create_contract`）：接收 multipart 文件，落到临时目录，调用 `ContractManager.create_contract`（`contract/manager.py`）生成 `contract_id`（uuid4 hex）、保存原始文件（只写一次，不允许覆盖）、计算 sha256、写 `metadata.json`（最后原子写入，代表创建完整）。
2. **合同存储** ✅ —— 纯文件系统，`<root>/<contract_id>/{original_file/, parsed_text.txt, clauses.json, metadata.json, review/, modification_tasks/, versions/}`；`contract_id` 在访问任何目录前都经过正则校验，防止路径穿越。
3. **合同解析** ✅（仅 `.txt`）—— `POST /contracts/{id}/parse` → `parser.contract_parser.parse_contract` → `parser/document_parser.py::DocumentParser` 按扩展名分发给 `TxtParser`（支持 BOM 检测、编码回退），**不改动原文**（不 strip、不统一换行），保证后续 `Clause` 的字符偏移量指向原文准确无误。
4. **条款切分** ✅ —— 同一个 `/parse` 请求内，`clause.contract_clause_splitter.split_contract` → `clause/clause_splitter.py::ClauseSplitter`：两阶段（正则结构切分"条→款" + 超长条款用 `RecursiveCharacterTextSplitter` 二次切分），建立 `hierarchy_level`（0=条，1=款）与 `parent_clause` 父子关系，保证 `full_text[start_char:end_char] == original_text` 不变量。
5. **Review 发起** ✅ —— `POST /contracts/{id}/review`（`api/routes/contracts.py::review_contract`）调用 `review.pipeline.run_review`（LangGraph 编排，见第六节），内部依次经过下面 6~9 步，最终由本路由把结果组装成 `ReviewReport` 并调用 `contract_manager.save_review(contract_id, report, contract_version="v1")` 持久化（不可覆盖，按序编号 `v1_001`、`v1_002`……）。
6. **RAG / Evidence** ✅ —— `review/reviewer.py::ClauseReviewer.review` 对每个条款先 `generate_query`（保留标题关键词，只去编号），再调用 `rag/retrieval.py::LegalKnowledgeRetriever` 从 Chroma（BGE-M3 稠密向量、归一化）里检索出最相关的法条，转成 `Evidence` 对象（不落盘、不进 LangGraph State，只是 `review` 内部的局部变量）。
7. **LLM Review** ✅ —— 把条款原文 + 检索到的 `Evidence` 拼成 Prompt（`llm/prompts.py`），调用 DeepSeek（`llm/client.py::OpenAICompatibleClient.chat`，JSON 模式），解析成 `LLMReviewOutput`（`review/schemas.py`）后补上 `clause_id`/`source=llm`，构造成 `schemas.ReviewResult`。单条款失败会被捕获进 `failed_clauses`，不影响其他条款。
8. **RuleChecker** ✅（仅 2 条规则）—— `rules/checker.py::RuleChecker.check(clauses)` 与 LLM Review **并行**运行（LangGraph 两条边同时从 `contract_loading` 扇出），不读 `llm_results`，独立判断试用期工资比例、试用期期限是否符合《劳动合同法》第十九条阶梯规则，跨条款问题用 `related_clause_ids` 关联。
9. **Merge** ✅ —— `rules/merge.py::merge_review_results` = `llm_results + rule_results`，纯拼接，不覆盖不去重（`ReviewResult` 是风险点粒度，一个条款可以有多条结果）。
10. **ReviewReport** ✅ —— `review/pipeline.py::report_assembly` 节点内部构造用于验证；对外真正返回给前端/持久化的 `ReviewReport` 由 `api/routes/contracts.py` 用最终 LangGraph State 重新组装（State 本身明确不含 `report` 字段，这是记录在案的架构决策，见 `docs/DEVELOPMENT_LOG.md` 3.9）。
11. **前端展示** ✅ —— `frontend/src/App.jsx` 持有全部状态，`ReviewWorkspace.jsx`/`ClauseViewer.jsx` 展示审查结果，律师可以从某条 `ReviewResult` 定位到对应条款（`handleLocateClause`）。
12. **律师提出修改任务** ✅ —— `POST /contracts/{id}/modification-tasks`（`ModificationTaskForm.jsx` 提交）：律师选中一个具体条款（`target_clause_id`）+ 原文 + 修改意见，`ModificationService.check_task_conflict` 先检查同一条款是否已有未完成任务（同一条款重复创建会被拒绝，409），通过后 `ContractManager.create_modification_task` 落盘，状态固定为 `pending`。
13. **Modification Agent** ✅ —— `POST .../modification-tasks/{id}/start`（`ModificationService.start_modification`）：加载条款、加载该条款关联的最新审查结果（若有）、调用 `ModificationAgent.generate_candidate`（`modification/agent.py`）。
14. **Function Calling** ✅ —— Agent 内部把条款、审查结果、**全部历史**律师意见拼成 Prompt，调用 `llm/client.py::chat_with_tool`，声明唯一工具 `modify_clause`（`modification/prompts.py::MODIFY_CLAUSE_TOOL_SCHEMA`），`tool_choice="auto"`（P-21 修复后），模型通过真实 `tool_calls` 返回结构化参数。
15. **Validator** ✅ —— `modification/tool.py::execute_modify_clause` 做第一道校验（`clause_id` 必须匹配目标条款）；`modification/validator.py::validate` 做第二道、更完整的校验：范围（越界条款编号）、完整性（占位符/空文本）、结构（条款编号是否保留）。
16. **Human Confirmation** ✅ —— 校验通过后任务进入 `reviewing`，`current_modified_text` 存候选文本；律师通过 `POST .../confirm` 确认（→`confirmed`）或 `POST .../reject`（附带新意见，→`rejected`，若已用满 3 次重试则直接 →`needs_human`）。**没有任何自动确认逻辑**——这是硬约束。
17. **V2** ✅ —— 所有任务都不再处于 `pending/reviewing/rejected`（`needs_human` 不阻塞）且至少有一条 `confirmed` 时，律师点击"生成 V2"（`POST /contracts/{id}/versions` → `ModificationService.generate_v2`）：按"条"为单位、基于 V1 原始全文的字符偏移量做局部替换重建全文（`_group_clauses_by_article`+`_reconstruct_article_text`，P-22 修复后的实现），写入临时文件（`newline=""`，P-24 修复），再用**完全未改动**的 `create_contract`/`parse_contract`/`split_contract` 正常创建一个新的、内部使用的 `contract_id`。
18. **重新解析 / 重新切分** ✅ —— 上一步已经完成（V2 复用了未改动的解析/切分函数，不是打补丁）。
19. **完整重新 Review** ✅ —— `POST /contracts/{id}/versions/{v}/review`（`ModificationService.run_v2_review`）直接调用**同一个未改动的** `run_review`，对 V2 的内部 `contract_id` 走一遍完整的 RAG+LLM+Rule+Merge 流程，`save_review` 时显式传 `contract_version=version_number`（P-23 修复后）。
20. **Clause Diff** ✅ —— `GET /contracts/{id}/versions/{v}/diff`（`ModificationService.clause_diff`）按 `clause_id` 对比 V1/V2 的 `hierarchy_level==0` 条款原文，`matched=False` 时不猜测对应关系。
21. **Risk Diff** ✅ —— `GET /contracts/{id}/versions/{v}/risk-diff`（`ModificationService.risk_diff`）按 `(source, clause_id/rule_id)` 做 key，把 V1/V2 两次独立复审结果分类为 `resolved/unchanged/changed/new/unmatched`。

## 三、系统架构

```
文字版架构图（一）：主审查链路

  React（frontend/）
      │  fetch（api/client.js，唯一 HTTP 出口）
      ▼
  FastAPI（api/app.py + dependencies.py + routes/contracts.py + routes/modification.py）
      │  Depends（lifespan 构造的重对象：ContractManager/embedder/knowledge_base/
      │           retriever/llm_client/reviewer/rule_checker/modification_agent）
      ▼
  Contract / Parser / Clause
      （contract/manager.py → parser/document_parser.py → clause/clause_splitter.py）
      │  contract_id → parsed_text.txt → clauses.json
      ▼
  Review Pipeline（review/pipeline.py，LangGraph StateGraph）
      │
      ├─▶ LLM Review（review/reviewer.py）──┐
      │      │ query→RAG(rag/*)→Prompt      │
      │      ▼                              ▼
      │   llm/client.py (DeepSeek)       Merge（rules/merge.py）
      │                                      ▲
      └─▶ Rule Check（rules/checker.py）─────┘
                                              │
                                              ▼
                                      ReviewReport（review/schemas.py + schemas/review_report.py）
                                              │
                                              ▼
                          contract_manager.save_review()（持久化，不可覆盖）


文字版架构图（二）：Modification Agent → V1 → V2 → 重新 Review

  律师（前端 ModificationTaskForm/Panel）
      │ 创建 ModificationTask（pending）
      ▼
  ModificationService.start_modification
      │
      ▼
  ModificationAgent（modification/agent.py）
      │  Prompt（V1 原文 + 审查结果 + 全部历史意见）
      │  chat_with_tool（Function Calling，tool_choice="auto"）
      ▼
  modification/tool.py（执行 modify_clause，第一道越界校验）
      ▼
  modification/validator.py（范围/完整性/结构校验，纯函数）
      │
      ├─ 通过 ──▶ task.status = reviewing（等待人工）
      │               │ 律师 confirm / reject
      │               ▼
      │           confirmed（可进入 V2）/ rejected（可重试，<3 次）
      └─ 不通过 ──▶ pending（可重试）/ needs_human（已达 3 次上限）

  全部任务不再 pending/reviewing/rejected 且至少一条 confirmed
      │
      ▼
  ModificationService.generate_v2
      │  _group_clauses_by_article + _reconstruct_article_text（按字符偏移量局部替换）
      │  写临时文件（newline=""）→ create_contract/parse_contract/split_contract（未改动）
      ▼
  V2（新的、内部的 contract_id）+ ContractVersion 映射记录
      │
      ├─▶ run_v2_review（复用未改动的 run_review）──▶ V2 的 ReviewRecord
      │
      ├─▶ clause_diff（按 clause_id 对比 V1/V2 原文）
      │
      └─▶ risk_diff（按 source+clause_id/rule_id 对比 V1/V2 审查结果）
```

## 四、模块级说明

> 以下每个模块按"解决什么问题 / 位置 / 输入 / 输出 / 依赖 / 与其他模块的关系 / 对应代码文件 / 为什么这样设计 / 当前实现状态"组织。更细的历史演进见 `docs/DEVELOPMENT_LOG.md`。

### 4.1 Contract（合同存储）

- **业务职责**：作为律师/系统的"合同档案柜"——保存原始合同、解析结果、条款、审查历史、修改任务、版本映射，保证原始文件永远可追溯。
- **Agent 职责**：无（不涉及任何 LLM 调用），是纯粹的存储基础设施，被 Review 和 Modification 两条业务链路共同依赖。
- **工程职责**：路径安全（`contract_id` 正则校验防穿越）、原子写入（临时文件+`os.replace`）、状态推进（`uploaded→parsed→split→reviewed`）、审查记录不可覆盖（按版本+序号编号）。
- **输入**：合同文件路径、`Clause` 列表、`ReviewReport`、`ModificationTask`、`ContractVersion`。
- **输出**：`Contract`/`Clause`/`ReviewRecord`/`ModificationTask`/`ContractVersion` 对象。
- **模块关系**：被 `parser`/`clause`（写入解析结果/条款）、`api/routes/*`（HTTP 层直接调用）、`modification/service.py`（审查记录、任务、版本的全部持久化）共同依赖；自身不依赖 `parser`/`clause`/`rag`/`llm`（只负责"存"，不负责"怎么产生这些数据"）。
- **对应代码文件**：`contract/manager.py`。
- **设计原因**：审查是多步骤流程，中间产物需要落盘并按合同隔离；不用数据库是因为当前只需要按合同隔离，没有检索/并发/事务需求（详见 ARCHITECTURE_DECISIONS）。
- **当前实现状态**：✅ 完整实现（Phase 1/2 主体 + Phase 3 的 review/modification_tasks/versions 三个子目录）；⚠️ 三个子目录各自独立编号、没有跨文件事务保护，真实并发场景未验证。

### 4.2 Parser（文档解析）

- **业务职责**：把用户上传的任意格式合同文件转换成纯文本，供后续切分/审查使用。
- **Agent 职责**：无。
- **工程职责**：按扩展名分发解析器、编码探测（BOM/utf-8-sig/gb18030 回退）、**绝不改动原文内容**（保证下游偏移量不变量）。
- **输入**：原始文件路径（来自 `ContractManager.get_original_file_path`）。
- **输出**：纯文本字符串（经 `contract_manager.save_parsed_text` 落盘）。
- **模块关系**：被 `parser/contract_parser.py::parse_contract`（桥接函数）调用，向 `ContractManager` 写结果；`clause` 模块消费其输出；`modification/service.py::generate_v2` 直接复用此桥接函数处理 V2 文本。
- **对应代码文件**：`parser/document_parser.py`、`parser/contract_parser.py`。
- **设计原因**：文件格式差异应该隔离在这一层；不清洗文本是为了让 `Clause` 的字符偏移量始终有效可追溯。
- **当前实现状态**：✅ `.txt` 完整实现；📝 `.pdf`/`.docx`/`.ocr` 是占位（`NotImplementedError`，API 层映射成 415）。

### 4.3 Clause（条款切分）

- **业务职责**：把合同全文切成结构化的条款树，保留条/款的层级关系与原文精确位置，是审查、修改、Diff 三条业务链路共同的"寻址系统"。
- **Agent 职责**：无（纯正则 + `RecursiveCharacterTextSplitter`，不涉及 LLM）。
- **工程职责**：两阶段切分（结构优先，字数兜底）、`clause_id` 编号规则、`hierarchy_level`/`parent_clause` 父子关系维护、`full_text[start:end]==original_text` 不变量。
- **输入**：解析后的纯文本。
- **输出**：`Clause` 列表（含 `clause_id`/`hierarchy_level`/`parent_clause`/`start_char`/`end_char`/`original_text`/`metadata`）。
- **模块关系**：被 `review/reviewer.py`（逐条审查）、`modification/service.py`（V2 重建按这棵树分组、`validator.py` 用 `metadata['article_no']` 做范围校验）依赖；自身只依赖 `schemas`/`config`。
- **对应代码文件**：`clause/clause_splitter.py`、`clause/contract_clause_splitter.py`。
- **设计原因**：审查以条款为单位；结构信息比字数切分更重要（法律条文的边界是语义边界）。
- **当前实现状态**：✅ 完整实现；⚠️ P-22 的真实根因证明了"这棵树的父子内容包含关系"这条隐含规则容易在新的消费场景（V2 重建）下被误用，是需要持续警惕的一个不变量。

### 4.4 RAG

- **业务职责**：为 LLM 判断提供真实、可追溯的法律依据，避免 LLM 凭记忆编造法条。
- **Agent 职责**：无自主性——检索是 `ClauseReviewer.review` 里写死的一步，不是 LLM 自己决定"要不要检索、检索什么"。
- **工程职责**：法律文本切分（按条）、BGE-M3 embedding（本地加载、归一化）、Chroma 持久化写入与检索。
- **输入**：法律文本（知识库构建时）、query 字符串（检索时）。
- **输出**：`Evidence` 列表。
- **模块关系**：被 `review/reviewer.py` 调用；`modification/agent.py` **明确不**调用 RAG（复用 `review_result.legal_basis`，见 ARCHITECTURE_DECISIONS）；自身独立于 `contract`/`parser`/`clause`。
- **对应代码文件**：`rag/embedding.py`、`rag/database.py`、`rag/loader.py`、`rag/retrieval.py`。
- **设计原因**：把"检索真实依据"和"LLM 判断"解耦，检索层可以独立测试、独立扩充知识库。
- **当前实现状态**：✅ 真实验证过（三个 query 第一名全部命中）；⚠️ 知识库仅 14 条、无相关性阈值。

### 4.5 Review（LLM Review + RuleChecker + Merge）

- **业务职责**：对单个条款做出风险判断（LLM），并对结构性、确定性问题做补充检查（Rule），合并成完整结果。
- **Agent 职责**：LLM Review 是"在写死的流程节点里做一次概率性判断"，不是 Agent；RuleChecker 是纯确定性代码，完全不是 Agent。
- **工程职责**：Prompt 拼接、JSON 输出校验（`LLMReviewOutput`）、失败隔离（`failed_clauses`）、规则的独立注册与执行、纯拼接合并。
- **输入**：`Clause` 列表。
- **输出**：`ReviewResult` 列表。
- **模块关系**：被 `review/pipeline.py`（LangGraph 节点）调用；`modification/service.py::_find_review_result` 消费其持久化结果（`ReviewRecord`）作为 Modification Agent 的输入之一。
- **对应代码文件**：`review/reviewer.py`、`review/schemas.py`、`rules/checker.py`、`rules/merge.py`、`rules/probation_salary.py`、`rules/probation_duration.py`。
- **设计原因**：LLM 单条款审查看不到其他条款、结果不保证可复现——真实数据证明了这两点（详见 PITFALLS P-04/P-05），所以需要规则补充确定性和跨条款能力；不做单纯规则系统是因为规则无法覆盖法律语义的丰富性；不做单纯 RAG+LLM 是因为它有结构性盲区。
- **当前实现状态**：✅ 完整实现，✅ 真实 10 条款验证（12=10+2）。

### 4.6 LangGraph Pipeline

见第六节详细说明。**对应代码文件**：`review/pipeline.py`。**当前实现状态**：✅ 完整实现，只用到 State/Node/Edge/并行/汇合，未用条件边/重试/checkpoint。

### 4.7 API（FastAPI）

- **业务职责**：把 Contract/Review/Modification 三条业务链路暴露成 HTTP 接口，供前端调用。
- **Agent 职责**：无，纯粹的接线层——不重新实现任何业务逻辑，只做请求解析、依赖注入、异常到状态码的映射。
- **工程职责**：`lifespan`+`AppState`+`Depends` 依赖注入（重对象启动时构造一次）、组合型依赖现场组装（P-20 教训）、统一异常映射。
- **输入**：HTTP 请求。
- **输出**：HTTP 响应（`schemas` 里的 Pydantic 模型序列化）。
- **模块关系**：依赖 `contract`/`parser`/`clause`/`review`/`rules`/`modification` 的全部业务模块；不被任何模块依赖（是最上层）。
- **对应代码文件**：`api/app.py`、`api/dependencies.py`、`api/routes/contracts.py`、`api/routes/modification.py`。
- **设计原因**：不手写 Singleton 类，用 FastAPI 自带三件套；业务路由用同步 `def`（阻塞调用交给线程池）。
- **当前实现状态**：✅ 完整实现，✅ 真实 `uvicorn` 启动、真实浏览器联调；**这与 README.md/旧版 docs/INTERVIEW.md/旧版 docs/KNOWLEDGE_TREE.md 里"api/ 是空包"的记录不一致，属于文档滞后，已在本次整理中标注（见 `docs/KNOWLEDGE_TREE.md`"文档与代码不一致"一节）**。

### 4.8 前端（React）

- **业务职责**：律师操作界面——上传合同、查看审查结果、提交修改任务、确认/拒绝候选、生成 V2、查看 Diff。
- **Agent 职责**：无。
- **工程职责**：`App.jsx` 唯一持有状态与调用 API；`api/client.js` 唯一 fetch 层；统一错误提示格式。
- **输入**：用户操作事件。
- **输出**：对 `api/client.js` 的调用。
- **模块关系**：依赖 FastAPI 暴露的全部接口；不被任何后端模块依赖。
- **对应代码文件**：`frontend/src/App.jsx`、`frontend/src/api/client.js`、`frontend/src/components/*.jsx`。
- **设计原因**：状态集中管理，避免网络请求散落各处。
- **当前实现状态**：✅ 完整实现，✅ 真实浏览器联调（三次 Bug 修复的验收测试均从前端发起）；⚠️ 无路由、无本地状态持久化。

### 4.9 Modification（modification/）

见第九节详细说明。**对应代码文件**：`modification/agent.py`、`modification/tool.py`、`modification/validator.py`、`modification/prompts.py`、`modification/service.py`。**当前实现状态**：✅ 完整实现且有三次真实 Bug 修复的完整证据链；⚠️ **没有对应的 `tests/test_modification*.py` 自动化 pytest 覆盖，只有 `scripts/verify_*.py` 手工验证脚本**（本次整理核实 `tests/` 目录下确实不存在此类文件）——这是一条真实技术债务。

### 4.10 V1/V2 与 Diff

见第十、十一节详细说明。**对应代码文件**：`schemas/contract_version.py`、`schemas/diff.py`、`modification/service.py` 里的 `generate_v2`/`clause_diff`/`run_v2_review`/`risk_diff`。**当前实现状态**：✅ 完整实现，三次真实 Bug（P-22/23/24）均已修复并验证。

## 五、Agent 知识

- **什么地方是 Agent，什么地方不是**：
  - **不是 Agent**：LLM Review（`review/reviewer.py`）——流程固定（先检索、再判断），LLM 只在一个写死的节点里做判断，不决定"下一步做什么"。RuleChecker 完全是确定性代码。
  - **是 Agent（但有严格边界）**：`ModificationAgent`（`modification/agent.py`）——由 LLM 通过真实 Function Calling 自主决定"要不要调用工具、怎么填参数"，决策权确实在模型手里，不是 Python 代码里的 if/else 硬解析。
- **LLM 和 Agent 的区别**（本项目的立场）：LLM 是一次"输入→输出"的概率性调用；Agent 至少要有"由模型自己决定采取什么行动"这个环节。本项目 Review 链路里的 LLM 调用不是 Agent；Modification 链路里的 LLM 调用是 Agent，因为它通过 Function Calling 自主决定是否调用 `modify_clause`、怎么填参数。
- **Modification Agent 当前的 Agent 形态**：**一次带校验和人工确认的单次工具调用 Agent**。具体特征：
  - 只有一个工具（`modify_clause`），不做多工具选择；
  - 一次 `start_modification` 调用只产生一轮候选，不做多步规划或自主循环；
  - 没有自主终止条件——是否继续重试、是否转人工、是否进入 V2，全部由外部状态机（Service 层）和人（律师）决定，Agent 自己不知道"整个任务"的全貌；
  - 校验（Validator）和确认（HITL）都在 Agent 之外，Agent 的产出不会未经校验/确认就生效。
  - **不是完全自主的复杂 Agent**：没有多工具自主选择、没有多步规划循环、没有自主设定子目标的能力。
- **Function Calling**：真实的 Function Calling——请求带 `tools=[schema]`，DeepSeek 返回真实的 `tool_calls`（不是要求模型在文本里输出 JSON 再用正则去抠）。`tool_choice` 经历过"强制指定函数名→改为 auto"的真实修复（P-21），详见 `docs/PITFALLS.md`。
- **Tool**：目前只有 `modify_clause` 一个工具，定义在 `modification/prompts.py::MODIFY_CLAUSE_TOOL_SCHEMA`，执行逻辑在 `modification/tool.py`。
- **Validator**：`modification/validator.py::validate`，纯函数，不调用 LLM，做范围/完整性/结构三类校验，是"用固定规则检测 LLM 常见错误"的典型例子。
- **Human-in-the-loop**：确认/拒绝永远由外部（律师，通过 API）触发；系统没有任何自动确认逻辑；Reject 后重新生成永远基于 V1 原文+全部历史意见，不基于上一轮候选。
- **当前为什么没有强 Tool Selection Agent**：第一版业务需求只有"修改单个条款"这一种操作，只有一个工具，"选哪个工具"这个问题根本不存在；过早引入多工具选择框架属于过度设计（和 `rules/` 模块曾经的 `ContractFacts` 教训是同一类问题，见 PITFALLS P-06）。
- **未来 Tool Selection Agent 可以放在哪里**：如果未来 Modification 需要支持"新增条款""删除条款""跨条款联动修改"等多种操作，可以在 `modification/agent.py` 与 `modification/service.py` 之间加一层"选择该用哪个工具"的路由逻辑（工具集扩展成多个），不需要改动 `review/pipeline.py` 里的 LangGraph 主图——Modification 本身就是独立于 Review 主图之外的一条链路。
- **当前 Agent 的边界**：Modification Agent 不做检索（复用审查阶段已有的 `legal_basis`）、不做重试策略决定（属于 Service 层）、不做多任务协调（属于 Service 层的状态机与冲突检测）。

## 六、LangGraph

- **为什么项目需要 LangGraph**：Review 链路有真实的并行分支（LLM Review 与 Rule Check 互不依赖，可以同时跑）和汇合点（两者都完成才能 Merge），用声明式的图结构表达比手写线程池代码更可读、更容易测试拓扑本身（而不仅仅是测试最终结果）。**如实说明**：当前只用到 State/Node/Edge/并行/汇合这些基础能力，一个 fork/join 用函数加线程池也能实现，条件边/重试/checkpoint/streaming 一个都没用。
- **Graph/State/Node/Edge 基本概念**：State 是节点间共享的、类型化的数据容器；Node 是"读 State、返回部分更新"的函数；Edge 决定执行顺序，一个节点引出多条边就是并行分支，多条入边汇入一个节点就是汇合点，框架保证所有上游都完成才执行汇合节点。
- **当前 ReviewGraphState**：6 个字段——`contract_id`、`clauses`、`llm_results`、`rule_results`、`final_results`、`failed_clauses`，每个字段只有一个写入者，不需要 reducer。判断标准是"下一个节点是否把它当直接输入"。
- **当前 Graph 数据流**：`contract_loading`（parse+split）→ 扇出到 `llm_review`（逐条 `ClauseReviewer.review`）与 `rule_check`（`RuleChecker.check`）→ 两条边汇入 `merge`（`merge_review_results`，纯拼接）→ `report_assembly`（构造 `ReviewReport` 用于验证，但不写回 State）。
- **哪些数据进入 State，哪些没有，及为什么**：`Evidence`（`ClauseReviewer` 内部局部变量，没有下游节点需要）、`parsed_text`（切分后无人再用）、`original_file`、基础设施实例（`retriever`/`llm_client` 等，通过闭包注入 `build_graph`，不是数据）、`ReviewReport`（明确决定不进，由调用方用最终 State 重建）都不进 State。
- **当前异常处理策略**：除 LLM 单条款失败被捕获进 `failed_clauses` 外，任何节点异常都直接终止整图、向上抛出。真实 LangGraph 1.2.12 上验证过：`ContractNotFoundError`、`RuntimeError` 都原样向上抛出（确认到类型没被换成别的类型这一级）。
- **当前为什么暂时不增加复杂 Retry-Recovery**：锁定的 State 里没有能装"整节点失败"的字段，条件边缺少路由信号；先跑通主链路，用真实使用决定是否值得扩大 State——这是记录在案的架构决策（P-14），不是遗漏。
- **后续可能如何扩展**：如果 Modification 未来需要多工具选择或多步规划，可以在 `modification/` 内部单独建一张更小的图，不动 Review 主图；如果 Review 主图未来需要条件边（例如"某类条款需要额外一轮检索"），需要先扩大 State 加入路由信号字段。

## 七、RAG

- **RAG 在本项目中的真正定位**：**证据层**，只负责"检索真实法条给 LLM 参考"，不参与"审查哪些条款"这个决策——审查哪些条款是由 `ClauseSplitter` 切分结果决定的，切分出多少条就审查多少条，RAG 对此没有发言权。
- **RAG 为什么不负责决定"审查哪些条款"**：这是切分层和检索层的职责边界——切分层保证"每个条款都会被过一遍"，检索层只负责"给这个条款找依据"，两者不应该耦合（如果 RAG 反过来决定审查范围，会让"某条款没检索到相关法条"和"这个条款不需要审查"这两件完全不同的事情被混淆）。
- **RAG 如何提供法律依据 Evidence**：法律文本按"第X条"切分（一条一个 `Evidence`），BGE-M3 归一化稠密向量写入 Chroma，检索时用条款的 query（标题+正文，去编号保留标题）找最相近的几条，转成 `Evidence` 列表交给 Prompt 拼接。
- **Chroma/BGE-M3/Embedding/Retrieval**：`rag/database.py` 是唯一直接接触 Chroma 的文件；`rag/embedding.py` 用 `HuggingFaceEmbeddings` 本地加载 BGE-M3（构造时即加载模型，不是懒加载，这一点被 P-01 真实踩过坑）；`rag/loader.py` 管切分与写入；`rag/retrieval.py` 管检索并转换成 `Evidence`。
- **RAG 当前局限**：知识库只有 14 条节选；`distance` 数值本身没有绝对含义，不同集合不可比；没有相关性阈值；`index` 不去重。
- **为什么不能解决所有法律判断**：知识库覆盖之外的问题，RAG 检索不到相关法条，Prompt 要求 LLM 如实说明"依据不足"而不是编造；跨条款的判断（例如试用期期限是否合法取决于另一个条款的合同期限）RAG 单独检索单个条款也无法解决，需要 RuleChecker 补充。
- **RuleChecker 为什么仍然需要存在**：因为真实数据证明了 LLM 单条款审查看不到其他条款（P-04）、LLM 结果不保证可复现（P-05），RAG 层面无法解决这两个问题——RAG 只能让 LLM"看到更对的法条"，不能让 LLM"看到其他条款"或"每次输出一致"。

## 八、Review

- **LLM Review**：概率性判断，`ClauseReviewer.review` 对单条款做出风险判断，依赖 RAG 检索到的证据，输出经过 `LLMReviewOutput` 校验后补上 `clause_id`/`source`。
- **RuleChecker**：确定性代码，对稳定漏检的问题（试用期工资比例、试用期期限阶梯）做补充判断，独立于 LLM 结果运行。
- **Merge**：`llm_results + rule_results` 纯拼接，理由是 `ReviewResult` 是风险点粒度，替换式合并会丢掉信息。
- **ReviewReport**：`summary`/`overall_risk_level` 是计算字段，由 `results` 推出，不单独存储，避免汇总和明细不一致。
- **为什么不是单纯规则系统**：规则无法覆盖法律语义的丰富性（例如"竞业限制补偿是否合理"这类需要理解上下文的判断），且规则的开发成本高、覆盖范围窄（当前只有 2 条）。
- **为什么也不是单纯 RAG+LLM 系统**：真实验证证明了 LLM 单条款审查的结构性盲区（看不到其他条款）和非确定性（同一输入两次结果不完全一致），这两点用规则能可靠、确定性地补上。
- **两者如何互补**：LLM 覆盖面广但不稳定、有结构性盲区；规则窄但确定、能做跨条款判断。合并时不覆盖不去重，保留两边各自发现的问题。

## 九、Modification Agent

- **Lawyer instruction**：律师创建任务时的第一条意见（`lawyer_instructions[0]`），拒绝候选时追加新意见（`lawyer_instructions` 只增不减，永久保留全部历史）。
- **target_clause_id**：任务必须绑定一个具体条款，即使触发入口是一条 `clause_id` 为空、`related_clause_ids` 关联多个条款的 `ReviewResult`，前端也需要让律师明确选出其中一个条款。
- **Agent**：`ModificationAgent.generate_candidate`，每轮永远基于 V1 原始条款（`clause.original_text`）+ 全部历史意见重新生成，不基于上一轮候选。
- **modify_clause Tool**：唯一工具，Schema 定义在 `modification/prompts.py`，执行逻辑（第一道越界校验：`clause_id` 必须一致）在 `modification/tool.py`。
- **Validator**：`modification/validator.py`，第二道、更完整的越界/完整性/结构校验，纯函数不调用 LLM。
- **Human Confirmation**：`confirm`/`reject` 两个 API，只在 `reviewing` 状态下可调用，是整个流程里唯一能让候选"生效"或"被否决"的动作。
- **Reject**：附带新的 `lawyer_instruction`，`current_modified_text` 清空，状态回到 `rejected`（若还有重试机会）或 `needs_human`（已达上限）。
- **Retry**：`start` 可以在 `pending`/`rejected` 状态下再次调用，每次重试次数 `attempt_number` 递增。
- **3 次失败**：`MAX_MODIFICATION_ATTEMPTS = 3`（`schemas/modification_task.py`），`attempts_exhausted` 属性判断是否已用满。
- **needs_human**：唯一的失败终态——重试满 3 次仍未得到律师确认（无论是 Validator 一直不通过，还是律师一直拒绝），系统不再自动重试。
- **confirmed / completed**：`confirmed` 表示律师确认了某一轮候选，可以进入 V2；`completed` 表示 V2 已经生成、这条任务确认的修改已经写入 V2，任务生命周期结束。
- **为什么这样设计**：详见 `docs/ARCHITECTURE_DECISIONS.md` 里"为什么必须 Human Confirmation""为什么 Reject 从 V1+累积意见重新生成""为什么最多 3 次""为什么失败后 needs_human"等条目。核心理由：合同修改是高风险操作，不能允许 LLM 自主生效；有限重试+明确失败终态，避免无限循环消耗成本又给不出结果。

## 十、V1/V2

- **V1 是什么**：合同上传后的原始 `contract_id`，代表的是"原始上传的这份合同"，本身没有任何 `ContractVersion` 记录（V1 是隐式的）。
- **V2 如何产生**：律师确认若干条修改任务后调用 `generate_v2`，按"条"为单位基于 V1 原始全文的字符偏移量局部替换重建全文，写入临时文件后，用**完全未改动**的 `create_contract`/`parse_contract`/`split_contract` 正常创建一个新的、内部使用的 `contract_id`；`ContractVersion` 记录这层"外部版本号 v2 → 内部 contract_id"的映射。
- **为什么 V1 永不覆盖**：合同审查场景下原始文件是审计依据；`ContractManager` 的存储模型本身"原始文件只写一次，拒绝覆盖"这条硬约束在 Phase 1/2 就已确立，Phase 3 直接复用，没有为 V2 破例。
- **为什么 V2 必须重新解析**：V2 的全文内容和 V1 不同（部分条款被替换），已有的 `parsed_text.txt`/`clauses.json` 是针对 V1 全文算出来的偏移量，直接套用会错位；重新走一遍解析是最简单、最不容易出偏移量 bug 的方式（复用未改动的函数，而不是手写"局部更新已有切分结果"的逻辑）。
- **为什么必须重新切分**：同上，且 V2 的条款结构（尤其是被修改条款的款项编号）可能和 V1 不完全一致，必须用 `ClauseSplitter` 重新识别。
- **为什么必须完整重新 Review**：`ModificationAgent` 的候选只经过 Validator 的结构性校验（范围/完整性/结构），不等于经过完整的法律风险判断——V2 全文仍然需要走一遍完整的 RAG+LLM+Rule 审查，才能知道"修改后的合同还有没有新的风险""原来的风险是否真的解决了"。
- **ContractVersion**：`schemas/contract_version.py`，字段包括 `version_number`（恒为 `"v2"`）、`linked_contract_id`（V2 数据实际存放的内部 `contract_id`）、`source_version`（`"v1"`）。存在【V1 自己】的目录下的 `versions/` 子目录，永久保留、同一 `version_number` 不允许重复生成。
- **linked_contract_id**：把"V2 这个说法"和"实际存放数据的 contract_id"解耦，前端/律师只需要知道"这份合同的 V2"，不需要关心背后还有一个新的 contract_id。
- **ReviewRecord**：`schemas/review_record.py`，V1 和 V2 的审查记录分别存在各自 `contract_id` 的 `review/` 目录下，`contract_version` 字段（`"v1"`/`"v2"`）由调用方显式传入（P-23 修复后），不再由 `save_review` 内部硬编码或猜测。

## 十一、Diff

- **Clause Diff**：`ModificationService.clause_diff`，按 `clause_id` 对比 V1/V2 两边 `hierarchy_level==0` 的 `original_text`，`matched=True/False` 表示这个 `clause_id` 在另一个版本里是否存在，`matched=False` 时不猜测对应关系（明确交给人看）。
- **Risk Diff**：`ModificationService.risk_diff`，对比 V1/V2 两次**各自独立**的 `ReviewRecord.report.results`，按 key 分类为 `resolved`（V1 有风险、V2 无）/`unchanged`（风险级不变）/`changed`（风险级变化但两边都有）/`new`（V2 新出现）/`unmatched`（V1 有、V2 找不到对应）。
- **为什么需要两个 Diff**：Clause Diff 回答"条款文本变了没有"，Risk Diff 回答"风险判断变了没有"——两者不是一回事：条款文本没变，LLM 两次判断也可能因为非确定性给出不同风险级（P-05）；条款文本变了，风险判断也可能没变（改的是无关紧要的措辞）。
- **如何比较**：Clause Diff 用 `clause_id` 精确匹配（V1/V2 切分方式相同，`clause_id` 编号规则一致，理论上应该对齐）；Risk Diff 用 `(source, clause_id/rule_id)` 作为 key——LLM 来源用 `clause_id`（schema 强制要求 LLM 结果必须带 `clause_id`），规则来源用 `rule_id`（同样是 schema 强制要求），而不是用需求原文提到的 `related_clause_ids`（可变长度、可能因条款文本变化而变化，匹配起来更不稳定，详见 ARCHITECTURE_DECISIONS）。
- **如何处理 clause_id**：两个 Diff 都不猜测——找不到匹配就明确标记（`matched=False`/`category="unmatched"`），不编造对应关系。
- **如何处理 V2 重新切分产生的子条款**：Clause Diff 只比较 `hierarchy_level==0` 的条级 Clause，不逐一比较款级子条款（这是当前范围有限的简化，如果 V2 重新切分后某条被拆分出不同数量的款，条级对比仍然成立，但看不到"具体哪一款变了"这个粒度）；Risk Diff 依赖的是 `ReviewResult` 本身的 `clause_id`/`rule_id`，如果 V2 重新切分导致条款编号变化较大，可能被分类为 `unmatched`——这是已知的匹配局限，不是 bug。

## 十二、未来持续迭代机制

这套知识库不是一次性文档。约定的迭代方式：

1. **开发**：完成一个重要模块或修复一个真实 bug 后，不是"顺手写几行注释就算了"，而是回到这套知识库补充记录。
2. **记录**：Claude（或后续开发者）更新 `docs/DEVELOPMENT_LOG.md`（这一阶段做了什么/为什么/遇到什么问题/最终方案/验证结果）、`docs/PITFALLS.md`（如果是真实 bug，用 12 字段格式记录）、`docs/PROJECT_KNOWLEDGE.md`（如果涉及模块职责或架构决策变化）、`docs/KNOWLEDGE_TREE.md`（更新对应节点的掌握程度评级）、`docs/INTERVIEW_QA.md`（补充对应的面试题）。
3. **学习 / 面试**：由 ChatGPT（或其他工具）根据这套知识库对开发者做项目面试——找出理解漏洞、补充知识、发现业务逻辑缺口、讨论 LangGraph 编排问题，必要时提出新的架构设计。
4. **确认后进入下一轮开发**：开发者确认下一步方向后，回到步骤 1。

形成闭环：**开发 → 记录 → 学习 → 面试 → 发现不足 → 补充知识 → 完善业务 → 完善 Agent/LangGraph → 再开发**。

---

## 附：四、模块级说明中的技术债务与状态

完整的"已完成并验证 / 已知但暂缓 / 技术债务 / 业务逻辑待完善 / LangGraph 待完善"分类见 `docs/KNOWLEDGE_TREE.md` 的"技术债务""待完善业务逻辑""LangGraph 待完善"三个节点，以及 `Labor_Contract_Review_Project_Report.md` 第十六~二十部分（项目根目录）。此处不重复展开，避免同一份分类在多个文件里维护、产生不一致。
