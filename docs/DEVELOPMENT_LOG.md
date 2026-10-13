# 开发日志（DEVELOPMENT_LOG）

> 本文件是本次知识库整理（2026-09-29）新建的正式开发日志，按 spec 要求使用确切文件名 `docs/DEVELOPMENT_LOG.md`。
> 内容 = 原 `docs/DEVLOG.md`（2026-09-28，覆盖 schemas → LangGraph 的 Phase 1/2）的全部真实内容，**逐字合并**，
> + 本次新增的 Phase 3（Modification Agent / Function Calling / HITL / V1-V2 / Clause Diff / Risk Diff / API / 前端 / 三次真实 Bug 修复）。
> 原文件 `docs/DEVLOG.md` 保留作为历史存档，不删除。
> 数据来源：开发过程中的设计讨论，以及在本地真实环境运行后贴出的输出。**没有出现过的结果不会写在这里。**
> 图例：✅ 已在真实环境验证　🧪 仅自动化测试　⚠️ 已知限制　📝 未实现

## 一、开发方式

- **严格分步**：每个阶段先给设计，确认后再编码；完成后附测试结果与数据流，再进入下一阶段。开发顺序：schemas → contract → parser → clause → RAG → LLM Review → RuleChecker → LangGraph（State → Node → Edge → 搭建）→ 整理 → **API/前端 → Modification Agent → Function Calling → HITL → V1/V2 → Diff → 三次真实 Bug 修复（P-20/P-21/P-22/P-23/P-24）**。
- **两类验证要分清**：代码开发发生在**没有网络的沙箱**里，BGE-M3、Chroma、DeepSeek、真实 LangGraph、真实 FastAPI 都装不上，只能用替身验证代码逻辑；**真实效果全部由用户（bh）在本地真实环境（Windows + PowerShell + venv）运行后确认**。"沙箱通过"不等于"真实通过"，这是本项目最重要的经验之一（见 [PITFALLS.md P-01](PITFALLS.md)）。Phase 3 里这条经验被反复验证：P-20（依赖注入）、P-21（DeepSeek Thinking 模式）、P-22（V2 重建丢款）、P-24（换行符损坏）全部是"沙箱全绿、真实环境才暴露"。
- **验证脚本不允许静默降级**：真实环境脚本遇到模型加载失败、知识库为空、缺 API Key，只报告环境问题并退出，不会自动换成假实现。

## 二、时间线总览

| 阶段 | 内容 | 关键决策 | 验证 |
|---|---|---|---|
| 1 | schemas | 唯一的数据契约层；`ReviewResult` 一致性校验；`summary` 等用计算字段 | 🧪 |
| 2 | contract | 纯文件系统存储；`contract_id` 校验防路径穿越；原文件只写一次 | 🧪，本地 pytest 通过 |
| 3 | parser | 解析不改动原文；PDF/DOCX/OCR 先留占位 | 🧪 |
| 4 | clause | 正则结构切分 + 超长条款二次切分；偏移量不变量 | 🧪 |
| 5 | rag | 独立于 contract/parser/clause；按条切分；BGE-M3 稠密向量 | 🧪 |
| 6 | rag 真实初始化 | 真实 BGE-M3 写入 Chroma，再从持久化库检索 | ✅ 三个 query 第一名全部命中 |
| 7 | llm + review | 最终结果复用 `ReviewResult`，新增 `LLMReviewOutput`；DeepSeek | 🧪 |
| 8 | 单条款真实验证 | 发现并修复：模型名过期、query 丢标题关键词 | ✅ 三个案例 |
| 9 | rules | 经过重设计：删除 `ContractFacts`，规则各自封装；合并用拼接 | ✅ 10 条款验证 |
| 10 | LangGraph 设计 | State 6 字段 → 5 Node → 7 Edge，无条件边 | 设计确认 |
| 11 | LangGraph 搭建 | `review/pipeline.py`；真实 E2E | ✅ 5 → 5 + 2 → 7 |
| 12 | 整理 | `config/settings.py`、测试分层、scripts 整理 | 🧪 |
| 13 | 整理后复验 | 真实 pytest 与 E2E；定位 marker warning | ✅ 258 passed |
| 14 | 文档（第一轮） | README + docs/ | — |
| 15 | **API（FastAPI）** | `api/app.py`/`dependencies.py`/`routes/contracts.py`；lifespan + AppState + Depends | 🧪 + ✅ 真实 uvicorn 启动 |
| 16 | **前端（React + Vite）** | `App.jsx` 唯一持有状态、唯一调用 API；`api/client.js` 唯一 fetch 层 | ✅ 真实浏览器联调 |
| 17 | **依赖注入 bug（P-20）** | 发现 `ModificationService` 被错误设计成启动时单例，绑死旧 `ContractManager` | ✅ `scripts/verify_di_fix.py` 11/11 + 本地 pytest |
| 18 | **Modification Agent + Function Calling** | `modification/agent.py`/`tool.py`/`validator.py`/`prompts.py`；真实 DeepSeek Function Calling | ✅ `scripts/verify_agent_function_calling.py` |
| 19 | **DeepSeek Thinking 模式冲突（P-21）** | `tool_choice` 从强制指定函数名改为 `"auto"` | ✅ 沙箱替身 10/10，真实联调待 bh 确认（已合入代码） |
| 20 | **HITL 状态机** | 6 状态（pending/reviewing/rejected/needs_human/confirmed/completed），最多 3 次重试 | 🧪（设计确认，代码已实现） |
| 21 | **V1/V2 + Clause Diff + Risk Diff** | `ContractVersion` 映射记录；V2 完整重新解析/切分/复审；两种 Diff | ✅ `scripts/verify_modification.py` |
| 22 | **Fix B：V2 重建丢款（P-22）** | `_group_clauses_by_article` + `_reconstruct_article_text` 按字符偏移量局部替换重建 | ✅ `verify_v2_article_reconstruction.py` 68/68 + bh 真实验收 |
| 23 | **Fix A：review_id 撞车（P-23）** | `save_review` 增加显式 `contract_version` 参数，移除内部硬编码 | ✅ `verify_modification.py` 73/73 + bh 真实验收 |
| 24 | **Fix C：换行符损坏（P-24）** | `generate_v2` 写入时改用 `newline=""` | ✅ `verify_p24_newline_write.py` 6/6 + bh 真实 Windows 浏览器验收 |
| 25 | **本次知识库整理（2026-09-29）** | 扫描全量代码，建立 PROJECT_KNOWLEDGE/DEVELOPMENT_LOG/PITFALLS/INTERVIEW_QA/KNOWLEDGE_TREE/ARCHITECTURE_DECISIONS/CAPABILITY_GAPS + 独立复盘报告 | 文档整理，未改动业务代码 |

## 三、模块开发日志（Phase 1/2，原文完整保留）

### 3.1 schemas

- **模块**：`schemas/`（`Clause`、`Evidence`、`Contract`、`ReviewResult`、`ReviewReport` 等）
- **目的**：定义各模块之间传递的对象。模块之间只允许传递这里的对象，不传随意格式的 dict。
- **为什么需要它**：各模块要独立开发、独立测试，需要一份稳定的数据契约；`schemas` 自己不依赖任何模块，所以不会引入循环依赖。
- **设计方案**：Pydantic v2；`RiskLevel`（`none/low/medium/high`）内部只用英文值，界面通过映射转中文；`ReviewSource`（`llm` / `rule`）；把"不合法的组合"挡在模型构造时。
- **具体实现**：
  - `ReviewResult`：`risk` 必须与 `risk_level` 一致；LLM 来源必须有 `clause_id` 且不能有 `rule_id`；规则来源必须有 `rule_id`，`clause_id` 可为空。
  - `Clause`：`end_char >= start_char`；`Contract`：时间必须带时区（UTC）、`sha256` 为 64 位小写十六进制、`failed` 状态必须有 `error`。
  - `ReviewReport`：`summary` 和 `overall_risk_level` 是**计算字段**，由 `results` 推出，不单独存储。
- **遇到的问题**：① `Clause` 起初没有 `contract_id`，条款无法绑定合同，后来补为必填；② 设计时没有明确 `ReviewResult` 是"一条款一结果"还是"一风险一结果"，到规则阶段才澄清；③ 文档字符串后来漂移（见下）。
- **如何定位**：① 合同数据流打通时发现 `save_clauses` 无法校验条款属于哪份合同；② 分析 `ReviewReport.results` 是没有唯一性约束的扁平列表。
- **解决方案**：① 补 `contract_id`，`save_clauses` 校验全部一致；② 明确 `ReviewResult` 是**风险点**粒度，一个条款可对应多条结果。
- **为什么选这个方案**：计算字段避免"汇总与明细不一致"；把非法组合挡在构造处，比在业务代码里到处检查可靠。
- **最终结果**：`tests/test_schemas.py` 39 个测试。⚠️ `schemas/contract.py`、`schemas/_time.py` 的文档字符串仍写 SQLite（本次整理复核代码确认这个漂移依然存在），`schemas/review_report.py` 提到"重试"和"formatter"，这些**代码里都不存在**；本次整理同样不允许改代码，只记录。
- **面试可能被问到什么**：为什么用 Pydantic？为什么 `summary` 用计算字段？`ReviewResult` 为什么是风险点粒度？
- **后续可以怎么优化**：让 `ReviewResult` 能携带 `Evidence`；修正漂移的文档字符串。

### 3.2 contract

- **模块**：`contract/manager.py`（`ContractManager`）
- **目的**：管理合同文件的本地存储：原文件、解析文本、条款、元数据；**Phase 3 起还管理审查历史记录、修改任务、版本映射**（见下方 3.13）。
- **为什么需要它**：审查是多步骤流程，中间产物需要落盘并按合同隔离；原文件是审计依据，不能被覆盖。
- **设计方案**：不使用数据库，纯文件系统。布局：`<root>/<contract_id>/{original_file/<文件名>, parsed_text.txt, clauses.json, metadata.json, review/, modification_tasks/, versions/}`。状态 `uploaded → parsed → split → reviewed`。
- **具体实现**：
  - `contract_id = uuid4().hex`，访问目录前用正则校验，防止 `../` 穿出根目录（因为它以后会来自 API——Phase 3 已经证实这一点）。
  - 原文件**只写一次，拒绝覆盖**；sha256 在保存后的副本上分块计算；`metadata.json` **最后写入**并用临时文件 + `os.replace` 原子替换，所以它存在就代表合同创建完整；创建中途失败会 `rmtree` 清理整个目录。
  - `save_clauses` 校验每个条款的 `contract_id` 与目标合同一致。
  - **（Phase 3 新增）** `save_review`：审查记录不可覆盖，按 `contract_version_序号` 编号（`v1_001`、`v2_001`……）；曾经硬编码 `contract_version="v1"`，已在 Fix A（P-23）修复为显式参数。
  - **（Phase 3 新增）** `create_modification_task` / `list_modification_tasks` / `get_modification_task` / `update_modification_task`：修改任务的完整 CRUD，任务 id 按顺序编号（`task_001`……），每次更新整条覆盖写入（先写临时文件再 `os.replace`）。
  - **（Phase 3 新增）** `save_version` / `list_versions` / `get_version`：`ContractVersion` 映射记录，存在【原合同】目录下的 `versions/`，同一 `version_number` 不允许覆盖生成。
- **遇到的问题**（Phase 1/2）：`Path.read_text()` 不支持 `newline` 参数，读取 `parsed_text.txt` 时换行被转换，破坏了条款偏移量。
- **如何定位**：写"解析 → 切分"的集成测试时，`full_text[start:end] == original_text` 的不变量断言失败。
- **解决方案**：读写 `parsed_text.txt` 用 `open(..., encoding="utf-8", newline="")`，关闭换行转换。
- **为什么选这个方案**：不变量是前端定位和审计追踪的依赖，宁可在存储层严格保持原文。
- **最终结果**：`test_contract.py` 23 个测试（另有 parser / clause 的集成测试经过它）；本地 pytest 通过。⚠️ **早期需求提到过用 SQLite 保存元数据，最终实现是纯文件系统 JSON**，这个差异开发期间没有正式确认过，整理时如实记录。V1/V2 都用这同一套纯文件系统模型，V2 的数据实际存在【另一个内部 contract_id】的目录下（详见 3.14）。
- **面试可能被问到什么**：为什么不用数据库？怎么防路径穿越？为什么 `metadata.json` 最后写？V2 的数据存在哪里？
- **后续可以怎么优化**：需要检索、并发、审计时再引入数据库；Modification 相关的三个子目录（review/modification_tasks/versions）目前各自独立编号、独立文件锁，没有跨文件的事务保证——真实并发写入（例如同时对同一任务调用两次 start）目前没有加锁保护，这是一个已知但未验证是否会真实触发的风险点。

### 3.3 parser

- **模块**：`parser/document_parser.py`、`parser/contract_parser.py`
- **目的**：把上传文件转换成纯文本。
- **为什么需要它**：切分和审查只处理文本；文件格式的差异应该隔离在这一层。
- **设计方案**：`DocumentParser` 按后缀分发给 `BaseParser` 子类，可扩展注册。**不改动原文内容**（不 strip、不换行规范化）。
- **具体实现**：`TxtParser` 支持 BOM 检测（UTF-16/32、utf-8-sig），回退 gb18030，拒绝二进制和空内容。`PdfParser`、`DocxParser`、`OcrParser` 是占位，调用抛 `NotImplementedError`；API 层（`api/routes/contracts.py`）把这个 `NotImplementedError` 映射成 HTTP 415，当作"格式暂不支持"而不是服务端 bug。`parse_contract` 是连接 `ContractManager` 与 `DocumentParser` 的**过渡桥接**，Phase 3 的 V2 生成（`modification/service.py::generate_v2`）直接复用这个桥接函数，未做任何改动。
- **遇到的问题**：编码不确定；一旦解析阶段改了换行，条款偏移量就失效。
- **如何定位**：集成测试覆盖了各种编码和状态流转。
- **解决方案**：解析只做解码，不做任何清洗；换行等预处理如果需要，也应该放在这一层，而不是切分层。
- **为什么选这个方案**：让 `Clause` 的偏移量始终指向解析文本，审计可追溯；这条不变量后来在 P-22/P-24 的排查里被反复用到，证明了当初的设计是站得住的。
- **最终结果**：`test_document_parser.py` 17 个 + `test_parser_integration.py` 12 个（本地 pytest 通过）。⚠️ 只能解析 `.txt`——V2 生成的临时文件同样是 `.txt`，所以 V2 的生成/解析链路完全复用现有能力，没有引入新的解析器。
- **面试可能被问到什么**：怎么处理中文编码？为什么解析层不清洗文本？V2 是怎么"解析"出来的？
- **后续可以怎么优化**：实现 PDF / DOCX / OCR；桥接文件被 pipeline 收编。

### 3.4 clause

- **模块**：`clause/clause_splitter.py`、`clause/contract_clause_splitter.py`
- **目的**：把合同全文切成结构化的 `Clause` 列表。
- **为什么需要它**：审查以条款为单位；需要保留条款边界、层级关系与原文位置；**Phase 3 的 V2 重建也完全依赖这棵树的父子关系**（见 3.14）。
- **设计方案**：两阶段。① **结构切分（正则）**：先按"第X条"，再按款编号（`1.`、`（一）`、`（1）`）切分并建立 `parent_clause`；② **长度控制**：只有超过 `chunk_size` 的条款才用 `RecursiveCharacterTextSplitter` 二次切分。
- **具体实现**：`clause_id` 规则：`clause_000` 是第一条之前的前言（`clause_type="preamble"`）；`clause_001` 是按出现顺序编号的条（不使用条文里的数字，避免重复编号冲突）；`clause_001_2` 是第 2 款；`clause_001_p2` 是二次切分后的第 2 段。一个条内只采用最先出现的款编号样式。默认 `chunk_size=500`、`chunk_overlap=50`。**不变量**：`full_text[start_char:end_char] == original_text`。
- **遇到的问题**：① 只靠 `RecursiveCharacterTextSplitter` 会把几个很短的条合并进同一个 chunk，条款边界丢失；② 行内引用如"依照\n第三十九条的规定"被误认成条标题。
- **如何定位**：切分测试里出现条款被合并、引用被当成标题。
- **解决方案**：先结构切分再做长度控制；条标题正则加 `(?!的)` 排除引用。
- **为什么选这个方案**：结构信息比字数更重要，字数切分只作为兜底。
- **最终结果**：`test_clause_splitter.py` 15 个 + `test_clause_integration.py` 14 个。**Phase 3 复盘**：`hierarchy_level=0`（条）与 `hierarchy_level=1`（款，`parent_clause` 指回条）这个树形结构，在 Phase 1/2 阶段只被 Review 用来"逐条送审"，从未被要求过"按这棵树重建完整原文"；P-22 的根因正是 Phase 3 新写的 `_build_v2_text` 对这棵树做了一个在 Phase 1/2 语境下从未出现过、也从未被验证过的新假设（"条的 `original_text` 已经包含款的内容"），这提醒了一个通用教训：**给已有数据结构设计新的消费方式时，不能只看它过去被怎么用过，要重新核对它的真实不变量**。
- **面试可能被问到什么**：为什么不直接用 LangChain 的切分器？怎么保证偏移量正确？V2 重建是怎么用这棵树的？
- **后续可以怎么优化**：支持更多编号样式；`split_contract` 桥接文件被 pipeline 收编。

### 3.5 rag

- **模块**：`rag/embedding.py`、`database.py`、`loader.py`、`retrieval.py`
- **目的**：法律知识文本 → 切分 → 向量化 → Chroma → 根据 query 检索 → 返回 `Evidence`。
- **为什么需要它**：让 LLM 只依据检索到的真实法条判断，而不是凭记忆编造。
- **设计方案**：`rag` **完全独立**，不依赖 `contract` / `parser` / `clause`，只依赖 `schemas`（以及后来的 `config`）。四个文件职责严格分开：`embedding` 只构造 embedding；`database` 是唯一直接接触 Chroma 的文件；`loader` 管切分与写入；`retrieval` 管检索并转成 `Evidence`。
- **具体实现**：
  - BGE-M3 通过 `HuggingFaceEmbeddings` 本地加载，**只用稠密向量**，`normalize_embeddings=True`。
  - 法律文本**按"第X条"切分**，一条一个 `Evidence`；超过 500 字才二次切分。
  - Embedding 不是手动调用的步骤，由 Chroma 在 `add_texts` / `similarity_search` 内部调用。
  - `article` 为空时不写入 metadata（Chroma 不接受 `None`）。
  - `index` 不去重；`ChromaKnowledgeBase.count()` 依赖 Chroma 的内部 `_collection.count()`（没有公开接口，已在代码里注释）。
- **遇到的问题**：测试里的 `build_embedder` 参数校验用例，在真实环境下真的去下载模型。
- **如何定位**：本地 pytest 出现 `1 failed, 201 passed`，失败信息是 `RepositoryNotFoundError: 401 ... other/model`。
- **解决方案**：用 `unittest.mock.patch("rag.embedding.HuggingFaceEmbeddings")` 只检查传入参数。
- **为什么选这个方案**：真实的 `HuggingFaceEmbeddings` 在**构造时就加载模型**，不是懒加载，我之前的假设错了（见 PITFALLS P-01）。
- **最终结果**：✅ 真实环境（知识库 14 条）：三个 query 第一名全部命中，distance 分别为 0.4469（第二十条）、0.4434（第二十四条）、0.4782（第十七条）。**Phase 3 复盘**：RAG 在 Modification Agent 流程里**不重新触发**——`ModificationAgent` 直接复用 `review_result.legal_basis`（V1 审查阶段已经检索并保存的法律依据），不再调用一次 `LegalKnowledgeRetriever`，这是明确的设计决策（见 `modification/agent.py` 顶部注释），避免修改阶段和审查阶段各自检索出不一致的依据。
- **面试可能被问到什么**：为什么按条切分？为什么只用稠密向量？向量库怎么持久化？distance 怎么理解？为什么 Modification 阶段不重新检索？
- **后续可以怎么优化**：扩充知识库；评估稀疏 / 多向量混合检索；`index` 增加去重；引入检索相关性阈值。

### 3.6 llm

- **模块**：`llm/client.py`、`llm/prompts.py`
- **目的**：连接 LLM，并把条款与法律依据拼成 Prompt；**Phase 3 新增 `chat_with_tool`，支撑 Function Calling**。
- **为什么需要它**：把"怎么发请求"和"怎么拼 Prompt"与审查业务逻辑分开。
- **设计方案**：`OpenAICompatibleClient` 用官方 `openai` SDK 指定 `base_url`，可接入任何 OpenAI 兼容服务；`build_deepseek_client` 从环境变量读配置。`client` 只负责连接、不含业务；`prompts` 只负责拼字符串、不调用 LLM、不检索。
- **具体实现**：JSON 模式通过 `response_format={"type": "json_object"}`；`OpenAIError` 统一包装为 `LLMClientError`，空回复也视为错误。系统提示要求：只依据给定法律依据、不得编造、依据不足如实说明、只输出 JSON 及五个字段。`base_url` 固定为 `https://api.deepseek.com`；`DEEPSEEK_API_KEY` 必填；`DEEPSEEK_MODEL` 可选。**（Phase 3 新增）** `chat_with_tool(messages, tool_schema, temperature=0.0)`：调用时传 `tools=[tool_schema]`、`tool_choice="auto"`，解析真实返回的 `tool_calls[0].function.arguments`（JSON 字符串）为 dict 后返回；`tool_choice` 最初写的是强制指定函数名，真实联调 DeepSeek 后改为 `"auto"`（见 P-21）。
- **遇到的问题**（Phase 1/2）：① 首次真实运行请求被拒：`The supported API model names are deepseek-flash, deepseek-v4-pro, but you passed DEEPSEEK`；② 单元测试真的向 `example.com` 发了请求；③ 单元测试里"缺 API Key 应报错"的用例没有报错。
- **（Phase 3 新增问题）** ④ `chat_with_tool` 真实联调 DeepSeek 返回 HTTP 400 `Thinking mode does not support this tool_choice`——详见 P-21。
- **如何定位**：① 原因有两层：本地 `.env` 里 `DEEPSEEK_MODEL` 被写成了占位符 `DEEPSEEK`；同时代码里的默认值 `deepseek-chat` 已过期。② 自己造的假 `openai` 模块只存在于沙箱，本地装了真 SDK 后，改它的属性没有任何作用。③ `load_dotenv()` 把本地真实 `.env` 里的 key 又读了回来。④ 见 P-21：DeepSeek Thinking 模式不支持强制 `tool_choice`。
- **解决方案**：默认模型改为 `deepseek-flash` 并写明命名易变；测试统一用 `unittest.mock.patch` 替换被测模块里的名字；`chat_with_tool` 的 `tool_choice` 改为 `"auto"`。
- **为什么选这个方案**：`patch` 不依赖任何自造模块，本地是否装了真库都行为一致；`tool_choice="auto"` 改动最小，且"模型不调用工具"这个后果已经被 Service 层的重试/失败机制天然吸收（见 P-21）。
- **最终结果**：`test_llm_client.py` 12 个 + `test_llm_prompts.py` 7 个（全部 mock，不联网）；✅ 真实 DeepSeek 调用成功（审查链路）；`chat_with_tool` 沙箱替身 10/10 通过，真实联调结果待 bh 在真实环境确认（改动已合入代码，机制上已验证 `tool_choice="auto"` 被正确传给 SDK）。
- **面试可能被问到什么**：怎么保证输出是 JSON？为什么 `base_url` 固定？外部服务的版本变化怎么应对？为什么 `tool_choice` 用 `"auto"` 而不是强制指定？
- **后续可以怎么优化**：超时 / 重试；填充 `prompt_version`；Prompt 版本化；`chat_with_tool` 目前没有对"模型选择不调用工具"这条路径做专门的重试提示（只是计入普通失败次数）。

### 3.7 review（单条款审查）

- **模块**：`review/reviewer.py`、`review/schemas.py`
- **目的**：单条 Clause 的完整审查：query → RAG → Prompt → LLM → `ReviewResult`。
- **为什么需要它**：把已验证过的几个环节串成一条可独立运行、可独立测试的链路。
- **设计方案**：开始编码前发现一个架构冲突：需求里要在 `review/schemas.py` 定义一个新的 `ReviewResult`，但项目已有全局共用的 `schemas.ReviewResult`，两个同名类型会造成混乱。**决定：最终结果继续复用 `schemas.ReviewResult`，`review/schemas.py` 只放 `LLMReviewOutput`（要求 LLM 返回的原始 JSON 结构）。** 理由：`clause_id`、`source` 是代码拼上去的，不该让模型自己填。
- **具体实现**：`ClauseReviewer.review` 的流程见 README 第 11 节；检索失败、LLM 调用失败、输出不是合法 JSON、JSON 不合法，统一抛 `ReviewError`，不做静默兜底。
- **遇到的问题**：**真实审查"竞业限制三年且无补偿"的条款，`legal_basis` 只引用了第三条（公平原则），第二十三、二十四条没有被检索到**——但这两条明明在知识库里，且用短 query"竞业限制期限"时第二十四条是第一名。
- **如何定位**：对比检索结果发现，`generate_query` 会把"第X条 标题"**整行**删掉，只保留正文；而这条款正文是同义改写（"不得到有竞争关系的单位任职"），根本不含"竞业限制"这个词，标题里的关键词被丢了。
- **解决方案**：只去掉"第X条"编号本身，保留标题文字。
- **为什么选这个方案**：标题往往是最精准的法律术语，正文才是口语化改写。改动最小，不增加额外检索成本。
- **最终结果**：✅ 修复后同一条款：检索第一名是第二十四条（0.5259）、第二名第二十三条（0.6355），`legal_basis` 引用了两条，并额外指出了"竞业限制适用主体未明确"的问题。测试：`test_review_reviewer.py` 增加了回归用例。**Phase 3 复用**：`ModificationService._find_review_result` 从 V1 最新一次 `ReviewRecord` 里按 `clause_id` 或 `related_clause_ids` 查找该条款的审查结果，作为 Modification Agent 的输入之一（律师可以不提交任何审查结果就直接创建任务，此时传 `None`）。
- **面试可能被问到什么**：怎么让 LLM 只依据给定依据？为什么不让模型填 `clause_id`？query 怎么生成，遇到过什么问题？
- **后续可以怎么优化**：结合 `clause_type` 生成 query；对 `none` / `low` 结果考虑重复采样（成本要权衡）；保留 `Evidence` 以便审计。

### 3.8 rules

- **模块**：`rules/checker.py`、`merge.py`、`probation_salary.py`、`probation_duration.py`
- **目的**：主线路（RAG + LLM）之后，对稳定漏检或需要确定性保证的问题做补充检查，并把结果与 LLM 结果合并。
- **为什么需要它**：真实验证暴露了两件事：**LLM 单条款审查看不到其他条款**（`clause_004` 的 LLM 原话："现有信息未提供合同期限，无法……判断"）；**LLM 结果不保证可复现**。规则是确定性的，能补这两处。
- **设计方案**：这一模块**重设计过**：
  1. 第一版：建了 `ContractFacts` + `extract_contract_facts`（统一事实抽取层），准备做必备条款检查和条款间关系检查。写完 `schemas.py` 和 `extractor.py` 后被叫停。
  2. 重新定位：Rule Checker 是**测试驱动的漏检补丁层**，不是通用规则引擎，也不是第二条审查线路。**删除** `ContractFacts` 与 `extractor`，每条规则自己识别、提取、判断。
  3. `RuleChecker.check(clauses)` **不读 `llm_results`**，也不根据 LLM"是否不确定"决定是否运行。
  4. 分析 `ReviewResult` 粒度后（风险点，一个条款可有多条结果），把合并从"规则整条替换 LLM 结果"改为**纯拼接**。
- **具体实现**：两条规则见 README 第 10 节。规则**只在发现问题时返回结果**；跨条款问题用 `clause_id=None` + `related_clause_ids`。`RuleChecker.__init__` 里维护 `self.rules` 列表。`merge_review_results` = `llm_results + rule_results`。
- **遇到的问题**：① 统一事实层与"每条规则自己提取"的取舍；② 替换式合并会丢掉 LLM 已经发现、规则没检查的其他风险；③ 每条规则各写一份提取逻辑，`probation_duration` 内有一份合同期限 / 试用期正则，将来第二条规则需要期限信息时可能重复。
- **如何定位**：① 与真实使用方式对照：规则是逐条沉淀的补丁，不是先建模再套规则；② 检查 `ReviewReport.results` 的语义。
- **解决方案**：删除统一层、拼接合并；为②③保留触发线：等真的出现第二条需要同一段提取逻辑的规则，再抽成共享的小函数（仍不恢复 `ContractFacts`）。
- **为什么选这个方案**：先测试再抽象，避免提前设计。拼接是唯一不丢信息的合并方式。
- **最终结果**：`test_rules_*` 共 33 个（salary 9、duration 12、checker 5、merge 7）；✅ 真实 10 条款验证：规则只影响 `clause_001`、`clause_004`，`clause_004` 上 LLM 与规则两条结果并存，`12 = 10 + 2`。**Phase 3 未改动**：`run_v2_review` 直接复用同一个 `RuleChecker` 实例，V2 复审时规则同样独立于 LLM 结果运行。
- **面试可能被问到什么**：为什么要规则？为什么规则不依赖 LLM 结果？为什么不去重？为什么不做通用规则引擎？
- **后续可以怎么优化**：用更多真实合同迭代；风险级去重（数据证明有必要时）；逐规则容错；扩大数字与金额识别范围。

### 3.9 pipeline（LangGraph）

- **模块**：`review/pipeline.py`
- **目的**：把已验证的模块编排成一张图。
- **为什么需要它**：并行分支 + 汇合 + 共享状态用声明式拓扑表达，结构可读、可测，也为条件边、重试、checkpoint 留出空间。**如实说明**：当前只用了很小一部分 LangGraph 能力，一个 fork/join 用函数加线程池也能实现。
- **设计方案**：分三轮设计、逐轮确认。
  - **State**：6 个字段。进 State 的标准是"下一个节点是否把它当直接输入"。`Evidence`（`ClauseReviewer` 内部临时变量）、`parsed_text`（切分后无人再用）、`original_file`、基础设施实例都不进。`failed_clauses` 复用 `schemas.FailedClause`。
  - **Node**：5 个，`failed_clauses` 只在 `llm_review` 产生（`ReviewError` 天然是条款级；规则崩溃、Contract Loading 失败的粒度与 `FailedClause` 不匹配）。
  - **Edge**：7 条无条件边。并行和汇合用普通边即可，不需要条件边；每个字段只有一个写入者，不需要 reducer。
- **具体实现**：基础设施通过 `build_graph` 参数注入闭包；`run_review` 用全部初始化的 State 调用 `invoke`。**Phase 3 复用**：`run_v2_review` 和 `review_contract`（V1 路由）都直接调用同一个未改动的 `run_review`，`run_review` 本身完全不知道"V1"/"V2"这个概念，只认识一个普通的 `contract_id`——这是"V2 必须重新走一遍完整审查"这条设计决策在代码层面的直接体现（详见 3.14、ARCHITECTURE_DECISIONS）。
- **遇到的问题**：① 锁定的 State 没有能装"整节点失败"的字段，所以无法写条件边路由；② `report_assembly` 构造 `ReviewReport` 后，因为 State 明确不含 `report`，对象被丢弃。
- **如何定位**：设计 Edge 时发现条件边的路由函数没有可读的失败信号。
- **解决方案**：**接受"节点异常直接抛出、终止整图"作为当前阶段的架构决策**，不在这一轮扩大 State；`ReviewReport` 由调用方用最终 State 重建。**（Phase 3 补充）**：这个决策在 Modification/V2 场景下依然成立——`api/routes/modification.py::run_version_review` 用和 V1 完全一致的方式映射 pipeline 抛出的异常，没有为 V2 引入任何专门的失败路径。
- **为什么选这个方案**：先跑通主链路，用真实测试决定是否需要更复杂的失败处理，与规则"测试驱动再加"一致。
- **最终结果**：✅ 真实 E2E：5 个条款 → 5 条 LLM 结果 + 2 条规则结果 → 7 条最终结果，0 失败；✅ 12 个 graph 测试在真实 LangGraph 1.2.12 上通过。
- **面试可能被问到什么**：为什么用 LangGraph？State 存什么、不存什么？并行与汇合怎么实现？如何测试图？V2 复审为什么直接复用同一个 `run_review`？
- **后续可以怎么优化**：条件边与失败路由；节点重试；checkpoint；把 `ReviewReport` 或其等价物纳入输出；收编过渡桥接文件；未来如果 Modification 出现"需要多工具选择"的场景，可以考虑在 `modification/` 内部单独建一张更小的 LangGraph 图，而不是改动 `review/pipeline.py`（详见 ARCHITECTURE_DECISIONS）。

### 3.10 整理阶段（第一轮，Phase 1/2 末尾）

- **模块**：`config/settings.py`、`tests/conftest.py`、`pytest.ini`、`scripts/_samples.py`、`scripts/_common.py`
- **目的**：不改变业务行为的前提下，集中默认配置、给测试分层、去掉脚本里的沙箱遗留和重复代码。
- **为什么需要它**：默认值和路径散落在 8 处；测试混在一起分不清层次；脚本里有沙箱时期留下的假 embedding。
- **设计方案**：`settings.py` 只放跨模块共享的默认值常量，**不放密钥**，各模块仍可通过构造参数覆盖；测试分 `unit` / `module` / `graph` 三个 marker，真实 E2E 保留在 scripts，不进 pytest。
- **具体实现**：
  - `chunk_size/overlap` **没有合并成一组**，而是分成 `CLAUSE_CHUNK_*` 与 `KNOWLEDGE_CHUNK_*`：两个模块互相独立，数值相同只是巧合，共用一个常量会让调其中一个悄悄影响另一个。
  - `conftest.py` 按文件名自动打标记，新增测试文件不登记会在收集阶段报错；不需要改任何现有测试文件。
  - 新增 `tests/test_review_pipeline.py`：真实 `langgraph`，只有 LLM 与检索用假对象。
  - scripts：示例合同集中到 `_samples.py`（四份内容并不相同，没有合并）；"打开知识库并检查非空""构造 DeepSeek 客户端"两块真正重复的代码收进 `_common.py`；删除 `_FakeEmbeddings` 与 `--fake-embeddings`；`--top-k` 默认值统一引用 `settings.RETRIEVAL_TOP_K`。
- **遇到的问题**：① 集中配置改变了模块依赖图；② 上一轮说各脚本"复制了同一份示例合同"，核对后**判断有误**；③ 真实环境出现 3 条 `PytestUnknownMarkWarning`。
- **如何定位**：① 用 AST 前后对比依赖；② 逐字比对四份文本；③ 见下。
- **解决方案**：① 接受这个取舍并让 `config` 保持零依赖、有测试守着；② 更正结论，只做集中存放；③ 根因是本地 `pytest.ini` 没有同步更新。
- **为什么选这个方案**：先核对"发出去的是什么"再动手；没有复现就重复注册只会掩盖原因。
- **最终结果**：11 项默认值前后逐项等价；✅ 真实环境 258 passed；graph `12 passed, 246 deselected`；真实 E2E 复跑无问题；本次整理没有改变任何业务行为。
- **面试可能被问到什么**：为什么集中配置？有什么副作用？测试为什么分层？怎么证明整理没有改变行为？
- **后续可以怎么优化**：收编桥接文件；合并测试里重复的假对象；去掉 scripts 里重复的 `sys.path` 引导。

## 四、Phase 3：API / 前端 / Modification Agent / V1-V2 / Diff（本次新增）

### 3.11 API（FastAPI）

1. **当时要解决什么**：Phase 1/2 已经把审查链路（Contract→Parser→Clause→RAG→LLM→RuleChecker→LangGraph）跑通并验证，但只能通过脚本调用，没有对外的 HTTP 接口，也没有前端。
2. **最初怎么设计**：`api/app.py` 只做三件事——创建 FastAPI 实例、挂载 `lifespan`、留出路由挂载位；`api/dependencies.py` 用 `lifespan` + `app.state` + `Depends` 三件套组织依赖注入，明确"不手写 Singleton 类"。
3. **为什么这么设计**：业务链路（`run_review`/DeepSeek chat/LangGraph invoke）都是同步阻塞调用，路由统一用普通 `def`（FastAPI 自动丢进线程池），不用 `async def`（会占住事件循环）；重对象（`ContractManager`/`embedder`/`knowledge_base`/`retriever`/`llm_client`/`reviewer`/`rule_checker`）在 `lifespan` 里构造一次，请求期间通过 `Depends` 复用，`fail fast`——任何一步构造失败直接抛异常，不吞、不降级。
4. **实际开发中遇到什么问题**：详见 3.13（Modification Agent 引入后暴露的依赖注入 bug，P-20）。
5. **哪些方案被推翻**：无（API 层的基本骨架从设计到实现没有被推翻过，真正被推翻的是 3.13 里 `ModificationService` 的依赖组装方式）。
6. **为什么推翻**：见 3.13。
7. **最终方案**：`AppState`（dataclass）持有 7 个重对象字段（不含 `ModificationService`，理由见 3.13），`get_xxx(request)` 系列函数从 `request.app.state.app_state` 里取值。
8. **验证结果**：✅ 真实 `uvicorn api.app:app --reload` 启动成功；`tests/test_api_dependencies.py`（4 个）、`tests/test_api_contracts.py`（34 个）、`tests/test_api_full_flow.py`（2 个）在真实 FastAPI TestClient 上通过（本次整理用 `grep -c "^def test_"` 实测，2026-09-29）。
9. **当前遗留问题**：CORS 只放行了 `http://localhost:5173`（开发环境），没有生产环境的跨域配置；没有鉴权/用户体系；`api/routes/modification.py` 里 `ModificationServiceError` 和它的子类 `ModificationConflictError` 统一映射成 409，没有更细粒度的错误码。

### 3.12 前端（React + Vite）

1. **当时要解决什么**：API 已经可用，但仍然只能用 curl/脚本测试，需要一个律师能实际操作的界面。
2. **最初怎么设计**：`App.jsx` 作为唯一持有顶层状态、唯一调用后端 API 的组件；子组件（`ContractLibrary`/`ContractWorkspace`/`ClauseViewer`/`ReviewWorkspace`/`ModificationTaskPanel`/`ModificationTaskForm`/`VersionPanel`/`UploadPanel`/`ContractOverview`）只通过 props 拿数据、通过回调触发动作；`api/client.js` 是唯一的 `fetch` 封装层，组件不直接 `fetch`。
3. **为什么这么设计**：避免状态和网络请求散落在各个组件里，方便统一处理 loading/error；`handleResponse`/`wrapNetworkError` 把 FastAPI 的 `{detail: "..."}` 和 `{detail: [...]}`（422 校验错误数组）两种错误格式统一转换成可直接展示的字符串。
4. **实际开发中遇到什么问题**：（本次整理仅读代码，未发现前端历史 bug 的书面记录——如实说明**证据不足**，不编造。）
5. **哪些方案被推翻**：无已知证据。
6. **为什么推翻**：不适用。
7. **最终方案**：见 `frontend/src/App.jsx` 顶部注释——页面刷新后合同库/审查结果会重新从后端拉取（已持久化），但"当前打开哪份合同"不落盘（本阶段不引入路由/localStorage），刷新后需要重新点开合同，这是明确记录的已知行为，不是 bug。
8. **验证结果**：✅ 真实浏览器联调（用户在本地 Windows 环境操作，多次真实验收测试正是从前端界面发起的，详见 3.14/3.15）。
9. **当前遗留问题**：没有路由、没有状态持久化；没有对 Modification 任务列表做分页；没有对长文本条款做虚拟滚动等性能优化（合同规模较小，暂未暴露问题）。

### 3.13 依赖注入 bug：`ModificationService` 单例绑死旧 `ContractManager`（P-20）

1. **当时要解决什么**：给 `ModificationService` 接入依赖注入，让路由能拿到它。
2. **最初怎么设计**：把 `ModificationService` 当成和 `ContractManager`/`ClauseReviewer` 一样的"启动时构造一次、放进 `AppState` 的重对象"。
3. **为什么这么设计**：`ModificationService` 看起来和其他重对象一样"只是持有几个引用"，直觉上没有区别对待的理由。
4. **实际开发中遇到什么问题**：`tests/test_api_contracts.py` 里两条新用例失败——`test_create_modification_task_returns_201_with_pending_status` 期望 201 实际拿到 404，`test_list_modification_tasks_returns_created_tasks_in_order` 期望两条任务实际拿到 `[]`（详见 PITFALLS P-20）。
5. **哪些方案被推翻**：`ModificationService` 作为启动时单例存进 `AppState` 的做法被推翻。
6. **为什么推翻**：测试用 `app.dependency_overrides[get_contract_manager]` 把合同目录换成 `tmp_path`，但这个 override 只对"每次请求重新解析 `Depends(get_contract_manager)`"生效；`ModificationService` 在启动时就把当时（生产目录）的 `ContractManager` 实例封死在自己内部，永远感知不到 override。
7. **最终方案**：`AppState` 只存 `modification_agent`（不持有 `ContractManager`，可以安全单例）；新增 `get_modification_service(contract_manager=Depends(get_contract_manager), modification_agent=Depends(get_modification_agent))`，每次请求现场组装。判断标准：**一个组合型依赖内部有没有引用另一个可能被测试 override 的依赖？有，就必须现场组装；没有，才能作为启动时单例。**
8. **验证结果**：✅ `scripts/verify_di_fix.py`（11/11，不依赖真实 FastAPI 的最小复现脚本）+ bh 本地重跑 `pytest tests/test_api_contracts.py -v` 和全量 `pytest` 通过。
9. **当前遗留问题**：无已知遗留——这是一个已完全解决的历史 bug，记录在此是为了留存"单例 vs 现场组装"这条判断标准，供未来新增组合型依赖时参考。

### 3.14 Modification Agent + Function Calling + HITL

1. **当时要解决什么**：律师看完审查报告后，需要对某个条款提出修改意见，让系统生成修改后的文本，并且这个过程必须有律师确认、不能自动生效。
2. **最初怎么设计**：`ModificationAgent`（唯一职责：拼 Prompt → 真实 Function Calling → 解析工具调用）+ `modification/tool.py`（工具执行、第一道越界校验）+ `modification/validator.py`（纯函数，范围/完整性/结构三类校验，不调用 LLM）+ `modification/service.py`（编排层：冲突检测、状态机推进、V2 生成、Diff）。状态机 6 态：`pending→reviewing→confirmed→completed`；`reject`（附带新意见）→`rejected`（重试<3 时可再次 `start`）；重试满 3 次仍未确认→`needs_human`。
3. **为什么这么设计**：
   - Agent 和 ClauseReviewer 定位不同（判断 vs 生成），故意不合并、不复用同一个类。
   - "第一版只有一个工具"仍然坚持用真正的 Function Calling（`tools=[schema]`，模型自己决定要不要调用），而不是把 JSON 硬解析伪装成 Agent——这是对"什么是真 Agent"这个问题的一个明确立场。
   - 每一轮重试永远基于 `task.original_text`（V1 原文）+ `task.lawyer_instructions`（全部历史意见）重新生成，Prompt 构造函数本身不接受"上一轮候选文本"这个参数——从代码结构上排除了"在错误结果上继续叠加"的可能。
   - Validator 独立于 Agent 之外、不调用 LLM：越界修改、截断、占位符这些问题用固定规则就能可靠检测，不需要再调用一次 LLM 自证。
4. **实际开发中遇到什么问题**：真实联调 DeepSeek 时 `chat_with_tool` 返回 400 `Thinking mode does not support this tool_choice`（P-21，详见 PITFALLS）。
5. **哪些方案被推翻**：`chat_with_tool` 最初的强制 `tool_choice`（指定具体函数名）被推翻。
6. **为什么推翻**：DeepSeek 从 V3.2/V4 起，thinking 模式下只支持 `tool_choice` 为省略/`"auto"`/`"none"`，强制指定会被服务端拒绝（社区已有独立报告）。
7. **最终方案**：改为 `tool_choice="auto"`；"模型选择不调用工具"这条路径已经被现有的 `if not tool_calls: raise LLMClientError(...)` 天然覆盖，会被记成一次失败的 `ModificationAttempt`，计入 3 轮重试上限，不需要新增分支。
8. **验证结果**：✅ `scripts/verify_agent_function_calling.py`（沙箱假 `openai` 客户端上验证全部分支：正常/未调用工具/JSON 非法/越界等）；`tool_choice="auto"` 的回归断言已加入该脚本；真实 DeepSeek 联调的最终确认见 3.15（P-22/23/24 的真实验收过程中，Modification Agent 本身的调用链路已经在真实环境跑通，没有再报告过 Function Calling 层面的新问题）。
9. **当前遗留问题**：**`tests/` 目录下没有 `test_modification*.py`——Modification Agent/Tool/Validator/Service 的业务逻辑目前只有 `scripts/verify_*.py` 这类手工运行的验证脚本，没有被收编进自动化 pytest 套件**（本次整理核实：`tests/` 目录列表里确实不存在这类文件，`test_api_contracts.py` 里有一部分修改任务相关的 API 层测试，但不覆盖 Service/Agent/Validator 内部逻辑）。这是一条真实的技术债务，详见 PROJECT_KNOWLEDGE 第八节与 CAPABILITY_GAPS。

### 3.15 V1/V2 + Clause Diff + Risk Diff（含三次真实 Bug 修复）

1. **当时要解决什么**：律师确认若干条修改任务之后，需要生成一份"修改后的合同"（V2），并且要能对比 V1/V2 的条款差异和风险差异。
2. **最初怎么设计**：`ContractVersion` 作为"外部版本号 → 内部 contract_id"的映射记录；`generate_v2` 把 V1 全文按 `hierarchy_level==0` 的 Clause 过滤、拼接成新文本，写入临时文件后用【完全未改动的】`create_contract`/`parse_contract`/`split_contract` 走一遍正常流程，得到一个新的、内部使用的 `contract_id`。`clause_diff` 按 `clause_id` 对比 V1/V2 的 `hierarchy_level==0` 条款原文；`risk_diff` 按 `(source, clause_id/rule_id)` 做 key，把 V1/V2 两次独立复审的结果分类为 `resolved/unchanged/changed/new/unmatched` 五类。
3. **为什么这么设计**：不改造 `ContractManager` 的"一个 contract_id 一个版本"模型，而是让 V2 复用现有存储能力、以一个新 contract_id 存在——这样 V1/V2 复审都能直接复用未改动的 `run_review`，V2 在机制上就是"完整重新走一遍"，不是"打补丁"。
4. **实际开发中遇到什么问题（三次真实 Bug，均由用户在真实浏览器环境验收发现）**：
   - **Fix B / P-22**：`_build_v2_text` 只拼接 `hierarchy_level==0` 的文本，错误假设"款的内容已经包含在条里"，导致有款项编号的条在 V2 里丢失全部款级正文（无论有没有被修改）。
   - **Fix A / P-23**：`save_review` 硬编码 `contract_version="v1"`，导致 V2 第一次保存的 review 恰好也编号成 `v1_001`，与 V1 自己的第一条记录撞车，造成 Risk Diff 界面 `V1=v1_001`/`V2=v1_001` 的误导性巧合。
   - **Fix C / P-24**：`generate_v2` 用默认 `newline=None` 写入临时文件，在 Windows（`os.linesep=="\r\n"`）上把未修改条款原有的 `\r\n` 转写成 `\r\r\n`，多出一个换行，被误判为"已修改"。
5. **哪些方案被推翻**：① "款的内容已经包含在条的 `original_text` 里"这个隐含假设被推翻；② "`contract_version` 可以在 `save_review` 内部安全推断/硬编码"这个假设被推翻；③ "`write_text` 的默认换行行为在所有平台上是安全的"这个假设被推翻。
6. **为什么推翻**：三者都有真实浏览器环境的观察数据支撑，且都经过了"先假设、真实执行验证、假设被推翻、找到真根因"的完整排查过程（详见 PITFALLS P-22/23/24 的【最初怀疑】字段）。
7. **最终方案**：见 PITFALLS P-22/23/24 的【解决方案】字段（`_group_clauses_by_article`+`_reconstruct_article_text` 按字符偏移量局部替换重建；`save_review` 增加显式 `contract_version` 参数；`generate_v2` 写入时用 `newline=""`）。
8. **验证结果**：✅ `scripts/verify_v2_article_reconstruction.py`（68/68）、`scripts/verify_modification.py`（73/73）、`scripts/verify_p24_newline_write.py`（6/6）均真实执行通过；三次修复均经过 **bh 本地重跑 `pytest` 全量通过** + **真实（Fix C 是真实 Windows）浏览器验收确认**，是本项目里证据链最完整的三次 bug 修复。
9. **当前遗留问题**：
   - `_build_v2_text` 里条与条之间仍用固定的 `"\n\n"` 分隔，不是从 V1 原文取"条与条之间的缝隙"，这是已知的、范围有限的简化（不会丢内容，只可能让条间空行数量和 V1 不完全一致）。
   - `clause_diff` 目前是纯字符串比较，没有做任何格式规范化——三次修复已经把"数据本身"的问题都解决了，但如果未来出现新的、来源不同的文本差异（例如律师直接编辑候选文本带来的空白差异），`clause_diff` 仍然可能把格式噪音误判为实质修改，这一点在 P-24 修复说明里已经明确写出"交给未来 clause_diff 的格式规范化去兜底"。
   - `risk_diff` 用 `(source, clause_id/rule_id)` 做匹配，如果 V2 重新切分后同一条款被拆分成不同数量的子条款（例如律师修改后条款结构变化很大），`clause_id` 可能对不齐，会被分类为 `unmatched`，这是当前匹配策略的已知局限（详见 ARCHITECTURE_DECISIONS 里"为什么不用 related_clause_ids 匹配"）。

## 五、测试数量演进

| 阶段 | 数量 | 说明 |
|---|---|---|
| 通过 RAG 阶段 | 160 | 沙箱回归计数（含替身） |
| + llm / review | 202 | 真实 pytest 当时是 `1 failed, 201 passed` |
| 修正 embedding 测试 / 新增 query 回归用例 | 203 → 204 | 沙箱回归计数 |
| + rules | 237 | +33 |
| + settings | 246 | +9 |
| + graph 流程测试 | 258 | 真实 pytest：`258 passed`；其中 graph 12 |
| **+ API（Phase 3）** | — | 新增 `test_api_dependencies.py`（4）、`test_api_contracts.py`（34）、`test_api_full_flow.py`（2） |
| **本次整理实测（2026-09-29）** | **298** | 用 `grep -c "^def test_" tests/*.py` 对 `tests/` 目录下全部 24 个测试文件求和得出的真实数字，**未跑 pytest**（本沙箱同样没有真实依赖），仅统计测试函数定义数，可能与真实 `pytest` collected 数量存在参数化等原因的细微差异，供参考；Modification Agent/Tool/Validator/Service 的业务逻辑不在这 298 个之内（见 3.14 遗留问题） |

按 `tests/conftest.py` 的登记，Phase 1/2 阶段 unit 184 / module 62 / graph 12。总数与 graph 数已在真实环境确认；unit / module 的拆分是按登记推算的，未逐层单独核对。Phase 3 新增的 API 测试层未见到对应的 `pytest.ini` marker 记录（本次整理未新增或修改任何测试/配置文件，如实记录现状）。

## 六、关键架构决策清单（Phase 1/2，完整保留）

| 决策 | 原因 | 放弃的方案 |
|---|---|---|
| `schemas` 是唯一基础层，功能模块互相独立 | 独立开发与测试，避免循环依赖 | 模块之间直接互相引用 |
| 最终结果只有一种类型 `ReviewResult`，用 `source` 区分来源 | 合并、报告不需要处理多种格式 | `FinalResult` / `RuleResult` 等 |
| `ReviewResult` 是风险点粒度 | 一个条款可有多个风险 | 一条款一结果 |
| 合同存储用文件系统，不用数据库 | 当前只需要按合同隔离的中间产物 | SQLite（早期设想） |
| 解析与切分不改动原文，保证偏移量不变量 | 审计与定位依赖 | 解析时清洗文本 |
| 法律文本按条切分 | 依据完整、带条号 | 固定长度切分 |
| RAG 独立于 contract / parser / clause | 可单独使用与测试 | 复用 `ClauseSplitter` |
| LLM 输出用 `LLMReviewOutput` 校验后再补 `clause_id` / `source` | 这些字段不该由模型决定 | 让模型直接产出最终结果 |
| 规则是测试驱动的补丁层，各自封装 | 先测试再抽象 | `ContractFacts` 统一事实层、通用规则引擎 |
| `RuleChecker` 不依赖 `llm_results` | 规则必须能独立运行、独立测试 | 让规则只在 LLM"不确定"时运行 |
| 合并 = 拼接，不覆盖、不去重 | 唯一不丢信息 | 规则替换 LLM 结果 |
| State 只放数据，且每字段单一写入者 | 无需 reducer，可读可测 | 把 Evidence、report、基础设施放进 State |
| 图里只用无条件边；节点异常直接抛出 | 先跑通主链路，用真实测试决定失败处理 | 统一 error state + 条件分支 |
| 配置只集中默认值，不放密钥；chunk 参数按语义分开 | 密钥留在环境变量；语义不同不耦合 | 一个 `chunk_size` 到处用 |
| 真实 E2E 放在 scripts，不放进 pytest；验证脚本不允许静默降级 | 避免 CI 误消耗 token；真实验证的意义就是暴露真实问题 | 用假实现兜底 |

**Phase 3 新增的架构决策**（详细的【决策/问题/方案/理由/是否仍成立/何时重估】见 `docs/ARCHITECTURE_DECISIONS.md`，此处只列条目）：

| 决策 | 原因 | 放弃的方案 |
|---|---|---|
| Modification Agent 只有一个工具（`modify_clause`），不做多工具选择 | 当前业务需求只有"修改单个条款"这一种操作 | 一开始就设计通用的多工具 Agent 框架 |
| ModificationService 依赖现场组装，不做启动时单例 | 组合型依赖必须跟随请求级 override（P-20） | 和其他重对象一样放进 `AppState` |
| `tool_choice="auto"` 而不是强制指定函数名 | DeepSeek thinking 模式的真实限制（P-21） | 强制 `tool_choice`（沙箱里能跑，真实环境会被拒绝） |
| V2 是一个新的、内部的 `contract_id`，完整重新解析/切分/复审 | 复用现有存储与 pipeline，V1 永不被覆盖 | 改造 `ContractManager` 支持"一个 contract_id 多版本" |
| Reject 后基于 V1 原文 + 累积意见重新生成，不基于上一轮候选 | 防止在错误结果上继续叠加 | 基于上一轮候选做增量修改 |
| 最多 3 次重试，失败后 `needs_human` | 有限重试 + 明确的失败终态，避免无限循环 | 无限重试 / 无失败终态 |
| Risk Diff 用 `(source, clause_id/rule_id)` 匹配，不用 `related_clause_ids` | clause_id/rule_id 在 V1/V2 间更稳定、更不会产生歧义 | 用 `related_clause_ids` 这个可变长度集合匹配 |

## 七、遗留问题

见 [README 的已知限制与后续优化方向](../README.md#18-已知限制)（Phase 1/2 遗留问题，README 未改动，本次整理不重复列出）；Phase 3 的遗留问题见上方 3.11~3.15 各小节末尾的"当前遗留问题"，以及 `docs/PROJECT_KNOWLEDGE.md` 第八节"项目状态管理"的完整汇总。

## 2026-10-09：Modification/Review 架构升级（Batch / Risk Analyzer / V2 独立生成服务）

**解决的问题**：
1. Review Graph 的 `report_assembly` 节点之前只是"构造一次 ReviewReport 验证能不能构造"，真正返回值在图外（`run_review`）重新拼一次，两处构造逻辑有分叉风险——现在 `ReviewGraphState` 增加 `report` 字段，`report_assembly` 写回真正要返回的对象，`run_review` 直接取用。
2. `ModificationTask` 状态机的 `COMPLETED` 同时隐含"律师确认过"+"V2 生成成功过"两层含义，无法支持"V2 生成失败后重试"——拆成 Task 自己的终态（`CONFIRMED`/`ABANDONED`，永久保留"是否被确认"这一个事实）和 Batch 的 V2 生成结果（`V2_GENERATED`/`V2_FAILED`，可重试），互不影响。
3. 候选修改通过 Validator 后，缺少"改完之后风险是否真的被化解"这一步独立判断——新增 Modified Clause Risk Analyzer（复用 `ClauseReviewer.review`，不新建 RAG/LLM 链路）+ `risk_resolution` 业务比较纯函数。
4. V2 生成之前以"扫描全合同全部任务"为判定依据，无法支持"分批次改、分批次生成"——新增 `ModificationBatch`，V2 生成收窄到 `V2GenerationService`，以 `batch_id` 为单位判定就绪、记录生成结果。
5. 新增最小化自然语言问答能力（QA：收集数据 → 一次 Prompt → 一次 LLM 调用，不是 Agent/工具调用系统）。

**新模块在架构里的位置**：
```
API (routes/contracts.py, routes/modification.py)
  -> Application (review_service / diff_service / qa_service / v2_generation_service)
    -> Workflow (workflows/review_workflow.py，仅 Review 是 LangGraph)
    -> Business Capability (modification/service.py ModificationService；
                              modification/risk_resolution.py 纯函数；
                              agents/risk_analyzer.py 复用 ClauseReviewer；
                              document/reconstructor.py 纯函数，未改动)
      -> Infrastructure/Storage (contract/manager.py ContractManager)
```
- `modification/service.py::ModificationService`：批次创建、任务创建（服务端查原文+冻结快照）、Agent 调用编排、Validator、Risk Analyzer 调用、人工确认/拒绝/放弃。生命周期止于 `CONFIRMED`/`ABANDONED`，不再做 V2 生成。
- `modification/risk_resolution.py::determine_risk_resolution`：纯函数，输入两个 `RiskLevel`，输出 `RiskResolution`，不依赖任何基础设施，单独可测。
- `agents/risk_analyzer.py::analyze_modified_clause`：输入 Clause + 候选文本，输出 `ReviewResult`；内部只是 `clause.model_copy` + `ClauseReviewer.review`，不重复实现 RAG/LLM 调用。
- `application/v2_generation_service.py::V2GenerationService`：输入 `batch_id`，做就绪判断 → 批次状态流转（`V2_GENERATING`→`V2_GENERATED`/`V2_FAILED`）→ 调用未改动的 `document.reconstructor` 纯函数重建全文 → `ContractManager.create_contract`/`parse_and_split_contract`/`save_version`。
- `application/qa_service.py::QAApplicationService` + `prompts/qa.py`：收集 Contract/Clause/ReviewResult/ModificationTask/ContractVersion 数据 → 拼 Prompt → 一次 `llm_client.chat()`。

**依赖边界**：`ModificationService` 新增对 `ClauseReviewer`（Risk Analyzer 复用）的依赖，但依然不 import `workflows.review_workflow` / `diff` 包 / `V2GenerationService`——V2 生成和 Review Graph 继续是独立方向的依赖，没有反向引用回 `ModificationService`。`V2GenerationService` 依赖 `modification.service.compute_batch_readiness`（读方向）但不依赖 `ModificationService` 实例本身。

**真实踩到的问题**：见 `docs/PITFALLS.md` P-25（鸭子类型避免适配层、Risk Analyzer 失败必须建模成返回值而不是异常控制流、批次就绪判断必须 batch-scoped 不能退化成 contract-scoped）。

**测试**：`scripts/verify_modification.py` 重写为覆盖新状态机/Risk Analyzer/risk_resolution/批次就绪/V2 生成成功-失败-重试/ABANDONED 保留原文，61/61 真实执行通过；`scripts/verify_di_fix.py`、`scripts/verify_p24_newline_write.py` 同步更新签名/取值位置后分别 11/11、6/6 通过；`scripts/verify_agent_function_calling.py`（10/10）、`scripts/verify_v2_article_reconstruction.py`（68/68）未受影响，原样通过，确认本次改动没有破坏 Function Calling 解析和 V2 条款级重建这两块既有逻辑。

**后续优化方向**（不在本次范围内，见最终报告"遗留问题"）：`tests/test_api_contracts.py` 里基于 FastAPI TestClient 的修改任务相关用例仍使用旧的请求体形状（`original_text` 字段、无 `batch_id`），本沙箱没有 `fastapi`/`pytest` 无法执行验证，需要在有真实依赖的环境里更新后重跑。
