# 开发日志

> **【本文件已归档，2026-09-29】** 本文件内容已完整合并至 [`docs/DEVELOPMENT_LOG.md`](DEVELOPMENT_LOG.md)（新文件用的是本次整理指定的确切文件名），并在那里补充了 Modification Agent / Function Calling / HITL / V1-V2 / Clause Diff / Risk Diff / 最近的 Fix A/B/C 等本文件未覆盖的阶段。**本文件本身不删除、不改写，完整保留在下方**，作为历史存档；请以 `docs/DEVELOPMENT_LOG.md` 为准继续阅读和更新。
>
> ---
>
> 以下是本文件原始内容（未做任何修改）：

> 整理日期：2026-09-28。
> 记录范围：从 schemas 到 LangGraph 编排，再到整理阶段与真实环境复验。
> 数据来源：开发过程中的设计讨论，以及在本地真实环境运行后贴出的输出。**没有出现过的结果不会写在这里。**
> 图例：✅ 已在真实环境验证　🧪 仅自动化测试　⚠️ 已知限制　📝 未实现

## 一、开发方式

- **严格分步**：每个阶段先给设计，确认后再编码；完成后附测试结果与数据流，再进入下一阶段。开发顺序：schemas → contract → parser → clause → RAG → LLM Review → RuleChecker → LangGraph（State → Node → Edge → 搭建）→ 整理。
- **两类验证要分清**：代码开发发生在**没有网络的沙箱**里，BGE-M3、Chroma、DeepSeek、真实 LangGraph 都装不上，只能用替身验证代码逻辑；**真实效果全部由你在本地真实环境运行后确认**。"沙箱通过"不等于"真实通过"，这是本项目最重要的经验之一（见 [PITFALLS P-01](PITFALLS.md)）。
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
| 14 | 文档 | README + docs/ | — |

## 三、模块开发日志

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
- **最终结果**：`tests/test_schemas.py` 39 个测试。⚠️ `schemas/contract.py`、`schemas/_time.py` 的文档字符串仍写 SQLite，`schemas/review_report.py` 提到"重试"和"formatter"，这些**代码里都不存在**；整理阶段不允许改代码，只记录。
- **面试可能被问到什么**：为什么用 Pydantic？为什么 `summary` 用计算字段？`ReviewResult` 为什么是风险点粒度？
- **后续可以怎么优化**：让 `ReviewResult` 能携带 `Evidence`；修正漂移的文档字符串。

### 3.2 contract

- **模块**：`contract/manager.py`（`ContractManager`）
- **目的**：管理合同文件的本地存储：原文件、解析文本、条款、元数据。
- **为什么需要它**：审查是多步骤流程，中间产物需要落盘并按合同隔离；原文件是审计依据，不能被覆盖。
- **设计方案**：不使用数据库，纯文件系统。布局：`<root>/<contract_id>/{original_file/<文件名>, parsed_text.txt, clauses.json, metadata.json}`。状态 `uploaded → parsed → split`。
- **具体实现**：
  - `contract_id = uuid4().hex`，访问目录前用正则校验，防止 `../` 穿出根目录（因为它以后会来自 API）。
  - 原文件**只写一次，拒绝覆盖**；sha256 在保存后的副本上分块计算；`metadata.json` **最后写入**并用临时文件 + `os.replace` 原子替换，所以它存在就代表合同创建完整；创建中途失败会 `rmtree` 清理整个目录。
  - `save_clauses` 校验每个条款的 `contract_id` 与目标合同一致。
- **遇到的问题**：`Path.read_text()` 不支持 `newline` 参数，读取 `parsed_text.txt` 时换行被转换，破坏了条款偏移量。
- **如何定位**：写"解析 → 切分"的集成测试时，`full_text[start:end] == original_text` 的不变量断言失败。
- **解决方案**：读写 `parsed_text.txt` 用 `open(..., encoding="utf-8", newline="")`，关闭换行转换。
- **为什么选这个方案**：不变量是前端定位和审计追踪的依赖，宁可在存储层严格保持原文。
- **最终结果**：`test_contract.py` 23 个测试（另有 parser / clause 的集成测试经过它）；本地 pytest 通过。⚠️ **早期需求提到过用 SQLite 保存元数据，最终实现是纯文件系统 JSON，这个差异开发期间没有正式确认过**，整理时如实记录。⚠️ 没有代码把状态置为 `reviewed` / `failed`。
- **面试可能被问到什么**：为什么不用数据库？怎么防路径穿越？为什么 `metadata.json` 最后写？
- **后续可以怎么优化**：需要检索、并发、审计时再引入数据库；流程结束后更新 `reviewed` / `failed`。

### 3.3 parser

- **模块**：`parser/document_parser.py`、`parser/contract_parser.py`
- **目的**：把上传文件转换成纯文本。
- **为什么需要它**：切分和审查只处理文本；文件格式的差异应该隔离在这一层。
- **设计方案**：`DocumentParser` 按后缀分发给 `BaseParser` 子类，可扩展注册。**不改动原文内容**（不 strip、不换行规范化）。
- **具体实现**：`TxtParser` 支持 BOM 检测（UTF-16/32、utf-8-sig），回退 gb18030，拒绝二进制和空内容。`PdfParser`、`DocxParser`、`OcrParser` 是占位，调用抛 `NotImplementedError`。`parse_contract` 是连接 `ContractManager` 与 `DocumentParser` 的**过渡桥接**。
- **遇到的问题**：编码不确定；一旦解析阶段改了换行，条款偏移量就失效。
- **如何定位**：集成测试覆盖了各种编码和状态流转。
- **解决方案**：解析只做解码，不做任何清洗；换行等预处理如果需要，也应该放在这一层，而不是切分层。
- **为什么选这个方案**：让 `Clause` 的偏移量始终指向解析文本，审计可追溯。
- **最终结果**：`test_document_parser.py` 17 个 + `test_parser_integration.py` 12 个（本地 pytest 通过）。⚠️ 只能解析 `.txt`。
- **面试可能被问到什么**：怎么处理中文编码？为什么解析层不清洗文本？
- **后续可以怎么优化**：实现 PDF / DOCX / OCR；桥接文件被 pipeline 收编。

### 3.4 clause

- **模块**：`clause/clause_splitter.py`、`clause/contract_clause_splitter.py`
- **目的**：把合同全文切成结构化的 `Clause` 列表。
- **为什么需要它**：审查以条款为单位；需要保留条款边界、层级关系与原文位置。
- **设计方案**：两阶段。① **结构切分（正则）**：先按"第X条"，再按款编号（`1.`、`（一）`、`（1）`）切分并建立 `parent_clause`；② **长度控制**：只有超过 `chunk_size` 的条款才用 `RecursiveCharacterTextSplitter` 二次切分。
- **具体实现**：`clause_id` 规则：`clause_000` 是第一条之前的前言（`clause_type="preamble"`）；`clause_001` 是按出现顺序编号的条（不使用条文里的数字，避免重复编号冲突）；`clause_001_2` 是第 2 款；`clause_001_p2` 是二次切分后的第 2 段。一个条内只采用最先出现的款编号样式。默认 `chunk_size=500`、`chunk_overlap=50`。**不变量**：`full_text[start_char:end_char] == original_text`。
- **遇到的问题**：① 只靠 `RecursiveCharacterTextSplitter` 会把几个很短的条合并进同一个 chunk，条款边界丢失；② 行内引用如"依照\n第三十九条的规定"被误认成条标题。
- **如何定位**：切分测试里出现条款被合并、引用被当成标题。
- **解决方案**：先结构切分再做长度控制；条标题正则加 `(?!的)` 排除引用。
- **为什么选这个方案**：结构信息比字数更重要，字数切分只作为兜底。
- **最终结果**：`test_clause_splitter.py` 15 个 + `test_clause_integration.py` 14 个。
- **面试可能被问到什么**：为什么不直接用 LangChain 的切分器？怎么保证偏移量正确？
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
- **最终结果**：✅ 真实环境（知识库 14 条）：三个 query 第一名全部命中，distance 分别为 0.4469（第二十条）、0.4434（第二十四条）、0.4782（第十七条）。
- **面试可能被问到什么**：为什么按条切分？为什么只用稠密向量？向量库怎么持久化？distance 怎么理解？
- **后续可以怎么优化**：扩充知识库；评估稀疏 / 多向量混合检索；`index` 增加去重；引入检索相关性阈值（当前分数没有绝对意义，不同集合不可比）。

### 3.6 llm

- **模块**：`llm/client.py`、`llm/prompts.py`
- **目的**：连接 LLM，并把条款与法律依据拼成 Prompt。
- **为什么需要它**：把"怎么发请求"和"怎么拼 Prompt"与审查业务逻辑分开。
- **设计方案**：`OpenAICompatibleClient` 用官方 `openai` SDK 指定 `base_url`，可接入任何 OpenAI 兼容服务；`build_deepseek_client` 从环境变量读配置。`client` 只负责连接、不含业务；`prompts` 只负责拼字符串、不调用 LLM、不检索。
- **具体实现**：JSON 模式通过 `response_format={"type": "json_object"}`；`OpenAIError` 统一包装为 `LLMClientError`，空回复也视为错误。系统提示要求：只依据给定法律依据、不得编造、依据不足如实说明、只输出 JSON 及五个字段。`base_url` 固定为 `https://api.deepseek.com`；`DEEPSEEK_API_KEY` 必填；`DEEPSEEK_MODEL` 可选。
- **遇到的问题**：① 首次真实运行请求被拒：`The supported API model names are deepseek-flash, deepseek-v4-pro, but you passed DEEPSEEK`；② 单元测试真的向 `example.com` 发了请求；③ 单元测试里"缺 API Key 应报错"的用例没有报错。
- **如何定位**：① 原因有两层：本地 `.env` 里 `DEEPSEEK_MODEL` 被写成了占位符 `DEEPSEEK`；同时代码里的默认值 `deepseek-chat` 已过期——按 DeepSeek 官方文档，旧模型名已于 2026-07-24 下线。② 自己造的假 `openai` 模块只存在于沙箱，本地装了真 SDK 后，改它的属性没有任何作用。③ `load_dotenv()` 把本地真实 `.env` 里的 key 又读了回来。
- **解决方案**：默认模型改为 `deepseek-flash` 并写明命名易变；测试统一用 `unittest.mock.patch` 替换被测模块里的名字（`llm.client.OpenAI`、`llm.client.load_dotenv`）。
- **为什么选这个方案**：`patch` 不依赖任何自造模块，本地是否装了真库都行为一致。
- **最终结果**：`test_llm_client.py` 12 个 + `test_llm_prompts.py` 7 个（全部 mock，不联网）；✅ 真实 DeepSeek 调用成功。
- **面试可能被问到什么**：怎么保证输出是 JSON？为什么 `base_url` 固定？外部服务的版本变化怎么应对？
- **后续可以怎么优化**：超时 / 重试；填充 `prompt_version`；Prompt 版本化。

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
- **最终结果**：✅ 修复后同一条款：检索第一名是第二十四条（0.5259）、第二名第二十三条（0.6355），`legal_basis` 引用了两条，并额外指出了"竞业限制适用主体未明确"的问题。测试：`test_review_reviewer.py` 增加了回归用例。
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
- **最终结果**：`test_rules_*` 共 33 个（salary 9、duration 12、checker 5、merge 7）；✅ 真实 10 条款验证：规则只影响 `clause_001`、`clause_004`，`clause_004` 上 LLM 与规则两条结果并存，`12 = 10 + 2`。
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
- **具体实现**：基础设施通过 `build_graph` 参数注入闭包；`run_review` 用全部初始化的 State 调用 `invoke`。
- **遇到的问题**：① 锁定的 State 没有能装"整节点失败"的字段，所以无法写条件边路由；② `report_assembly` 构造 `ReviewReport` 后，因为 State 明确不含 `report`，对象被丢弃。
- **如何定位**：设计 Edge 时发现条件边的路由函数没有可读的失败信号。
- **解决方案**：**接受"节点异常直接抛出、终止整图"作为当前阶段的架构决策**，不在这一轮扩大 State；`ReviewReport` 由调用方用最终 State 重建。
- **为什么选这个方案**：先跑通主链路，用真实测试决定是否需要更复杂的失败处理，与规则"测试驱动再加"一致。
- **最终结果**：✅ 真实 E2E：5 个条款 → 5 条 LLM 结果 + 2 条规则结果 → 7 条最终结果，0 失败；✅ 12 个 graph 测试在真实 LangGraph 1.2.12 上通过。
- **面试可能被问到什么**：为什么用 LangGraph？State 存什么、不存什么？并行与汇合怎么实现？如何测试图？
- **后续可以怎么优化**：条件边与失败路由；节点重试；checkpoint；把 `ReviewReport` 或其等价物纳入输出；收编过渡桥接文件。

### 3.10 整理阶段

- **模块**：`config/settings.py`、`tests/conftest.py`、`pytest.ini`、`scripts/_samples.py`、`scripts/_common.py`
- **目的**：不改变业务行为的前提下，集中默认配置、给测试分层、去掉脚本里的沙箱遗留和重复代码。
- **为什么需要它**：默认值和路径散落在 8 处；测试混在一起分不清层次；脚本里有沙箱时期留下的假 embedding。
- **设计方案**：`settings.py` 只放跨模块共享的默认值常量，**不放密钥**，各模块仍可通过构造参数覆盖；测试分 `unit` / `module` / `graph` 三个 marker，真实 E2E 保留在 scripts，不进 pytest。
- **具体实现**：
  - `chunk_size/overlap` **没有合并成一组**，而是分成 `CLAUSE_CHUNK_*` 与 `KNOWLEDGE_CHUNK_*`：两个模块互相独立，数值相同只是巧合，共用一个常量会让调其中一个悄悄影响另一个。
  - `conftest.py` 按文件名自动打标记，新增测试文件不登记会在收集阶段报错；不需要改任何现有测试文件。
  - 新增 `tests/test_review_pipeline.py`：真实 `langgraph`，只有 LLM 与检索用假对象。
  - scripts：示例合同集中到 `_samples.py`（四份内容并不相同，没有合并）；"打开知识库并检查非空""构造 DeepSeek 客户端"两块真正重复的代码收进 `_common.py`；删除 `_FakeEmbeddings` 与 `--fake-embeddings`；`--top-k` 默认值统一引用 `settings.RETRIEVAL_TOP_K`（rag 与 real_retrieval 两个脚本由 3 变为 5）。
- **遇到的问题**：① 集中配置改变了模块依赖图；② 我上一轮说各脚本"复制了同一份示例合同"，核对后**判断有误**；③ 真实环境出现 3 条 `PytestUnknownMarkWarning`。
- **如何定位**：① 用 AST 前后对比依赖；② 逐字比对四份文本；③ 见下。
- **解决方案**：① 接受这个取舍并让 `config` 保持零依赖、有测试守着；② 更正结论，只做集中存放；③ 根因是**本地 `pytest.ini` 没有同步更新**，交付的文件本来就已注册 marker，覆盖后消失，**没有修改任何代码**。
- **为什么选这个方案**：先核对"我发出去的是什么"再动手；没有复现就重复注册只会掩盖原因。
- **最终结果**：11 项默认值前后逐项等价；✅ 真实环境 258 passed；graph `12 passed, 246 deselected`；真实 E2E 复跑无问题；本次整理没有改变任何业务行为。
- **面试可能被问到什么**：为什么集中配置？有什么副作用？测试为什么分层？怎么证明整理没有改变行为？
- **后续可以怎么优化**：收编桥接文件；合并测试里重复的假对象；去掉 scripts 里重复的 `sys.path` 引导。

## 四、真实验证记录

以下结果来自你在本地真实环境运行后贴出的输出。

**环境**：Windows + PowerShell + venv，Python 3.13.12，pytest 9.1.1，LangGraph 1.2.12；LLM 为 DeepSeek `deepseek-flash`；embedding 为 `BAAI/bge-m3`（默认 CPU）。

| 编号 | 验证 | 结果 |
|---|---|---|
| R-01 | 真实检索（BGE-M3 + 持久化 Chroma，知识库 14 条） | "试用期工资不得低于多少" → 第二十条 0.4469、第十九条 0.6457、第二十一条 0.8028；"竞业限制期限" → 第二十四条 0.4434、第二十三条 0.8561、第十九条 0.9645；"劳动合同必备条款有哪些" → 第十七条 0.4782、第三条 0.6339、第二十九条 0.7507 |
| R-02a | 单条款审查首次真实运行 | 全部失败：模型名 `DEEPSEEK` 被拒（400）。原因：`.env` 占位符 + 默认模型名过期 |
| R-02b | 修正模型名后的三个案例 | 试用期工资 50% → `high`（第二十条、第十九条）；正常工时 → `none`，依据不足如实说明；**竞业限制三年无补偿 → `high`，但 `legal_basis` 只有第三条，第二十三、二十四条没被检索到（query 丢了标题关键词）** |
| R-02c | 修复 `generate_query` 后 | 竞业限制条款：第二十四条 0.5259 居首、第二十三条 0.6355 第二；`legal_basis` 两条都引用；额外指出适用主体未明确 |
| R-03a | 10 条款合同：LLM + 规则 + 合并 | 10 条 LLM 结果，0 失败；规则 2 条；合并 12 = 10 + 2；规则只影响 `clause_001`、`clause_004`；`clause_004` 上 LLM 与规则并存 |
| R-03b | 同一份合同第二次运行 | 规则结果不变；`clause_001`、`clause_009` 的 LLM 风险等级从 `low` 变为 `none`，两条 `high` 的结论保持稳定 → **LLM 非确定性的实证** |
| R-04 | 完整 LangGraph E2E（5 条款） | **5 = 5（LLM），+2 条规则 = 7，0 失败**；`summary`：high 4 / none 3；`clause_003` 的 LLM 原话"条款未载明劳动合同期限，无法判断"，规则用 `clause_001 + clause_003` 给出确定性结论；`clause_005`（竞业限制）由 LLM 独立发现期限与补偿两个问题，规则没有对应规则，所以没有重复输出 |
| R-05 | 整理后真实 pytest | `258 passed, 3 warnings`；`pytest -m graph`：`12 passed, 246 deselected` |
| R-06 | 定位 3 条 warning | 均为 `PytestUnknownMarkWarning`（`unit` / `module` / `graph`），来源 `tests/conftest.py`；根因：本地 `pytest.ini` 未同步；覆盖后输出正常 |
| R-07 | 整理后真实 E2E | 复跑无问题 |

说明：`R-04` 的 `summary`（high 4 / none 3）统计的是 **7 条结果**，不是 5 个条款。

## 五、测试数量演进

| 阶段 | 数量 | 说明 |
|---|---|---|
| 通过 RAG 阶段 | 160 | 沙箱回归计数（含替身） |
| + llm / review | 202 | 真实 pytest 当时是 `1 failed, 201 passed`：失败的就是会去下载模型的 embedding 用例（P-01） |
| 修正 embedding 测试 / 新增 query 回归用例 | 203 → 204 | 沙箱回归计数 |
| + rules | 237 | +33 |
| + settings | 246 | +9 |
| + graph 流程测试 | **258** | 真实 pytest：`258 passed`；其中 graph 12 |

按 `tests/conftest.py` 的登记，unit 184 / module 62 / graph 12。总数与 graph 数已在真实环境确认；unit / module 的拆分是按登记推算的，未逐层单独核对。

## 六、关键架构决策清单

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

## 七、遗留问题

见 [README 的已知限制与后续优化方向](../README.md#18-已知限制)。
