# 劳动合同智能审查系统 —— 项目复盘报告

> 整理日期：2026-09-29～30。本报告可脱离代码独立阅读，是对 `labor_contract_review` 项目截至本次整理时的完整复盘。内容以当前真实代码为最高事实依据，历史文档（`docs/DEVLOG.md`/`docs/INTERVIEW.md`/`docs/KNOWLEDGE_TREE.md`/`docs/PITFALLS.md`）与代码冲突之处已单独说明。**没有代码/测试/脚本证据支撑的内容一律标注"未找到证据"，不编造。** 与本报告配套的项目内部知识库见 `docs/PROJECT_KNOWLEDGE.md`、`docs/DEVELOPMENT_LOG.md`、`docs/PITFALLS.md`、`docs/INTERVIEW_QA.md`、`docs/KNOWLEDGE_TREE.md`、`docs/ARCHITECTURE_DECISIONS.md`、`docs/CAPABILITY_GAPS.md`。

---

## 第一部分：项目到底做了什么

这是一个"劳动合同智能审查系统"：输入一份 `.txt` 格式的劳动合同，系统自动把合同切成条款，对每个条款检索《劳动合同法》相关条文作为依据，用 LLM（DeepSeek）判断这个条款是否存在法律风险，同时用一套确定性规则补充检查两类稳定漏检的问题（试用期工资比例、试用期期限阶梯），把两边的结果合并成一份完整的审查报告。

在此基础上，系统支持律师对某个具体条款提出修改意见，由一个"Modification Agent"（通过真实 Function Calling 调用一个 `modify_clause` 工具）生成修改后的候选文本，候选文本先经过程序化的 Validator 校验（防止越界修改、占位符、条款编号丢失），再由律师人工确认或拒绝——系统没有任何自动确认逻辑。律师确认若干条修改后，可以生成一份"V2"合同：系统会基于原始合同（V1）的字符偏移量，把已确认的修改局部替换进去，重建出完整的新合同全文，再完整地重新走一遍解析、切分、审查流程（不是"打补丁"）。最后系统提供两种对比：条款级 Diff（哪些条款文本变了）和风险级 Diff（哪些风险解决了、哪些是新出现的、哪些没变）。

项目有一个完整实现的 FastAPI 后端和一个 React 前端，律师可以通过浏览器完成从上传合同到查看 V1/V2 风险对比的全部操作。

## 第二部分：业务场景

目标用户是律师、企业 HR/合规人员——需要审查劳动合同、并且愿意在系统给出的建议基础上做最终专业判断的用户，不是面向普通劳动者的自助解释工具。业务问题：劳动合同审查需要专业法律知识和大量重复劳动，人工逐条对照法律条文容易漏检、难以保证一致性；律师提出修改意见后，手动改写合同文本、追踪修改历史、对比新旧版本风险变化也是重复劳动。本项目用"RAG 检索真实法条 + LLM 判断 + 规则补充确定性检查"辅助审查，用"受限的 Function Calling Agent + 人工确认闭环"辅助修改，定位始终是"辅助工具"而不是"自主决策系统"——所有会实际改变合同内容的动作（生成 V2）都需要人工确认在前。

## 第三部分：完整系统架构

```
React（frontend/）
    │  fetch（api/client.js，唯一 HTTP 出口，唯一负责把后端错误格式转成可展示文本）
    ▼
FastAPI（api/app.py + dependencies.py + routes/contracts.py + routes/modification.py）
    │  lifespan 启动时构造重对象（ContractManager/embedder/knowledge_base/retriever/
    │  llm_client/reviewer/rule_checker/modification_agent），Depends 请求期间复用
    ▼
Contract / Parser / Clause（contract/manager.py → parser/document_parser.py → clause/clause_splitter.py）
    │  纯文件系统持久化；contract_id 正则校验防路径穿越；原文件只写一次
    ▼
Review Pipeline（review/pipeline.py，真实 LangGraph StateGraph）
    │
    ├─▶ LLM Review（review/reviewer.py：query→RAG→Prompt→DeepSeek）──┐
    │                                                                 ▼
    └─▶ Rule Check（rules/checker.py，独立运行）──────────────▶ Merge（拼接）──▶ ReviewReport
                                                                                  │
                                                          contract_manager.save_review()（不可覆盖）

Modification Agent → V1 → V2 → 重新 Review（独立于 LangGraph 主图，手写状态机）
    │
    律师创建 ModificationTask（pending）
        → ModificationAgent（真实 Function Calling：modify_clause，tool_choice="auto"）
        → modification/tool.py（第一道越界校验）→ modification/validator.py（第二道校验）
        → reviewing（等待人工）→ confirm/reject（HITL，无自动确认）
        → 全部任务确认/转人工后：generate_v2（按条重建全文，字符偏移量局部替换）
        → 新的内部 contract_id（完整重新 parse+split）
        → run_v2_review（复用未改动的 run_review）
        → clause_diff（按 clause_id 对比原文）/ risk_diff（按 source+clause_id/rule_id 对比风险）
```

## 第四部分：完整业务数据流

见 `docs/PROJECT_KNOWLEDGE.md` 第二节"完整业务流程"（21 个步骤，逐一标注实现状态与对应代码文件），此处不重复展开，避免同一份内容在两个文件里分别维护产生不一致。核心结论：从合同上传到 V1/V2 风险对比，全部 21 个步骤均已实现，只有第 3 步（合同解析）有格式限制（仅 `.txt`）。

## 第五部分：模块职责与代码对应

| 模块 | 核心文件 | 一句话职责 |
|---|---|---|
| Contract | `contract/manager.py` | 合同/审查记录/修改任务/版本映射的文件系统存储与状态推进 |
| Parser | `parser/document_parser.py`、`parser/contract_parser.py` | 文件→纯文本，不改动原文 |
| Clause | `clause/clause_splitter.py`、`clause/contract_clause_splitter.py` | 全文→条款树（条/款层级），保证字符偏移量不变量 |
| RAG | `rag/embedding.py`、`database.py`、`loader.py`、`retrieval.py` | 法律文本检索，产出 `Evidence` |
| Review | `review/reviewer.py`、`review/schemas.py` | 单条款审查：query→RAG→Prompt→LLM→`ReviewResult` |
| Rules | `rules/checker.py`、`merge.py`、`probation_*.py` | 确定性补充检查 + 纯拼接合并 |
| Pipeline | `review/pipeline.py` | LangGraph 编排 Review 全流程 |
| API | `api/app.py`、`dependencies.py`、`routes/*.py` | HTTP 接口，依赖注入，异常映射 |
| 前端 | `frontend/src/App.jsx`、`api/client.js`、`components/*.jsx` | 律师操作界面 |
| Modification | `modification/agent.py`、`tool.py`、`validator.py`、`prompts.py`、`service.py` | 修改闭环：Agent 生成→校验→HITL→V2→Diff |
| Schemas | `schemas/*.py` | 全部模块共享的数据契约（Pydantic v2） |
| Config | `config/settings.py` | 跨模块默认值集中管理，不放密钥 |

详细的"业务职责→Agent职责→工程职责→输入→输出→模块关系→对应代码文件→设计原因"见 `docs/PROJECT_KNOWLEDGE.md` 第四节。

## 第六部分：Agent / LangChain / LangGraph

- **Agent 的界定**：本项目对"Agent"采用严格定义——LLM 自主决定下一步做什么。Review 链路（`ClauseReviewer`）不是 Agent，流程固定、LLM 只在一个节点里判断。Modification Agent **是** Agent，但是"带校验和人工确认的单次工具调用 Agent"：真实 Function Calling（`tools=[schema]`，模型自主决定是否调用、怎么填参数），但工具集固定为一个、不做多步规划、决策权（是否生效）最终在人手里。
- **LangChain**：只用到部分组件——`langchain_core.embeddings.Embeddings` 接口、`HuggingFaceEmbeddings`、`RecursiveCharacterTextSplitter`。**没有证据**表明使用过 LangChain 的 `AgentExecutor`/`Chain` 抽象；Modification Agent 是直接基于 OpenAI SDK 手写的 Function Calling，不是 LangChain 的 Agent 框架。
- **LangGraph**：Review 主链路用真实 `StateGraph`（6 字段 State、5 Node、7 无条件 Edge、一次并行+汇合），12 个 graph 测试在真实 LangGraph 1.2.12 上通过。**如实说明**：只用到很小一部分能力，条件边/reducer/retry/checkpoint/streaming 一个都没用。Modification 链路**不在**这张图里，是独立的手写状态机。

## 第七部分：RAG

定位是**证据层**，只负责"给条款找法律依据"，不决定"审查哪些条款"（那是 `ClauseSplitter` 切分结果决定的）。法律文本按"第X条"切分，一条一个 `Evidence`；BGE-M3 归一化稠密向量写入 Chroma 持久化；检索时 query 只去条款编号、保留标题（P-03 修复后）。当前局限：知识库仅 14 条节选、无相关性阈值、`distance` 不同集合不可比。Modification 阶段**不重新检索**，复用审查阶段已保存的 `legal_basis`，避免两个阶段依据不一致。真实验证：三个 query 第一名全部命中相关法条。

## 第八部分：Review

LLM Review（概率性判断，依赖 RAG 证据）+ RuleChecker（确定性代码，独立运行）+ Merge（纯拼接，不覆盖不去重）。为什么不是单纯规则系统：规则无法覆盖法律语义的丰富性，且开发成本高（当前仅 2 条）。为什么不是单纯 RAG+LLM：真实验证证明了结构性盲区（单条款看不到其他条款，P-04）和非确定性（P-05），需要规则补足。两者互补：LLM 覆盖面广但不稳定，规则窄但确定、能跨条款判断。真实验证：10 条款合同，12 = 10（LLM）+ 2（规则），规则只影响 clause_001/clause_004。

## 第九部分：Modification Agent

组件：`ModificationAgent`（生成候选）、`modify_clause` Tool（唯一工具）、`modification/tool.py`（第一道越界校验）、`modification/validator.py`（第二道范围/完整性/结构校验，纯函数不调 LLM）。流程：律师创建任务（pending）→ `start` 调用 Agent → 校验通过进 `reviewing`（等待人工）→ 律师 `confirm`（→`confirmed`）或 `reject`（附带新意见，→`rejected`，可重试）。重试永远基于 V1 原文+全部历史意见，不基于上一轮候选。最多 3 次重试，失败后 `needs_human`（唯一失败终态）。没有任何自动确认逻辑——这是本项目最核心的安全边界。真实联调 DeepSeek 时暴露并修复了一次真实限制：Thinking 模式不支持强制 `tool_choice`，改为 `"auto"`（P-21）。

## 第十部分：V1→V2

V1 是原始 `contract_id`，永不被覆盖。V2 是内部另一个、完整独立的 `contract_id`：`generate_v2` 按"条"为单位，基于 V1 原始全文的字符偏移量做局部替换重建全文（已确认修改的条款用候选文本替换，其余原样保留原文缝隙），写入临时文件（`newline=""`，见第十四部分 P-24），用完全未改动的 `create_contract`/`parse_contract`/`split_contract` 正常创建。`ContractVersion` 记录"v2 → 内部 contract_id"的映射，存在 V1 目录下，永久保留、不可覆盖生成。V2 必须完整重新解析、切分、审查（不是打补丁）：解析/切分是因为全文内容变了，偏移量需要重新计算；审查是因为 Validator 只做结构校验，不代表完整的法律风险判断已经完成，且 LLM 非确定性意味着重新审查本身可能给出有意义的新信息。

## 第十一部分：Clause Diff / Risk Diff

Clause Diff（`ModificationService.clause_diff`）按 `clause_id` 对比 V1/V2 两边条级（`hierarchy_level==0`）原文，`matched=False` 时不猜测对应关系。Risk Diff（`ModificationService.risk_diff`）对比 V1/V2 两次**各自独立**的审查结果，按 `(source, clause_id/rule_id)` 做 key（不是需求原文提到的 `related_clause_ids`，理由见下），分类为 `resolved/unchanged/changed/new/unmatched` 五类。为什么需要两个 Diff：条款文本没变，风险判断也可能因 LLM 非确定性而变化；反之条款文本变了，风险判断也可能不变。为什么用 `clause_id`/`rule_id` 而不是 `related_clause_ids`：前者是 schema 强制保证存在的、稳定的标识，后者是可变长度、可能因文本变化而变化的集合，匹配起来更不稳定。

## 第十二部分：重要架构决策

完整的 15 条决策（含【决策】【当时的问题】【考虑过的方案】【为什么选择当前方案】【没有选择其他方案的原因】【当前是否仍然成立】【未来什么时候需要重新评估】）见 `docs/ARCHITECTURE_DECISIONS.md`。摘要：

- 为什么用 LangGraph（AD-01）：并行+汇合声明式表达，可读可测；**诚实说明**目前只用到很小一部分能力。
- 为什么 RAG 是证据层、RuleChecker 是补充、所有条款仍需 LLM Review（AD-03/04/05）：三者职责边界清晰，各自解决对方解决不了的问题。
- 为什么暂时不做强 Tool Selection Agent、Modification Agent 只有一个核心工具（AD-06/07）：当前业务需求只有一种操作，过早设计多工具框架是没有真实需求支撑的过度设计。
- 为什么必须 Human Confirmation、Reject 从 V1+累积意见重新生成、最多 3 次、失败后 needs_human（AD-08~10）：合同修改是高风险操作，需要明确的安全边界和有限的重试上限。
- 为什么 V1 不覆盖、V2 必须重新解析切分审查（AD-11/12）：审计完整性 + 正确性优先于性能。
- 为什么用 filesystem-JSON 暂不用 SQLite（AD-13）：**这个决定在开发期间没有被正式确认过**（如实标注），当前无跨合同查询/并发需求。
- bridge 模块（`parse_contract`/`split_contract`）未来是否需要删除（AD-14）：**本次整理发现**这两个函数被 Review 和 Modification 两条链路共同复用，"收编进 pipeline"这条原计划应该重新评估。
- RAG interface-data boundary 是否需要继续观察（AD-15）：**证据不足，暂不评级**——现有文档中没有找到这个问题曾被显式讨论过的记录。

## 第十三部分：历史方案与设计演进

【历史方案】与【当前方案】对照（完整过程见 `docs/DEVELOPMENT_LOG.md`）：

| 领域 | 【历史方案】最初设计 | 为什么被推翻 | 【当前方案】 |
|---|---|---|---|
| Rules | `ContractFacts` 统一事实抽取层 + 通用规则引擎 | 与真实使用方式（逐条沉淀的补丁）不匹配，是过度设计 | 每条规则自己识别、提取、判断，不依赖统一模型 |
| Rules 合并策略 | 规则结果整条替换 LLM 结果 | 会丢掉 LLM 发现、规则未覆盖的其他风险 | 纯拼接（`llm_results + rule_results`） |
| API 依赖注入 | `ModificationService` 作为启动时单例存进 `AppState` | 绑死旧 `ContractManager`，测试 override 失效（P-20） | 现场组装：`Depends(get_contract_manager)+Depends(get_modification_agent)` |
| Function Calling | `chat_with_tool` 强制指定函数名的 `tool_choice` | DeepSeek Thinking 模式拒绝强制 `tool_choice`（P-21） | `tool_choice="auto"` |
| V2 全文重建 | `_build_v2_text` 只拼接 `hierarchy_level==0` 文本 | 错误假设"款的内容已经包含在条里"，导致款级内容丢失（P-22） | `_group_clauses_by_article`+`_reconstruct_article_text`，按字符偏移量局部替换重建 |
| `save_review` | 内部硬编码 `contract_version="v1"` | V1/V2 review_id 撞车，产生误导性巧合（P-23） | 增加显式 `contract_version` 参数，调用方显式声明 |
| V2 文件写入 | `write_text(..., encoding="utf-8")`（默认 `newline=None`） | Windows 上把原有 `\r\n` 转写成 `\r\r\n`，误判未修改条款为已修改（P-24） | `newline=""`，完全关闭换行转换 |

## 第十四部分：真实 Bug / PITFALLS

`docs/PITFALLS.md` 共收录 24 条真实问题（P-01~P-21 为 8 字段格式，P-22~P-24 为本次整理统一改写的 12 字段格式），涵盖测试/环境、外部服务、RAG、架构、LLM、数据模型、存储、工程、依赖注入、Function Calling、V1/V2/Diff 等类别。其中面试价值最高、最值得完整讲述的三条：

1. **P-01 沙箱替身≠真实依赖**：四个真实案例（假 openai 模块失效、HuggingFaceEmbeddings 构造即加载、load_dotenv 读到真实 key、LangGraph 替身局限）证明"沙箱通过≠真实通过"，这条经验在 Phase 3 的 P-20/P-21/P-22/P-24 中被反复验证。
2. **P-22/P-23/P-24（本次整理重点改写为 12 字段格式）**：V2 重建款级内容丢失、review_id 撞车、换行符损坏——三个都是在真实浏览器验收测试中发现、有完整"最初怀疑→定位过程→真正根因→解决方案→验证结果"证据链的 bug，且都已在真实环境（含 Windows）验证修复生效。
3. **P-20 依赖注入生命周期**：一个"表面是路由/schema 问题，实际是依赖注入生命周期管理"的真实案例，提炼出"单例 vs 现场组装"的判断标准。

## 第十五部分：测试与验证

- **自动化 pytest**：`tests/` 目录 24 个测试文件，本次整理用 `grep -c "^def test_"` 实测得出 **298 个测试函数定义**（未真实运行 pytest，本沙箱同样缺少真实依赖）。历史记录的 258（Phase 1/2 末尾真实运行结果）是更早阶段的数字，Phase 3 新增的 `test_api_contracts.py`（34）、`test_api_dependencies.py`（4）、`test_api_full_flow.py`（2）等解释了增量。
- **手工验证脚本**：`scripts/` 目录 13 个（不含 `_common.py`/`_samples.py` 两个工具文件），覆盖 RAG/规则/pipeline/DI（`verify_di_fix.py`）/Function Calling（`verify_agent_function_calling.py`）/V2 重建（`verify_v2_article_reconstruction.py`）/换行修复（`verify_p24_newline_write.py`）等。
- **真实环境验收**：Phase 1/2 有完整的真实 E2E 记录（5→5+2→7，0 失败）；Phase 3 的三个真实 bug（P-22/23/24）都经过用户在真实浏览器（含真实 Windows 部署环境）上的完整验收确认。
- **已验证 vs 未验证明确区分**：`chat_with_tool` 的 `tool_choice="auto"` 修复目前只在沙箱假客户端上验证过参数传递正确，**真实 DeepSeek 联调的最终确认待用户在真实环境反馈**（代码层面已合入，机制上已核实）。
- **关键技术债务**：**Modification Agent/Tool/Validator/Service 的业务逻辑没有对应的 `tests/test_modification*.py` 自动化 pytest 覆盖，只有手工运行的 verify 脚本**——本次整理核实 `tests/` 目录列表得出此结论。

## 第十六部分：当前项目完成度

已完成并有真实验证证据的部分：完整审查链路（V1）、完整修改闭环（Modification Agent+HITL）、V2 生成、Clause Diff、Risk Diff、FastAPI 后端、React 前端、三次真实 bug 的定位与修复。未完成/有明确限制：PDF/DOCX/OCR 解析、鉴权与多用户、批量处理、`output/` 结果格式化（仍是空包）、知识库规模化、Modification 模块的自动化测试覆盖。

## 第十七部分：技术债务

1. Modification 模块缺少自动化 pytest 覆盖（只有手工 verify 脚本）。
2. `legal_basis` 没有程序化校验，只靠 Prompt 约束和人工观察。
3. `_build_v2_text` 条与条之间固定用 `"\n\n"` 分隔，不是从原文取真实缝隙（已知、范围有限的简化）。
4. `clause_diff` 是纯字符串比较，没有格式规范化——三次真实 bug 修复解决了"数据本身"的问题，但未来若出现新的文本差异来源（如律师直接编辑），仍可能被误判。
5. `schemas/contract.py`/`schemas/_time.py` 文档字符串仍提到 SQLite，与实际的文件系统实现不符（文档漂移，本次复核确认依然存在，未改代码）。
6. `contract/manager.py` 新增的三个子目录（review/modification_tasks/versions）各自独立编号，没有跨文件事务保护，真实并发场景未验证。

## 第十八部分：暂缓问题（当前有意不做，非缺陷）

1. LangGraph 的条件边/重试/checkpoint（P-14，已知架构决策）。
2. 强 Tool Selection Agent（AD-06，当前只有一个工具，无需求支撑）。
3. Modification 阶段重新检索 RAG（有意复用审查阶段已有依据，避免不一致）。
4. 规则去重（合并策略明确选择"拼接不去重"，等真实数据证明有必要再做）。

## 第十九部分：业务逻辑待完善

1. 跨条款分析仅限规则手工覆盖的两类问题，无通用机制。
2. 知识库覆盖仅 14 条节选，规则仅 2 条，大量条款类型（竞业限制、保密、解除条件等）只靠 LLM 判断，无规则兜底。
3. unknown/needs_review 类状态未系统化，目前靠 LLM 文字说明"依据不足"表达。
4. 修改任务之间没有依赖图，只做最简单的"同条款冲突检测"。
5. 多用户协作场景未设计（无鉴权，`created_by` 是固定默认值）。

## 第二十部分：LangGraph 待完善

1. Conditional Routing / Retry / Error Recovery：当前节点异常直接终止整图，State 无失败路由信号（P-14）。
2. Tool Selection：Modification Agent 的工具选择场景完全没有被验证过（当前只有一个工具）。
3. Cross-Clause Analysis：目前只靠 2 条手工规则做跨条款判断，没有通用机制。
4. 更复杂 HITL：当前 HITL 是单轮确认/拒绝，没有多轮协商、没有多人审批流程。
5. Modification 链路本身未使用 LangGraph（是手写状态机）——如果未来该链路复杂度提升，是一个可以评估引入 LangGraph 的候选场景。

## 第二十一部分：我的知识与能力现状

完整清单见 `docs/CAPABILITY_GAPS.md`。已有真实代码/测试/脚本证据支撑"已经实际接触并使用"的技术：Pydantic v2、FastAPI（含依赖注入生命周期管理的真实踩坑）、LangChain 部分组件（Embeddings 接口、文本切分器）、LangGraph（State/Node/Edge/并行/汇合）、RAG（BGE-M3+Chroma）、Function Calling（含真实 DeepSeek 限制的定位修复）、Human-in-the-loop、React（函数组件+Hooks）、文件系统持久化设计、pytest 测试分层、Mock 与真实依赖的边界判断。

## 第二十二部分：知识缺口

有真实影响、需要后续学习的缺口（完整列表见 `docs/CAPABILITY_GAPS.md`）：LangGraph 的条件边/重试/checkpoint（简历上"熟悉 LangGraph"最容易被追问的地方）、Agent 的多工具选择与自主规划（当前只验证过单工具场景）、Modification 模块的自动化测试覆盖（技术债务，且是可以立刻动手补的高性价比缺口）、跨平台 I/O 的系统性认知（P-24 说明这是靠真实踩坑才学到的）、向量检索的评估方法论（当前全靠人工观察）。

## 第二十三部分：项目面试题

完整题库（项目级/架构级/Agent/LangGraph/RAG/Review-规则/工程/Bug-Debug/设计题，每题含【面试问题】【考察点】【我应该能够回答什么】【当前项目中的真实答案】【容易答错的地方】五个字段）见 `docs/INTERVIEW_QA.md`。必考题"为什么 V2 中未修改条款出现额外空行"（P-24 完整 现象→定位→根因→修复→验证 流程）已在该文件 Q8-1 完整展开。

## 第二十四部分：后续学习与开发方向

按"真实测试暴露什么再做什么"的一贯原则，建议优先级：

1. **给 Modification 模块补自动化 pytest 覆盖**——这是当前最明确、最容易验证收益的技术债务，用 mock 的 `llm_client` 覆盖状态机全部转移路径。
2. **用更多真实合同迭代规则和知识库**——当前样本量小（1 份 10 条款的验证合同），规则和知识库覆盖面窄是限制系统实用性的最大因素。
3. **给 Modification 链路设计一张小的 LangGraph 图**——比在 Review 主图上硬加条件边更安全，也是补齐"LangGraph 条件路由"这条知识缺口的合适场景。
4. **补齐 PDF/DOCX 解析**——当前只支持 `.txt`，是实际可用性的一个明显限制。
5. **引入鉴权和多用户支持**——如果这个项目要真正给多个律师用，这是必须做的前置工作。

## 第二十五部分：完整项目知识树

完整的知识树（含每个节点的掌握程度评级和证据、"文档与代码不一致"记录）见 `docs/KNOWLEDGE_TREE.md`。顶层节点：项目 / 业务 / 系统架构 / Contract / Parser / Clause / Review / RAG / RuleChecker / LangChain / LangGraph / Agent / Function Calling / HITL / Modification / V1-V2 / Diff / FastAPI / React / 工程实践 / 测试 / 历史设计 / PITFALLS / 技术债务 / 待完善业务 / LangGraph 待完善 / 面试能力。评级严格依据真实代码/测试/脚本证据，证据不足的节点明确标注"证据不足，暂不评级"，不做主观臆测。

---

*本报告与项目内部 `docs/` 目录下的知识库文档互为补充：本报告是可独立阅读的复盘叙述，`docs/` 下的文档是可持续更新、按主题拆分的详细知识库。两者应保持同步更新，见 `docs/PROJECT_KNOWLEDGE.md` 第十二节"未来持续迭代机制"。*
