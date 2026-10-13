# 问题 / 踩坑知识库

> 整理日期：2026-09-28；本次知识库整理（2026-09-29）在原有基础上补充格式说明，未删除任何历史条目。
> 只收录**真实发生过**的问题；每条都来自开发过程中的真实输出或真实设计争议。**预防性决策**会明确标注"未实际发生"。
>
> **格式说明（2026-09-29 新增）**：P-01 ~ P-21 沿用最初的 8 字段格式（问题 / 现象 / 原因 / 定位过程 / 解决方案 / 为什么采用这个方案 / 如何避免再次发生 / 面试价值），**保持原样，不强行改写**——没有足够证据把它们逐条扩展成新格式的其余字段（例如"最初怀疑"是否存在、Agent/LangGraph 经验是否适用），强行扩写会有编造的风险。P-22、P-23、P-24 三条与 Modification Agent / V1V2 / Fix A/B/C 直接相关的条目，按本次整理要求改写为统一的 **12 字段格式**：
> 【问题】【现象】【最初怀疑】【定位过程】【真正根因】【解决方案】【为什么这样解决】【验证结果】【工程经验】【Agent / LangGraph 经验】【面试怎么讲】【是否已解决】。
> 今后新增的条目一律使用 12 字段格式。

## 索引

| 编号 | 问题 | 类别 | 价值 |
|---|---|---|---|
| [P-01](#p-01-沙箱替身--真实依赖) | 沙箱替身 ≠ 真实依赖 | 测试 / 环境 | ★★★ |
| [P-02](#p-02-外部服务的名称过期--env-占位符) | DeepSeek 模型名过期与 `.env` 占位符 | 外部服务 | ★★ |
| [P-03](#p-03-query-丢失标题关键词导致召回失败) | query 丢失标题关键词导致召回失败 | RAG | ★★★ |
| [P-04](#p-04-单条款审查看不到其他条款) | 单条款审查看不到其他条款 | 架构 | ★★★ |
| [P-05](#p-05-temperature0-仍不可复现) | `temperature=0` 仍不可复现 | LLM | ★★★ |
| [P-06](#p-06-rule-checker-设计走偏) | Rule Checker 设计走偏 | 架构 | ★★★ |
| [P-07](#p-07-reviewresult-的粒度) | `ReviewResult` 的粒度 | 数据模型 | ★★ |
| [P-08](#p-08-pathread_text-不支持-newline-参数) | `Path.read_text` 不支持 `newline` | 存储 | ★ |
| [P-09](#p-09-配置集中化改变了模块依赖图) | 配置集中化改变了模块依赖图 | 工程 | ★★★ |
| [P-10](#p-10-两个-chunk-配置数值相同但语义独立) | 两个 chunk 配置数值相同但语义独立 | 工程 | ★★ |
| [P-11](#p-11-pytest-unknownmarkwarning) | `PytestUnknownMarkWarning` | 测试基础设施 | ★★ |
| [P-12](#p-12-测试假绿) | 测试假绿 | 测试 | ★★★ |
| [P-13](#p-13-知识库覆盖不足不是缺陷) | 知识库覆盖不足不是缺陷 | RAG | ★ |
| [P-14](#p-14-设计后果state-没有-report节点异常终止整图) | State 没有 `report`，节点异常终止整图 | 设计后果 | ★★ |
| [P-15](#p-15-chroma-的-metadata-不接受-none) | Chroma metadata 不接受 `None` | RAG | ★ |
| [P-16](#p-16-流程先核对前提再下结论) | 先核对前提再下结论 | 流程 | ★★★ |
| [P-17](#p-17-文档字符串漂移) | 文档字符串漂移 | 文档 | ★ |
| [P-18](#p-18-powershell-没有-tail) | PowerShell 没有 `tail` | 环境 | ★ |
| [P-19](#p-19-pytestini-中的中文预防性未实际发生) | `pytest.ini` 中的中文（预防性） | 测试基础设施 | ★ |
| [P-20](#p-20-依赖注入单例绑死了会被测试-override-的下游依赖) | 依赖注入单例绑死了会被测试 override 的下游依赖 | 架构 / 依赖注入 | ★★★ |
| [P-21](#p-21-deepseek-thinking-模式与强制-tool_choice-冲突) | DeepSeek Thinking 模式与强制 `tool_choice` 冲突 | 外部服务 / Function Calling | ★★★ |
| [P-22](#p-22-v2-重建全文时款级子-clause-内容被静默丢弃) | V2 重建全文时款级子 Clause 内容被静默丢弃 | 数据模型 / 编排逻辑 | ★★★ |
| [P-23](#p-23-save_review-硬编码-contract_version-导致-v1v2-review_id-撞车) | `save_review` 硬编码 `contract_version` 导致 V1/V2 review_id 撞车 | 数据模型 / 存储 | ★★ |
| [P-24](#p-24-generate_v2-写临时文件时-oslinesep-导致换行符损坏) | `generate_v2` 写临时文件时 `os.linesep` 导致换行符损坏 | 跨平台 / I/O | ★★★ |
| [P-26](#p-26-risk_diff-按-rule_id-匹配导致同规则多条款结果互相覆盖) | `risk_diff` 按 `rule_id` 匹配导致同规则多条款结果互相覆盖 | 数据模型 / Diff 逻辑 | ★★★ |
| [P-27](#p-27-probation_salary-百分比正则遗漏零导致-0-试用期工资漏检) | `probation_salary` 百分比正则遗漏"零"导致 0% 试用期工资漏检 | 规则引擎 / 正则 | ★★ |
| [P-28](#p-28-probation_duration-跨条款配对取第一次出现的值导致误报) | `probation_duration` 跨条款配对取"第一次出现的值"导致误报 | 规则引擎 / 数据配对 | ★★★ |
| [P-29](#p-29-knowledgeloaderindex-不做去重导致重复加载知识库时数据翻倍) | `KnowledgeLoader.index()` 不做去重，导致重复加载知识库时数据翻倍 | RAG / 数据幂等性 | ★★ |

---

## P-01 沙箱替身 ≠ 真实依赖

- **问题**：开发在没有网络的沙箱里进行，第三方依赖只能用自己写的替身。把"替身上通过"当成了"真实依赖上通过"。
- **现象**（四个真实案例）：
  1. `tests/test_llm_client.py` 在本地真的向 `https://example.com` 发了请求，报 `LLMClientError`，错误内容是一整页 "Example Domain" 的 HTML。
  2. `build_embedder` 的参数校验用例在本地真的去 HuggingFace 下载不存在的 `other/model`，报 `RepositoryNotFoundError: 401`，整体是 `1 failed, 201 passed`。
  3. "缺 API Key 应该报错"的用例出现 `DID NOT RAISE`。
  4. 沙箱里手写的 LangGraph 替身能跑通，但不能证明真实 LangGraph 的行为。
- **原因**：
  1. 自造的假 `openai` 模块只存在于沙箱路径，测试里改的是它的类属性；本地装了真 SDK，改属性根本不生效。
  2. 真实的 `HuggingFaceEmbeddings` 在**构造时**就加载模型，不是懒加载；我的沙箱替身是懒的，所以假设错了。
  3. `build_deepseek_client()` 内部会调用 `load_dotenv()`，把本地真实 `.env` 里的 key 又读了回来。
  4. 替身由我按自己的理解写，不可能包含我不知道的真实行为。
- **定位过程**：看本地报错文本；调用栈 `rag/embedding.py → HuggingFaceEmbeddings(...) → self._client = model_cls(...)` 直接指出构造函数里就在加载模型；对照"这些用例本来只想测参数传递"。
- **解决方案**：用 `unittest.mock.patch` 替换**被测模块里引用的名字**（`llm.client.OpenAI`、`llm.client.load_dotenv`、`rag.embedding.HuggingFaceEmbeddings`）；LangGraph 流程测试改为使用真实安装的 `langgraph`，替身只留在沙箱里做逻辑自检，不进项目。
- **为什么采用这个方案**：`patch` 不依赖任何自造模块，本地有没有真库行为都一致，也不会真的发出请求。
- **如何避免再次发生**：新增外部依赖前先问三个问题：构造函数会不会联网？会不会加载大文件？会不会读环境或配置文件？"沙箱通过"只算逻辑通过；涉及真实服务的结论必须在真实环境验证。这些经验已写进 `tests/README.md`。
- **面试价值**：高。有四个真实案例可以讲"Mock 与真实依赖的边界"，并且 LangGraph 那一项是先承认"没验证"、再用真实环境补上的。

## P-02 外部服务的名称过期 / `.env` 占位符

- **问题**：LLM 首次真实调用全部失败。
- **现象**：HTTP 400，`The supported API model names are deepseek-flash, deepseek-v4-pro, but you passed DEEPSEEK`；脚本打印出 `model=DEEPSEEK`。
- **原因**：两层。① 本地 `.env` 里 `DEEPSEEK_MODEL` 被写成了占位符 `DEEPSEEK`；② 代码里的默认值 `deepseek-chat` 已过期——按 DeepSeek 官方文档，旧模型名已于 2026-07-24 下线（V4 系列之后命名还在继续变化）。当初写默认值时没有核实当前有效的名称。
- **定位过程**：错误响应带着服务器的 `request_id`，说明请求确实发到了 DeepSeek，**不是"假 LLM"**；脚本里的 `model=DEEPSEEK` 暴露占位符；再检索官方文档确认当前有效名称。
- **解决方案**：默认值改为 `deepseek-flash`；在 `config/settings.py` 里写明命名易变、建议在 `.env` 显式配置；`.env.example` 与 README 提醒不要留占位符。
- **为什么采用这个方案**：模型名是外部服务会变的信息，应该集中在一处、有显式覆盖方式，而不是散落在代码里。
- **如何避免再次发生**：外部服务的名称、版本不凭记忆写，查官方文档；默认值只在一处定义；使用前用一次真实调用确认。
- **面试价值**：中高。说明"外部依赖是会变的"，以及怎么从错误响应判断请求是否真的到达了服务。

## P-03 query 丢失标题关键词导致召回失败

- **问题**：真实审查"竞业限制三年且无补偿"的条款时，检索不到最相关的法条。
- **现象**：`legal_basis` 只引用了第三条（公平原则）；第二十三、二十四条没有进入 top 5，尽管它们在知识库里，且用短 query"竞业限制期限"时第二十四条是第一名。
- **原因**：`generate_query` 最初把"第X条 标题"**整行删掉**，只保留正文。这条款的标题是"竞业限制"，正文是同义改写（"不得到有竞争关系的单位任职"），根本不含这个词。标题里最精准的法律术语被丢了。
- **定位过程**：对比"单独 query 的检索结果"与"审查时实际用的 query 的检索结果"，发现差别只在 query；逐条比对不同条款：试用期条款没出问题只是碰巧正文里也有"试用期"。
- **解决方案**：`generate_query` 只去掉"第X条"编号本身（以及 `1.`、`（一）` 这类款编号），保留标题文字。
- **为什么采用这个方案**：改动最小，不增加检索次数，也不需要额外的 query 改写。
- **如何避免再次发生**：`test_review_reviewer.py` 里加了回归用例（标题关键词不在正文里的情况）；以后改 query 逻辑要用"标题与正文用词不同"的条款验证。
- **面试价值**：高。一个"单元测试全绿、真实检索才暴露"的真实 bug，能讲清 RAG 里 query 质量的重要性。

## P-04 单条款审查看不到其他条款

- **问题**：需要跨条款信息才能下结论的判断，LLM 单条款审查做不了。
- **现象**：`clause_003`（试用期三个月）的 LLM 审查原话："试用期三个月是否合法取决于劳动合同期限……条款未载明劳动合同期限，无法判断"。合同期限其实写在 `clause_001` 里。
- **原因**：`ClauseReviewer.review(clause)` 一次只把当前一个条款交给 LLM。这是结构性的，不是模型偶尔看漏。
- **定位过程**：两次真实验证里，LLM 都在试用期条款里明确说自己不知道合同期限；对照 `clause_007`（竞业限制），所需信息全在同一条款内，LLM 就能独立、完整地判断出两个问题。
- **解决方案**：加规则分支。`probation_duration` 同时读取合同期限条款与试用期条款，用 `related_clause_ids=[clause_001, clause_003]` 给出确定性结论。
- **为什么采用这个方案**：规则本来就是为这类"主线路结构上做不到"的判断准备的，比让 LLM 每次都读整份合同便宜且可复现。
- **如何避免再次发生**：新增审查项时先问"判断所需的信息是否全部在一个条款里"；不是，就考虑规则或全文级检查。
- **面试价值**：高。这是"为什么需要规则分支"最有说服力的实证。

## P-05 `temperature=0` 仍不可复现

- **问题**：同一份合同、同一模型、`temperature=0`，两次真实运行的结果不完全一致。
- **现象**：10 条款合同两次运行，`clause_001`、`clause_009` 的风险等级都从 `low` 变成 `none`；证据充分的高风险条款（试用期工资、竞业限制）两次都稳定为 `high`。
- **原因**：`temperature=0` 不保证服务端输出严格一致。这不是本项目代码的问题，是走 API 的 LLM 服务的已知特性；不稳定集中在"证据不足、模型自己也在边界上"的条款。
- **定位过程**：两次真实输出逐条对比，确认代码、输入、Prompt 都没变。
- **解决方案**：**接受并如实记录**，不在工程上强行消除。规则是系统里唯一可复现的部分；候选缓解方案（自洽性采样、只对 `none` / `low` 重复采样）成本与延迟都会上升，只在真实数据证明这种翻转造成误导性结论时再做。
- **为什么采用这个方案**：只在两条边界条款上观察到，且不影响"有没有抓到真正的高风险"，提前给整条链路加投票 / 重试不划算。
- **如何避免再次发生**：不要假设"同一份合同重跑一次报告完全一样"；对比结果时先分清"确定性部分（规则）"与"LLM 部分"。
- **面试价值**：高。能讲清 LLM 的非确定性、它对系统设计的影响，以及为什么用规则补确定性。

## P-06 Rule Checker 设计走偏

- **问题**：第一版规则设计过度设计，并把合并策略选错了。
- **现象**：写了 `ContractFacts` 统一事实模型与 `extract_contract_facts`（写完 `rules/schemas.py`、`rules/extractor.py` 后被叫停）；合并策略是"规则结果整条替换 LLM 结果"。
- **原因**：把 `RuleChecker` 往"通用规则引擎"方向设计，忽略了它的真实定位——**逐条沉淀的、测试驱动的漏检补丁**；同时没有先检查 `ReviewResult` 的粒度就选了替换式合并。
- **定位过程**：对照真实使用方式（哪类问题被漏检，就补哪条规则）；分析 `ReviewResult`、`LLMReviewOutput`、`ReviewReport.results` 的实际语义。
- **解决方案**：删除 `ContractFacts` 与 extractor；每条规则自己识别、提取、判断；`RuleChecker.check(clauses)` 不接收 `llm_results`；合并改为纯拼接。
- **为什么采用这个方案**：先测试再抽象；拼接是唯一不丢信息的合并方式。代价是每条规则各带一份提取逻辑，已约定触发线：出现第二条需要同一段提取逻辑的规则时，再抽成共享的小函数，仍不恢复 `ContractFacts`。
- **如何避免再次发生**：新模块开工前先用一句话写清"定位"；对已有数据结构有疑义，先读代码分析语义，再设计。
- **面试价值**：高。能讲"我什么时候识别出过度设计，以及怎么收回来"。

## P-07 `ReviewResult` 的粒度

- **问题**：不清楚一个 `ReviewResult` 代表"一个条款"还是"一个风险"。
- **现象**：讨论"规则结果是否替换 LLM 结果"时，如果一个条款有 A、B 两个风险而规则只补充了 A，替换会丢掉 B。
- **原因**：schema 一开始只是"能装结果"，没有明确语义。
- **定位过程**：读 `schemas/review_result.py`、`review/schemas.py`、`review/reviewer.py`：`ReviewResult` 只有单个 `risk_level` / `reason`，但 `ReviewReport.results` 是**没有唯一性约束的扁平列表**。
- **解决方案**：明确 `ReviewResult` 是**风险点**粒度；一个条款可以对应多条结果；LLM 结果与规则结果都保留。
- **为什么采用这个方案**：与 schema 既有设计一致，不需要新增"判断是不是同一个问题"的逻辑。
- **如何避免再次发生**：数据结构的语义要写进文档字符串；"合并 / 去重"类需求先确认粒度。
- **面试价值**：中高。

## P-08 `Path.read_text` 不支持 `newline` 参数

- **问题**：读取 `parsed_text.txt` 后，换行被转换，条款偏移量失效。
- **现象**：集成测试里 `full_text[start_char:end_char] == original_text` 的不变量断言失败。
- **原因**：`Path.read_text()` 没有 `newline` 参数，无法关闭通用换行转换。
- **定位过程**：写"解析 → 切分 → 存储 → 读回"的集成测试时暴露。
- **解决方案**：`parsed_text.txt` 的读写改用 `open(path, encoding="utf-8", newline="")`。
- **为什么采用这个方案**：偏移量的不变量是前端定位与审计追踪的依赖，存储层必须严格保持原文。
- **如何避免再次发生**：对"必须逐字保持"的数据，写集成测试验证往返一致。
- **面试价值**：低到中。是个具体的细节坑。

## P-09 配置集中化改变了模块依赖图

- **问题**：集中配置虽然没改变业务逻辑，却改变了模块依赖图。
- **现象**：原来 `contract`、`rag`、`llm`、`clause`、`review` 只依赖 `schemas`，现在它们还依赖 `config`。
- **原因**：常量从"各模块自己拥有"变成"共同引用一处"，引用本身就是依赖边。
- **定位过程**：整理前后用 AST 扫描生产代码的 import，对比依赖关系。
- **解决方案**：接受这个取舍，并让 `config` 保持零依赖（只放常量、只用标准库、不放密钥），`tests/test_config_settings.py` 用测试守住这两点。
- **为什么采用这个方案**：8 处散落的默认值和脆弱路径改成一处，收益大于多一条依赖边；`config` 零依赖就不会产生循环依赖。
- **如何避免再次发生**：任何"集中 / 抽取"类重构，先画依赖图前后对比。另有一个小坑：`def __init__(self, chunk_size=settings.X)` 的默认值在**函数定义时**求值，改 `settings.py` 需要重启进程才会生效。`config` 是个很通用的包名，若环境里有第三方同名包，需要确认导入的是项目内的（`python -c "import config; print(config.__file__)"`）。
- **面试价值**：高。能讲"集中配置的好处与副作用"。

## P-10 两个 chunk 配置数值相同但语义独立

- **问题**：需求写的是一组 `chunk_size` / `chunk_overlap`，代码里实际有两个互相独立的模块在用。
- **现象**：合同条款切分（`clause`）和法律知识切分（`rag/loader`）默认值都是 500 / 50。
- **原因**：两处数值相同只是巧合，不是"同一个参数"。
- **定位过程**：整理配置时逐处核对每个默认值的用途与所属模块。
- **解决方案**：分成两组：`CLAUSE_CHUNK_SIZE/OVERLAP` 与 `KNOWLEDGE_CHUNK_SIZE/OVERLAP`。
- **为什么采用这个方案**：`clause` 与 `rag` 是互相独立的模块，共用一个常量会让调整其中一个时悄悄影响另一个。
- **如何避免再次发生**：合并配置前先问"这两处将来会不会各自独立调整"；数值相同不等于语义相同。
- **面试价值**：中。体现对"重复"与"耦合"的区分。

## P-11 `PytestUnknownMarkWarning`

- **问题**：真实环境跑 pytest 出现 3 条 `PytestUnknownMarkWarning`。
- **现象**：`258 passed, 3 warnings`，警告是 `Unknown pytest.mark.unit / module / graph`，来源 `tests/conftest.py`；`pytest -m graph` 是 `12 passed, 246 deselected`（说明标记机制本身是生效的）。
- **原因**：本地的 `pytest.ini` **没有同步更新**，pytest 读到的是没有 marker 注册的旧文件。交付的 `pytest.ini` 本来就已注册，**不是业务代码问题，也不是配置写错**。
- **定位过程**：① 警告来源指向 `tests/conftest.py` 动态添加 marker 的那一行；② 读交付的 `pytest.ini`，发现已经注册，与交付压缩包逐字节一致，项目里也没有其他配置文件竞争；③ 沙箱里没有 pytest，无法复现，所以没有改任何文件，改为让你在本地做只读诊断；④ 发现本地 `pytest.ini` 没更新；覆盖后输出正常。
- **解决方案**：用交付版覆盖本地 `pytest.ini`，零代码修改。
- **为什么采用这个方案**：配置本来就对，没复现就重复注册只会掩盖真实原因。
- **如何避免再次发生**：修改配置文件后，用 `pytest --markers` 核对注册是否生效；交付时把"有配置文件变更"明确列出来。核心概念：marker 的**使用**只是创建标签（任意名字都能创建，故意宽松），**注册**才是声明"这些名字是我有意使用的"，警告的作用是防拼写错误，不应该通过关闭警告来解决。
- **面试价值**：中。排查思路——先验证前提再动手。

## P-12 测试假绿

- **问题**：测试全绿，但不知道它们是否真能抓到错误。
- **现象**：首版流程测试全部通过，但断言写弱或写错时，测试会永远是绿的。
- **原因**：断言"没报错"，或者断言与被测逻辑基于同一个错误假设。
- **定位过程**：做**变异检查**：故意破坏生产逻辑，看对应测试是否变红。
- **解决方案**：三个变异：① merge 改成"规则覆盖 LLM"；② 吞掉规则异常；③ 让 LLM 永不失败。三个变异下对应测试全部变红，还原后恢复全绿。
- **为什么采用这个方案**：验证的是"测试有没有区分力"，而不是"代码对不对"。
- **如何避免再次发生**：为关键行为写"具体结果"的断言（例如 `final_results == llm_results + rule_results`、`llm.calls == 3`），不写"不报错"；重要测试用变异检查验证灵敏度。⚠️ 局限：变异是手工做的，只覆盖了几个点，不是自动化的变异测试框架，且是在沙箱替身上做的。
- **面试价值**：高。直接回答"怎么证明测试不是假绿"。

## P-13 知识库覆盖不足不是缺陷

- **问题**：对知识库覆盖之外的条款，系统给不出明确结论。
- **现象**：正常工时条款——知识库里没有工时相关条文，LLM 返回 `none`，理由是"依据不足"，`legal_basis` 为空。
- **原因**：知识库只有《劳动合同法》14 条节选。
- **定位过程**：对照检索结果与 LLM 的理由。
- **解决方案**：无需修复代码；这正是 Prompt 要求的行为（依据不足要如实说明，不要编造）。补内容是"扩充知识库"的工作。
- **为什么采用这个方案**：宁可说"不知道"，也不要让模型编造法条。
- **如何避免再次发生**：读结果时区分 `risk=False` 的两种含义："确认合规"与"依据不足所以没发现冲突"；后者不是合规结论。
- **面试价值**：低到中。

## P-14 设计后果：State 没有 `report`，节点异常终止整图

- **问题**：两个已确认的设计决定带来了后果。
- **现象**：① `report_assembly` 构造 `ReviewReport` 后，State 没有 `report` 字段，对象被丢弃；② 除 LLM 单条款外，任何节点抛异常都会终止整张图。
- **原因**：State 已锁定为 6 个字段，且明确不加 `report` / `error`；条件边需要路由信号，State 里没有能装"整节点失败"的字段。
- **定位过程**：设计 Edge 时发现"节点级失败"在锁定的 State 里没有路由信号。
- **解决方案**：**接受为当前阶段的架构决策**。调用方用最终 State 的 `contract_id` / `final_results` / `failed_clauses` 自行重建 `ReviewReport`。真实 LangGraph 上，Contract Loading 抛出的 `ContractNotFoundError`、与 LLM 分支并行的 Rule Check 抛出的 `RuntimeError`，都被原样向上抛出（对应测试通过，确认到"类型没被换成别的类型"这一级）。
- **为什么采用这个方案**：先跑通主链路，用真实测试决定是否值得增加失败处理。
- **如何避免再次发生**：把这类决定写进文档（README 已知限制）；如果真实使用中"解析失败导致整次审查崩溃"变得常见，再扩大 State、加条件边。
- **面试价值**：中高。能讲清"先做最小可用，并明确记录已知取舍"。

## P-15 Chroma 的 metadata 不接受 `None`

- **问题**：`Evidence.article` 可以为 `None`，但 Chroma 的 metadata 不接受 `None` 值。
- **现象**：（设计阶段识别，代码里预先处理，未出现运行时报错。）
- **原因**：Chroma metadata 只支持字符串 / 数字 / 布尔。
- **定位过程**：设计 `KnowledgeLoader._to_metadata` 时对照 Chroma 的限制。
- **解决方案**：`article` 为 `None` 时**不写这个键**，而不是写 `article=None`；检索时用 `metadata.pop("article", None)` 还原。
- **为什么采用这个方案**：保持 `Evidence` 的可选语义，不引入"空字符串代表没有"的约定。
- **如何避免再次发生**：写入第三方存储前，先核对它支持的值类型。
- **面试价值**：低。

## P-16 流程：先核对前提再下结论

- **问题**：几次因为没有先核对事实就下了结论或动手。
- **现象**：① 我说各验证脚本"复制了同一份示例合同"，逐字核对后发现四份**并不相同**；② 收到"pytest 没有注册 marker"的报告时，读文件发现交付的 `pytest.ini` 早就注册了；③ 早先假设 `HuggingFaceEmbeddings` 是懒加载（P-01）；④ 写 DeepSeek 默认模型名时没有核实当前有效名称（P-02）。
- **原因**：用印象或记忆代替了对当前文件、当前服务的核对。
- **定位过程**：都是靠"逐字比对""读文件""真实输出"发现的。
- **解决方案**：更正结论；②没有重复修改，而是先做只读诊断。
- **为什么采用这个方案**：没复现就改，即使改对了，也不知道原因。
- **如何避免再次发生**：下结论前先看当前文件；引用数字前先用命令统计；外部服务的版本信息查官方文档。
- **面试价值**：高。体现排查习惯。

## P-17 文档字符串漂移

- **问题**：部分文档字符串描述的功能，代码里并不存在。
- **现象**：`schemas/contract.py`、`schemas/_time.py` 仍写着 SQLite（实际是纯文件系统 JSON）；`schemas/review_report.py` 提到"重试"和"formatter"（都不存在；`output/` 是空包）。
- **原因**：早期设计设想了这些功能，后来没有实现，文档字符串没有回头改。
- **定位过程**：整理阶段用 `grep` 检索"SQLite / 重试 / formatter"，与实际代码对照。
- **解决方案**：**本次整理禁止修改代码**，所以只在 README 的已知限制里如实记录，以代码为准。
- **为什么采用这个方案**：不为整理文档而改变已经验证过的实现。
- **如何避免再次发生**：每次砍掉或推迟一个设想的功能，同步检查相关文档字符串。
- **面试价值**：低。

## P-18 PowerShell 没有 `tail`

- **问题**：给出的验证命令 `pytest ... | tail -1` 在 PowerShell 里不能用。
- **现象**：`tail : 无法将"tail"项识别为 cmdlet……`。
- **原因**：`tail` 是 Unix 命令；开发者环境是 Windows PowerShell。
- **定位过程**：本地报错。
- **解决方案**：改用 `| Select-Object -Last 1`。
- **为什么采用这个方案**：PowerShell 原生等价写法，无需额外安装。
- **如何避免再次发生**：给命令时先确认对方的 shell；README 里写明。
- **面试价值**：低。

## P-19 `pytest.ini` 中的中文（预防性，未实际发生）

- **问题**：`pytest.ini` 里最初写了中文的 marker 描述。
- **现象**：**没有发生任何错误**，这是一个预防性决定。
- **原因**：担心较老版本的 `iniconfig` 在中文 Windows（GBK）下用系统默认编码读取 ini，一旦读崩，整个 pytest 都起不来。
- **定位过程**：交付前复查配置文件的编码风险。
- **解决方案**：把 `pytest.ini` 里的描述改成纯 ASCII（英文），中文说明放在 `tests/README.md` 与 `conftest.py`。
- **为什么采用这个方案**：之前的 `pytest.ini` 本来就是纯 ASCII，没必要引入这个风险。
- **如何避免再次发生**：影响整个工具链启动的配置文件，保持纯 ASCII。
- **面试价值**：低。

## P-20 依赖注入单例绑死了会被测试 override 的下游依赖

- **问题**：新增 `ModificationService` 依赖时，把它当成一个和 `ContractManager`/`ClauseReviewer` 一样的"启动时构造一次、放进 `AppState` 的重对象"，结果它内部持有的 `ContractManager` 引用没有跟着测试的 `dependency_overrides` 走。
- **现象**（bh 本地真实 `pytest` 跑出来的）：`test_create_modification_task_returns_201_with_pending_status` 期望 201 实际拿到 404；`test_list_modification_tasks_returns_created_tasks_in_order` 期望两条任务实际拿到 `[]`。296 passed，只有这 2 条新用例失败。
- **原因**：`tests/test_api_contracts.py` 的 `client` fixture 用 `app.dependency_overrides[get_contract_manager] = lambda: ContractManager(root_dir=tmp_path)` 把"合同存在哪里"换成了测试的临时目录，这个 override 只对**每次请求重新解析 `Depends(get_contract_manager)`** 生效。但 `build_app_state()` 在应用启动（`lifespan`）时就调用了一次 `ModificationService(contract_manager=contract_manager, agent=modification_agent)`，把当时（生产目录）的 `ContractManager` 实例直接封进了 `ModificationService` 对象里，存进 `AppState`；`get_modification_service(request)` 只是把这个封好的单例原样吐出来，从来没有重新经过 `Depends(get_contract_manager)`，override 自然影响不到它。于是：测试通过 override 后的 `contract_manager` 把合同建在了 `tmp_path`，但 `create_modification_task` 路由里的 `modification_service.check_task_conflict(...)` 内部用的却是绑死的生产目录 `ContractManager`，那里找不到这份合同，抛出 `ContractNotFoundError`，被路由映射成 404；POST 从未真正走到 `contract_manager.create_modification_task()`，所以 `tmp_path` 下没有任何 `task_*.json`，GET 自然是 `[]`——两个失败是同一个根因的两个表现，不是两个独立 bug。
- **定位过程**：先确认 schema 改名（`clause_id`→`target_clause_id` 等）不是这次的根因——那部分测试断言之前已经同步改过，且现象是 404/空列表而不是字段不匹配，说明请求根本没走到业务逻辑，而是在更早的地方就被拒绝了；顺着 `create_modification_task` 路由往回查，定位到它同时依赖 `Depends(get_contract_manager)`（会被 override）和 `Depends(get_modification_service)`（不会）两个"本应指向同一个 ContractManager"的依赖；读 `get_modification_service` 的实现，发现它直接从 `AppState` 里取一个启动时就固定好的单例，而不是现场组装；写了一个不依赖 FastAPI 的最小复现脚本（两个不同 `ContractManager` 实例，一个建合同、另一个查合同），真实复现出同样的 `ContractNotFoundError`。
- **解决方案**：`AppState` 不再存 `modification_service`，只存 `modification_agent`（它只包着 `llm_client`，本身不持有 `ContractManager`，可以安全地作为启动时构造一次的单例）；新增 `get_modification_service(contract_manager: ContractManager = Depends(get_contract_manager), modification_agent: ModificationAgent = Depends(get_modification_agent)) -> ModificationService`，每次请求现场用当前解析出的 `contract_manager` 组装一个新的 `ModificationService`。`ModificationService` 本身很轻，现场组装没有可观的性能代价。
- **为什么采用这个方案**：问题的本质是"两个理应共享同一个 `ContractManager` 实例的依赖，走了两条不同的解析路径"；修好它只需要让 `ModificationService` 也经过 `Depends(get_contract_manager)` 这条路径，不需要改 `ModificationService`/`ModificationAgent`/`Validator` 的任何业务逻辑，符合"只做问题定位和修复，不重构架构"的要求。
- **如何避免再次发生**：**任何新增的、内部持有其他 `Depends(...)` 对象的"组合型"依赖（本例是 `ModificationService` 组合了 `ContractManager` + `ModificationAgent`），必须写成"现场组装"的依赖函数，不能作为固定字段塞进 `AppState` 里的单例。** 判断标准：这个对象内部有没有引用另一个"可能会被测试 override"的依赖？有，就必须现场组装；没有（比如只包 `llm_client`/`rule_checker` 这类不会被单独 override 的叶子依赖），才可以作为启动时单例。本次已用一个不依赖真实 FastAPI（沙箱装不上）的手写脚本 `scripts/verify_di_fix.py` 复现 bug 根因并验证修复，但**最终确认仍以 bh 本地重跑的 `pytest tests/test_api_contracts.py -v` 和 `pytest` 全量结果为准**。
- **面试价值**：高。是一个"表面上是路由/schema 问题，实际是依赖注入生命周期管理"的真实案例，能讲清"单例 vs 现场组装"的判断标准，以及为什么"看起来更省事的写法"在可测试性上会踩坑。

## P-21 DeepSeek Thinking 模式与强制 `tool_choice` 冲突

- **问题**：`ModificationAgent` 在沙箱里用假 `openai` 客户端验证过全部分支（正常/未调用工具/JSON 非法/越界等），第一次真实联调 DeepSeek 就报错。
- **现象**：`llm/client.py::chat_with_tool` 真实调用 DeepSeek 时返回 HTTP 400：`{"error": {"message": "Thinking mode does not support this tool_choice", "code": "invalid_request_error"}}`，触发点是 `self._client.chat.completions.create(..., tools=[tool_schema], tool_choice={"type": "function", "function": {"name": tool_name}})` 这一次调用；沙箱里的替身测试（`scripts/verify_agent_function_calling.py`）全部通过，因为假客户端只按脚本返回预设的 `tool_calls`，从不真的把请求发给 DeepSeek，自然不会触发服务端对 `tool_choice` 的校验。
- **原因**：DeepSeek 从 V3.2/V4 起，"thinking 模式"（模型在给出最终答案前先做链式推理）下支持 Function Calling，但**只支持 `tool_choice` 为省略/`"auto"`/`"none"`**——`"required"` 和"强制指定某一个具体函数"（本项目 `chat_with_tool` 用的正是后者）在 thinking 模式下会被服务端直接拒绝，返回同样这条 400 错误（社区已有相同报告：[DeepSeek-V3 issue #1376](https://github.com/deepseek-ai/DeepSeek-V3/issues/1376)、[any-llm issue #1384](https://github.com/mozilla-ai/any-llm/issues/1384)）。代码本身没有任何一处显式打开 thinking——这是**当前配置的模型/接口默认启用的行为**，不是本项目请求参数里主动设置的；具体是 `.env` 里 `DEEPSEEK_MODEL` 配置成了带 thinking 的模型（本项目文档里标注"复杂推理任务"的 `deepseek-v4-pro` 一类），还是 DeepSeek 侧近期把 thinking 设为了这一档模型的默认状态，需要 bh 核对当时真实生效的 `DEEPSEEK_MODEL` 值来确认——这条信息我在这个沙箱里看不到、也不该替你猜。
- **定位过程**：先确认这不是"JSON 解析出错"或"越界修改"这类业务逻辑问题（`modification/tool.py`、`modification/validator.py` 都还没被跑到，报错来自 `chat_with_tool` 内部的 `self._client.chat.completions.create(...)` 这一步本身，是 `OpenAIError` 被包装成 `LLMClientError` 抛出来的）；核对 `chat_with_tool` 的请求构造，确认 `tool_choice` 传的是强制指定函数名这种形式；用 `WebSearch`/`WebFetch` 查 DeepSeek 官方 Thinking Mode 文档与社区已知问题，交叉确认"thinking 模式排斥强制 `tool_choice`"是 DeepSeek API 一个已被多方独立报告的真实限制，而不是本项目参数拼错。
- **解决方案**（**已实施并已用替身测试验证**，真实 DeepSeek 联调结果待 bh 反馈）：`chat_with_tool` 的 `tool_choice` 从强制指定函数名改为 `"auto"`。因为本工具集第一版只注册了 `modify_clause` 一个工具，`"auto"` 下模型能选的就只有"调用这一个工具"或"不调用任何工具直接回文本"两种结果；后者已经被现有代码天然覆盖（`if not tool_calls: raise LLMClientError(...)`），会被 `ModificationAgent` 包装成 `ModificationAgentError`，被 `modification/service.py::start_modification` 记成一次失败的 `ModificationAttempt`，计入 3 轮重试上限——不需要新增任何异常分支或状态。已知代价：社区实测 `"auto"` 下模型大约有 25% 的概率直接回文本、不调用工具（即便只给了一个工具），会让重试次数消耗得更快。`scripts/verify_agent_function_calling.py` 已加一条回归断言，直接检查真正传给底层 SDK 的 `tool_choice` 确实是 `"auto"`、`tools` 里仍然是完整的 `modify_clause` schema（10/10 通过，仍是假 `openai` 客户端上的替身验证，不能替代真实 DeepSeek 联调）。
- **为什么推荐这个方案**：改动范围最小（只改 `chat_with_tool` 里的一个参数值），不删除 `tool_choice` 参数本身、不改 Prompt 结构、不引入新的 JSON 解析路径、不碰 `ModificationAgent`/`Validator`/Service 状态机/Human-in-the-loop 的任何一行；"模型选不选调用工具"这件事从"API 层强制"变成"业务层校验+重试"，但校验和重试机制本来就已经存在（本项目的架构本来就是"Agent 可能失败，Validator/Service 兜底"，不是假设 Agent 一定成功）。
- **对 Agent 架构的影响**：这次修复后 Function Calling 依然是**真正的** Function Calling——请求里仍然声明 `tools=[tool_schema]`，DeepSeek 仍然通过真实的 `tool_calls` 字段返回结构化参数（不是让模型在文本里"假装"输出 JSON 再手写正则去抠），模型依然是自己决定要不要调用、怎么填参数；变化只是"是否被服务端强制要求必须调用"，不影响"调用之后怎么解析、怎么校验、怎么走 Human-in-the-loop"这条完整链路。`ModificationAgent` 的接口签名、`modification/tool.py`/`modification/validator.py`/`modification/service.py` 都不需要动。
- **如何避免再次发生**：真实联调新接入的 LLM 能力（尤其是 Function Calling / 强制工具调用类参数）之前，先查一遍该模型是否有"推理/thinking"变体，以及该变体对请求参数有没有额外限制——沙箱里的替身测试只能验证"代码解析响应的逻辑对不对"，验证不了"服务端到底接不接受这个请求"，这类问题只有真实联调才能暴露（和 P-01 是同一类风险，但 P-01 是"假依赖行为和真依赖不一致"，这次是"请求参数本身被真实服务拒绝"，属于新的一类）。
- **面试价值**：高。一个"沙箱全绿、真实联调才炸"的典型案例，还涉及"强制工具调用 vs 推理模型"这个眼下大多数 Agent 框架都会踩的真实坑，能讲清楚"Function Calling 的真实性不取决于 tool_choice 是不是强制"，以及怎么把一个 API 层的硬限制转化成已有重试/兜底机制能吸收的失败模式，而不是被迫新增分支。

## P-22 V2 重建全文时款级子 Clause 内容被静默丢弃（12 字段格式）

- **【问题】**：`ModificationService._build_v2_text` 重建 V2 全文时，错误假设"款/项级别的子 Clause 文本已经包含在其所属条（`hierarchy_level==0`）的 `original_text` 里"，只拼接了 `hierarchy_level==0` 的文本。
- **【现象】**（bh 真实浏览器验收测试发现）：V1→V2 的条款级 Diff 里，`clause_000`~`clause_011` 几乎全部显示"已修改"，但看上去大多数只是换行格式变化；同时 Risk Diff 显示 `V1=v1_001`、`V2=v1_001`，两个 review_id 字符串完全相同，非常可疑。
- **【最初怀疑】**：怀疑 `clause_diff` 用了朴素字符串比较，没有做格式规范化（换行/空白差异被误判为"已修改"）。
- **【定位过程】**：用户要求"先定位根因，不要直接修改代码"。先按"最初怀疑"写了一个**真实执行** `ClauseSplitter` + `_build_v2_text` 的验证脚本（不是手写假 Clause 对象），用和 bug 报告里格式相同的样例（"1.1"/"1.2" 子编号）去跑——结果推翻了"格式差异"这个最初假设：这种子编号不会被三种 `_ITEM_STYLES` 正则识别，整条本来就是一个 `hierarchy_level=0` 节点，往返后逐字节相同，`changed=False`。但在样例里加入一条能被识别出款（单层编号"1." "2."）的条款后，真实执行结果显示这一条的款级 Clause（`clause_004_1`/`clause_004_2`）在 V2 里完全消失——用真实代码执行的证据纠正了最初的猜测，找到了一个比"格式规范化"更严重的真实数据丢失 bug。
- **【真正根因】**：`clause/clause_splitter.py::_split_article` 在识别出条内的款项编号（"1." "（一）" "（1）" 三种正则样式之一）后，会把这一条拆成 1 个 `hierarchy_level=0`（只含标题/引导文字，`clause_00N`）+ N 个 `hierarchy_level=1`（每一款自己的正文，`clause_00N_k`，`parent_clause` 指回 `clause_00N`）。`_build_v2_text` 只筛选并拼接 `hierarchy_level==0` 的 Clause，对于任何被识别出款的条，重建出的 V2 全文里这一条只剩标题，所有款级正文（无论有没有被律师修改过）全部消失；如果律师确认修改的正是某个款级 `clause_id`（`task.target_clause_id` 指向 `hierarchy_level=1` 节点），这条已确认的修改也会被静默丢弃——`_build_v2_text` 只按 level=0 的 `clause_id` 去查 `confirmed_by_clause_id`，查不到对应的款级 id。（注：Risk Diff 显示 `v1_001`/`v1_001` 是另一个独立根因——`contract/manager.py::save_review` 硬编码 `contract_version="v1"`，已在 P-23 里单独修复，两者是同一轮报告里的两个独立问题，不要混为一谈。）
- **【解决方案】**：不再假设"level=0 已经包含 level=1 内容"，改为以"条"为单位、基于原始全文的字符偏移量做局部替换重建：
  1. 新增 `_group_clauses_by_article`：按 `parent_clause` 把 `hierarchy_level=0` 的条和它所有的 `hierarchy_level=1` 款分成一组（复用 `ClauseSplitter` 已经算好的父子关系，不重新用正则去猜）。
  2. 新增 `_reconstruct_article_text`：把一组节点按 `start_char` 排序后逐个输出——命中已确认修改的节点用 `task.current_modified_text` 替换它自己的字符区间，未命中的节点直接从 **V1 原始全文**（`contract_manager.get_parsed_text`，而不是已经被裁剪过的 `clause.original_text`）里取对应字符；节点与节点之间的"缝隙"（标题与第一款之间、各款之间的空白/换行）永远原样从原文复制，不受任何修改任务影响。
  3. `_build_v2_text` 改为对每一组调用 `_reconstruct_article_text`，组与组（条与条）之间仍用固定的 `"\n\n"` 分隔（已知的、范围有限的简化，不会丢内容，只可能让条与条之间的空行数量和 V1 不完全一致——这部分交给未来 clause_diff 的格式规范化去兜底，本次修复范围只解决"条内内容丢失"）。
  4. `generate_v2` 相应改为读取 V1 的原始全文并调用 `_group_clauses_by_article`，不再直接过滤 `hierarchy_level==0`。
  只改动 `modification/service.py` 一个文件；`clause/clause_splitter.py`、`schemas/`、`contract/manager.py`、`parser/`、`review/pipeline.py` 全部未改动。
- **【为什么这样解决】**：字符偏移量（`start_char`/`end_char`）是切分阶段留下的、指向**原始全文**这个唯一事实来源的可靠依据，不变量 `full_text[start:end] == original_text` 保证了"按偏移量局部替换"不会引入任何裁剪/重新格式化带来的失真；相比之下，"把所有子节点的已裁剪字符串重新拼起来"看似能解决"内容都在了"，实际会丢失节点之间原有的分隔符/空白（这正是本次调查一开始怀疑、但用真实执行证伪了的"格式差异"问题，只是它真正会发生在"拼接款"这一步，而不是"条与条之间"）。用 `parent_clause` 做分组依据而不是重新推导，是因为这是 `ClauseSplitter` 已经计算好、存在 Clause 里的结构化信息，复用它比重新跑一遍正则更可靠，也不需要改 `ClauseSplitter` 本身。
- **【验证结果】**：已实施，`scripts/verify_v2_article_reconstruction.py`（68/68，真实执行 `ClauseSplitter` + 修复后的 `_build_v2_text`，覆盖：无修改 / 改条级 / 改一个款 / 改多个款 / 一条部分改部分不改 / 有款无款混合 / 重新切分后父子结构正确 / 全局"内容不丢失"子串断言）+ `scripts/verify_modification.py`（73/73）真实执行验证通过；**bh 本地重跑 `pytest` 全量通过**，确认修复生效。
- **【工程经验】**：对"切分器产出的树形结构"做二次加工（拼接、重建、聚合）时，必须先在文档里（或代码注释里）明确写出"父节点的内容范围是否包含子节点"这个假设，并且**必须用真实会触发子节点分支的样例去验证**，不能只用简单样例（本次的 bug 之所以没被 `scripts/verify_modification.py` 的手写 Clause 测试发现，正是因为那份测试从未构造出真实的 `hierarchy_level=1` 结构）。
- **【Agent / LangGraph 经验】**：本 bug 与 LangGraph 编排本身无关（`review/pipeline.py` 未改动），但和"Agent 产出的结构化数据被下游二次加工"这一类问题相关：Modification Agent 的输出（`task.current_modified_text`）只是被拼接进一个更大的文本重建流程里的一个片段，Agent 本身不知道、也不需要知道自己的输出会被怎样拼接——数据契约（"我只负责替换我自己的字符区间"）应该在编排层显式维护，不能依赖 Agent 自己保证上下文完整性。
- **【面试怎么讲】**：一个"对切分器输出结构的隐含假设，只在部分分支成立，且没被测试样例覆盖到"的真实案例，讲清楚"用原始字符偏移量做局部替换"和"拼接已处理字符串"这两种文本重建思路的本质区别，以及如何设计"内容是否被静默丢弃"这类全局不变量测试（断言"未改内容必须仍作为子串存在"，而不是只断言"程序没崩溃"）。
- **【是否已解决】**：是。已在真实环境（bh 本地）验证生效。

## P-23 `save_review` 硬编码 `contract_version` 导致 V1/V2 review_id 撞车（12 字段格式）

- **【问题】**：`ContractManager.save_review` 内部硬编码 `contract_version = "v1"`，不管调用方传进来的 `contract_id` 实际代表的是 V1 本身，还是 V2 内部使用的 `linked_contract_id`。
- **【现象】**（bh 真实浏览器验收测试发现，和 P-22 是同一轮报告里的两个现象）：Risk Diff 界面显示 `V1 = v1_001`、`V2 = v1_001`，两个 `review_id` 字符串完全相同，非常可疑，怀疑 `risk_diff` 把同一份 `ReviewRecord` 错误地拿来和自己比较。
- **【最初怀疑】**：怀疑 `risk_diff` 的匹配逻辑有 bug——把 V1、V2 两次 `get_latest_review` 调用错误地指向了同一个 `contract_id`，导致读到同一份记录、和自己比较。
- **【定位过程】**：先复核 `risk_diff`（`get_latest_review` 两次调用分别传的是不是同一个 `contract_id`）——确认不是，两次调用的参数确实不同，说明问题不在"取哪份记录"，而在"记录被存下来时打的标签"，推翻了最初怀疑；顺着 `get_latest_review` → `list_reviews` → 磁盘上 `review_*.json` 的文件名规则往回查，定位到 `save_review` 里 `contract_version = "v1"` 这一行硬编码，且函数文档字符串本身写着"当前阶段合同版本恒为 v1，因为生成新版本的能力还没有实现"——这条注释在 V2 生成能力（见 P-22 所在的那一轮改动）实现之后从未同步更新过，是本次踩坑的根源。
- **【真正根因】**：`review_id` 的编号规则是"在这个 `contract_id` 自己的 `review/` 目录里，从 1 开始数、拼上 `contract_version` 前缀"。V1 的 `review/` 目录和 V2（`linked_contract_id`）的 `review/` 目录本来就是两个完全独立的目录，`risk_diff` 分别用 `get_latest_review(contract_id)` 和 `get_latest_review(version.linked_contract_id)` 读到的也确实是两个不同的 `ReviewRecord` 对象——**risk_diff 的匹配逻辑本身没有问题**。问题纯粹在于：V2 对应的 `linked_contract_id` 是第一次调用 `save_review`，这个目录里 `existing` 是空的，而 `contract_version` 又被硬编码成了 `"v1"`，于是算出来的 `review_id` 恰好也是 `"v1_001"`——和 V1 自己的第一条 review 撞成同一个字符串，纯属标签层面的巧合，不代表数据出错。
- **【解决方案】**：`save_review` 增加一个显式参数 `contract_version: str = "v1"`（默认值保留向后兼容，但**要求所有真实调用方都显式传值**，不依赖默认值）：
  - `api/routes/contracts.py`（V1 review pipeline 唯一的落盘点）调用时传 `contract_version="v1"`；
  - `modification/service.py::run_v2_review`（V2 独立复审唯一的落盘点）调用时传 `contract_version=version_number`（该方法本来就有的入参，默认值正是 `"v2"`）——不是新发明一个值，是直接复用方法自己已经知道"这次复审是给哪个版本做的"这个信息。
  `save_review` 本身不做任何"从 `contract_id` 反推版本"的推断：两个内部 `contract_id` 在数据结构上完全对等，无法从 `contract_id` 本身看出"这是谁的 V2"，只有调用方知道语境，所以版本号必须由调用方显式声明，不允许猜。
- **【为什么这样解决】**：改动范围最小——只在 `save_review` 签名上加一个参数，不改 `ReviewRecord` schema（`contract_version` 字段本来就存在，只是没被正确赋值过），不改 `list_reviews`/`get_latest_review`（它们本来就不依赖 `contract_version` 或 `review_id` 字符串做任何判断，只按 `created_at` 排序，所以完全不受影响），也完全不碰 `risk_diff` 的匹配/分类逻辑（`risk_diff` 判断"这是不是 V2 的记录"依据的始终是"从哪个 `contract_id` 的 `review/` 目录读出来的"，从来不是 `review_id` 字符串前缀，这次修复前后这一点都成立，只是修复前巧合地打了容易让人误解的标签）。
- **【验证结果】**：已实施，`scripts/verify_modification.py`（73/73）真实执行验证通过——新增/更新了针对 V1/V2 `review_id` 的专项断言（V1 连续两次保存分别得到 `v1_001`/`v1_002`，V2 第一次保存得到 `v2_001`，二者不相等；`risk_diff` 返回的 `v1_review_id`/`v2_review_id` 分别是 `v1_002`/`v2_001`，能互相区分）；**bh 本地重跑 `pytest` 全量通过**，V1/V2 的 `review_id` 现网也已分别显示为 `v1_00N`/`v2_00N`。
- **【工程经验】**：**任何"当前阶段功能还没实现，先写死一个值"的代码，都应该在文档字符串里同时标注"实现了对应功能之后必须回来检查这里"，并且最好让签名本身在调用方忘记传参时也不会默默用一个可能错误的默认值掩盖问题**（本次选择保留默认值 `"v1"` 是为了不强制修改测试脚本之外不知道的第三方调用方，但所有已知的真实调用方都已改成显式传参，不依赖默认值）。
- **【Agent / LangGraph 经验】**：与 LangGraph 编排无直接关系；但和"V2 是否是一条独立数据管线"这个设计判断相关——`run_v2_review` 复用的是同一个未改动的 `run_review`，V1/V2 在存储层被当成两个平等的 `contract_id`，这意味着任何"隐式假设自己在处理 V1"的代码（本例是硬编码 `"v1"`）在 V2 场景下都会出问题，这类隐式假设应该在设计 V2 时就集中排查一遍，而不是等真实使用暴露。
- **【面试怎么讲】**：一个"两处独立正确的逻辑（存储隔离、Diff 匹配），被第三处硬编码的标签生成规则搞出误导性巧合"的案例，讲清楚"数据本身没错，但展示给人看的标签造成了错误的怀疑方向"这种问题该怎么定位——先验证"两次读取是不是真的读了同一份数据"，而不是直接假设匹配逻辑有 bug。
- **【是否已解决】**：是。已在真实环境（bh 本地）验证生效。

## P-24 `generate_v2` 写临时文件时 `os.linesep` 导致换行符损坏（12 字段格式）

- **【问题】**：`ModificationService.generate_v2` 用 `tmp_path.write_text(v2_text, encoding="utf-8")` 把重建出的 V2 全文写入临时文件，这是 Python 默认的文本模式写入（`newline=None`），会把字符串里裸的 `"\n"` 替换成当前平台的 `os.linesep`。
- **【现象】**（bh 真实浏览器验收测试发现，且是在 Fix A/Fix B 都已部署之后才暴露出来的）：条款级 Diff 里，**没有被律师修改过**的条款（clause_002~005、007、008），V2 文本相比 V1 在"标题"和"正文"之间多了一个空行，正文一字未变；而**真正被修改过**的条款（clause_000、001、006）反而没有这个问题。规律非常干净：只和"这段文本有没有经过律师确认修改"相关，和条款内容本身无关。
- **【最初怀疑】**：怀疑是 `clause_diff` 缺少格式规范化（换行/空白差异被当成"已修改"）——即怀疑和 P-22 最初的怀疑类似的问题在别处重演。
- **【定位过程】**：用户要求先重新跑真实浏览器测试，看 Fix A/Fix B 部署后症状是否还在——发给我的真实条款级 Diff 数据显示症状仍在，但规律和最初怀疑的"clause_diff 缺少格式规范化"不同：只和"是否被修改"相关，和条款结构（有没有款）无关。这个规律排除了 `_build_v2_text`/`_reconstruct_article_text` 本身的问题（P-22 已经用真实数据验证过它对未修改片段的重建是逐字节保真的），把范围收窄到"重建出的文本之后又经过了什么处理"——顺着 `generate_v2` 往下看，只剩"写入临时文件"这一步会接触到字符串的字节表示，而 `Path.write_text` 默认的换行转换行为，结合项目已知的"部署环境是 Windows"这条历史记录（P-18/P-19），完整解释了全部观察到的现象。
- **【真正根因】**：项目实际部署环境是 Windows（`docs/PITFALLS.md` P-18/P-19 已经记录过这一点），Windows 上 `os.linesep == "\r\n"`。V1 原始上传的 `.txt` 文件本身很可能是 Windows 常见的 CRLF（`\r\n`）换行：
  - **未被修改的条款**：`_reconstruct_article_text`（P-22 引入）从 V1 原始全文里原样切出来的片段，天然带着原始的 `\r\n`。写入临时文件时，`write_text` 的默认换行转换规则只替换字符串里裸的 `"\n"`，不会特殊处理已经存在的 `"\r"`——于是原本的 `"\r" + "\n"` 变成 `"\r" + os.linesep`，在 Windows 上就是 `"\r" + "\r\n"` = `"\r\r\n"`，多出一个 `"\r"`。这个多余的 `"\r"` 在浏览器等渲染场景里常被当成额外一次换行，看起来像多了一个空行，但字符内容没有任何增删。
  - **被修改的条款**：文本来自 `task.current_modified_text`（Agent/LLM 生成的候选文本），本来就是干净的 `"\n"`，不含预先存在的 `"\r"`，写入时不会触发这个问题。
  这正好解释了"只有没改过的条款才多空行，改过的反而没问题"这个反直觉现象。
- **【解决方案】**：`generate_v2` 里改成 `tmp_path.write_text(v2_text, encoding="utf-8", newline="")`——`newline=""` 是 Python 官方文档定义的"完全关闭换行符转换，原样写出字符串里已有的字符"，平台无关。只改这一行，不改 `clause_diff`、不引入任何文本规范化逻辑、不改 `ClauseSplitter`/`Parser`/`Schema`/`ContractManager`/Review Pipeline，也不影响 P-22（Fix B）、P-23（Fix A）已经验证过的逻辑。
- **【为什么这样解决】**：这不是"展示层格式不一致"，是写入这一步真实损坏了字节，属于数据完整性问题，应该在损坏发生的源头解决，而不是在 `clause_diff` 里做规范化去"猜"哪些差异是格式噪音——那样做治标不治本，还天然有"过度规范化、消掉真实修改"的风险（这正是用户对 Fix C 的原始顾虑）。`newline=""` 和 `parser/document_parser.py` 里"不做 strip、不统一换行"这条一直坚持的不变量是同一种精神：不静默改写文本，读的时候不转换，写的时候也不转换。
- **【验证结果】**：`scripts/verify_p24_newline_write.py`（6/6）——本沙箱是 Linux，`os.linesep` 恒为 `"\n"`，且实测验证过给 `os.linesep` 赋值也不会改变 `write_text` 的实际写入行为（CPython 的 io 模块在文本模式写入时使用的是平台真实换行符，不是重新读取 `os` 模块这个可变属性），所以"Windows 上 `\r\r\n` 损坏"这个具体故障在本沙箱里无法被复现，验证脚本能证明的只是 `newline=""` 参数本身的平台无关语义和 `generate_v2` 确实已经改用它。既有回归测试 `scripts/verify_modification.py`（73/73）、`scripts/verify_v2_article_reconstruction.py`（68/68）、`scripts/verify_agent_function_calling.py`（10/10）、`scripts/verify_di_fix.py`（11/11）全部仍然通过。**已由 bh 在真实 Windows 环境重新生成 V2、真实浏览器核对确认**：未被修改的条款（clause_002/004/005/006/008）现在正确显示"未修改"，不再因为多余空行被误判；真正被修改的条款（clause_000/001/003/007）仍然正确显示"已修改"；Risk Diff 的 `v1_review_id`/`v2_review_id` 正确显示为 `v1_001`/`v2_001`（P-23 同步确认）。修复生效。
- **【工程经验】**：**任何要把字符串写回文件、这个字符串里可能包含"从别处原样切出来的原始文本"的地方，都应该显式传 `newline=""`，不要依赖默认的 `newline=None`**——默认行为是"平台相关的静默转换"，在 CI/开发机是 Linux、生产是 Windows（或反过来）这种环境不一致的项目里特别容易踩，而且只在处理"本来就带 `\r\n` 的原始文本"时才会暴露，纯 ASCII/LF 测试数据永远测不出来。
- **【Agent / LangGraph 经验】**：与 LangGraph 编排、Agent 决策逻辑都无关，是纯粹的 I/O 层问题；但提醒了一个更通用的教训——Agent/Modification 这类"生成文本、再拼接回大文档"的链路里，凡是文本要落盘或跨平台传输的环节，都要显式声明编码与换行策略，不能依赖语言/库的默认行为，因为默认行为往往是"看起来正确、只在特定平台组合下才出错"。
- **【面试怎么讲】**：一个"表面症状看着像 Diff 逻辑/格式规范化问题，实际根因是跨平台文本写入的默认行为"的真实案例，讲清楚 `open()`/`write_text()` 的 `newline` 参数语义、为什么"测试环境和生产环境操作系统不同"会让一类 bug 只在生产环境暴露、以及怎么通过"规律和什么相关、和什么无关"这种排除法把范围从"某个模块的逻辑"收窄到"某一行具体的 I/O 调用"。
- **【是否已解决】**：是。已在真实 Windows 环境验证生效。

## P-25 Modification/Review 架构升级（Batch/Risk Analyzer/V2 独立生成服务）踩坑记录（2026-10-09）

- **【问题背景】**：本轮需求要求 Review Graph 的 `report_assembly` 节点真正产出最终 `ReviewReport`（之前只是“构造一次验证能不能构造出来”，真正返回值在图外重新拼一次）；`ModificationTask` 需要去掉 `COMPLETED` 终态、新增 `ABANDONED`；修改候选通过 Validator 后要跑一次独立的“修改后风险分析”（Risk Analyzer）；新增 `ModificationBatch` 作为“一轮修改”的容器；V2 生成要从 `ModificationService` 搬到独立的 `V2GenerationService`，以 `batch_id` 为单位而不是扫描全合同的任务。
- **【真实踩到的问题 1：`ModificationAgent.generate_candidate` 的 `review_result` 入参类型收紧后差点被迫新建一套 Prompt】**：`ModificationTask` 新增 `source_review_snapshot`（`ReviewResultSnapshot`，不是 `ReviewResult`），`start_modification` 理应传这份冻结快照给 Agent，而不是重新查“最新一次审查”——但 `build_modification_messages`/`_format_review_result` 的类型签名原来写的是 `Optional[ReviewResult]`。
  - **根因**：`ReviewResultSnapshot` 和 `ReviewResult` 共享 `risk_level`/`reason`/`legal_basis`/`suggestion` 四个字段名，Python 是结构化调用（鸭子类型），运行时完全不需要两者是同一个类或有继承关系。
  - **解决方案**：不新建 `ReviewResultSnapshotPromptAdapter` 之类的包装类型，只把类型签名放宽成 `Optional[Union[ReviewResult, ReviewResultSnapshot]]`，函数体一行没改。
  - **工程经验**：当两个 schema 因为“冻结快照”这类需求天然需要字段重叠时，先看下游消费者是不是只按属性读取（没有 `isinstance` 判断、没有调用只属于其中一个类型的方法）——如果是，鸭子类型足够，不需要为了"类型更严格"而发明适配层，那样反而会制造一次没有必要的改动面。
- **【真实踩到的问题 2：Risk Analyzer 失败路径必须"不阻塞"，容易写成"阻塞"】**：需求明确要求 Risk Analyzer（复用 `ClauseReviewer.review`）调用失败时，任务必须**仍然**进入 `WAITING_CONFIRMATION`，只是把失败原因记进 `risk_analysis_error`、`risk_resolution` 置为 `UNKNOWN`。第一版实现本能地想在 `_run_risk_analysis` 里直接 `try/except` 再 `raise`，这样会让 Validator 已经通过的候选因为"风险分析这个锦上添花的步骤"失败而整体失败，违反需求。
  - **解决方案**：`_run_risk_analysis` 捕获任意异常后返回 `(None, str(exc), RiskResolution.UNKNOWN)` 这个三元组，调用方（`start_modification`）永远按"拿到一个结果三元组"处理，不区分成功/失败两条代码路径——这样"失败"在类型层面就是正常返回值的一种，不是异常控制流，从结构上保证不会被写成阻塞。
  - **工程经验**："失败不能阻塞主流程"这类需求，最好通过"把失败也建模成一个正常的返回值"来实现，而不是"捕获异常后继续执行"——后者在未来有人往 `start_modification` 加新代码时，很容易在 `except` 块和主流程之间插入一条新语句，不小心又变成阻塞。
- **【真实踩到的问题 3：批次就绪判断必须是 batch-scoped，容易不小心写成 contract-scoped】**：旧版 `generate_v2` 直接 `list_modification_tasks(contract_id)` 扫描全合同任务；本次要求改成只看 `batch.task_ids` 对应的任务。写验证脚本时第一次踩了这个坑——给同一份合同创建了两个批次，分别确认各自的任务后，`V2GenerationService.generate` 对其中一个批次调用时，如果不小心用 `list_modification_tasks` 而不是 `[get_modification_task(tid) for tid in batch.task_ids]`，就会把另一个批次的任务也算进"是否就绪"，在数据量小的测试里恰好两个批次都刚好读起来"看似就绪"，容易误判为通过。
  - **解决方案**：`compute_batch_readiness` 这个纯函数只接受"任务列表"这一个参数，调用方必须显式构造出"只属于这个批次"的列表（`[contract_manager.get_modification_task(contract_id, tid) for tid in batch.task_ids]`），函数签名上就不给"传整个合同的任务列表"留机会。
  - **验证方式**：`scripts/verify_modification.py` 第 6 节故意在同一份合同下创建了 `batch_ready_test`（已就绪）和 `batch_pending_test`（故意留一条 pending 任务）两个批次，断言后者调用 `generate` 必须被拒绝——这正是用来防止"batch-scoped 判断退化成 contract-scoped"这类回归的用例。

**【Agent / LangGraph 知识点】**：Risk Analyzer 复用 `ClauseReviewer.review` 而不是新建一条 RAG→LLM 链路，是"同一种能力、不同调用场景"时优先复用而不是复制的例子；但复用不等于直接传同一个 Clause 对象——必须构造一个"把 `original_text` 换成候选文本"的新 Clause（`clause.model_copy(update=...)`），否则审查的对象仍然是修改前的原文，结果没有意义。这类"同一个处理函数、不同数据"场景，`model_copy(update=...)` 比手写一个新对象更不容易在字段同步上出错（新增字段时自动带过去，不需要在两处分别列出全部字段）。

## P-26 `risk_diff` 按 `rule_id` 匹配导致同规则多条款结果互相覆盖（12 字段格式）

- **【问题】**：`diff/risk_diff.py` 在对比 V1/V2 的风险结果时，规则来源（`ReviewSource.RULE`）的结果只按 `rule_id` 匹配，而同一条规则（如 `probation_salary_below_80_percent`）可能在一份合同里对多个不同条款分别命中，产出多条 `rule_id` 相同、`clause_id` 不同的 `ReviewResult`。
- **【现象】**：这是在只读后端审计阶段（阶段 1）里被发现的，不是从真实故障报告倒推的——审计时直接阅读 `risk_diff()` 的实现发现 `v1_by_key = {_result_key(r): r for r in v1_results}` 是字典推导式，`_result_key` 对规则结果只返回 `("rule", rule_id)`，据此推断"同一规则命中多个条款时会互相覆盖"；本次修复先用最小复现用例验证了这个推断确实成立（构造两条 `rule_id` 相同、`clause_id` 不同的结果传入 `risk_diff()`，旧实现只返回 1 条 entry，而不是预期的 2 条）。
- **【最初怀疑】**：无——问题是直接从代码逻辑读出来的，不存在"最初怀疑了别的方向，后来排除"的过程。
- **【定位过程】**：阅读 `_result_key()` 和 `risk_diff()` 的实现，结合 `rules/probation_salary.py::check_probation_salary()` 的实现（它对传入的每个 `Clause` 独立判断，命中的每个条款各产出一条结果，没有数量上限），确认"一条规则命中多个条款"在当前规则实现下是真实可能发生的场景，不是理论上的边界情况。
- **【真正根因】**：`risk_diff()` 用字典推导式构建 `v1_by_key`/`v2_by_key`，Python 字典推导式对重复 key 的行为是"后面的值覆盖前面的"，这是语言本身的确定性行为，不是随机 bug；`_result_key()` 给规则结果选择的 key（只用 `rule_id`）丢失了"这条结果具体关联哪个/哪些条款"这个区分信息，导致本应是不同 key 的两条结果被错误地当成了同一个 key。
- **【解决方案】**：重写 `_result_key()`：LLM 来源结果继续按 `clause_id` 匹配（不变）；规则来源结果按优先级取可用的条款信息构造 key——有 `clause_id` 就用 `("rule", rule_id, "clause", clause_id)`，没有 `clause_id` 但有 `related_clause_ids`（跨条款问题，如 `probation_duration`）就用 `("rule", rule_id, "related", tuple(sorted(related_clause_ids)))`，两者都没有（真正的合同级问题，当前两条规则都不会触发这一分支）才退化为只用 `("rule", rule_id)`。同时把"展示用的 ref 字符串"从"反推 key"改成直接从 `ReviewResult` 对象取值（新增 `_clause_ref()`/`_describe_key()`），让 key 的职责纯粹是"判断是不是同一条"，不再和展示格式耦合。
- **【为什么这样解决】**：需求明确排除了两种简化方案——"全部按 `related_clause_ids` 匹配"会让单条款问题（本来有明确 `clause_id`）退化成空列表匹配，比现状更容易互相覆盖；"直接删除或跳过重复结果"会造成新的数据丢失，而不是解决数据丢失。按"这条结果实际携带了什么条款信息"分情况取 key，是在不扩大 `ReviewResult` 数据模型（不新增字段）的前提下，用现有字段能做到的最小且语义正确的修复。退化分支（两个字段都为空时只用 `rule_id`）是一个已知的、现有数据模型下无法进一步区分的理论限制，不在本次范围内通过扩大数据模型解决。
- **【验证结果】**：新增 `tests/test_risk_diff.py`（9 个测试），修复前先确认旧实现下 5/9 失败（精确复现"同 rule_id 不同 clause_id 互相覆盖"及其衍生场景：条目数变少、V1→V2 条款漂移被误判为"未变化"而不是"V1 消失+V2 新增"）；修复后 9/9 通过。同时运行了现有的规则相关测试（`test_rules_checker.py` 5/5、`test_rules_merge.py` 7/7、`test_rules_probation_duration.py` 12/12、`test_rules_probation_salary.py` 9/9，均未受影响、全部通过）以及项目里其余不依赖沙箱缺失第三方包（`fastapi`/`langgraph`/`langchain_core`/`openai`/`chromadb`/`langchain_text_splitters`，这是本沙箱一直存在的网络限制，与本次改动无关）的测试文件（`test_contract.py` 29/29、`test_schemas.py` 38/38、`test_llm_prompts.py` 7/7、`test_review_schemas.py` 7/7），总计 124/124 通过，全仓库 `py_compile` 语法检查无错误。`diff/clause_diff.py` 此前也是零测试覆盖，本次未新增（超出"只处理 risk_diff 及其直接相关测试"的范围，留给后续）。
- **【工程经验】**：用字典推导式/`dict(...)` 从一个列表构造"按某个字段去重"的映射时，必须先确认这个字段在业务上是否真的唯一；`rule_id` 标识"哪条规则"，不标识"这条规则这次命中了哪个具体对象"，两者是不同维度，不能互相替代——这类 bug 的特征是"字典推导式语法上完全正确，覆盖行为是 Python 的确定性语义"，纯靠阅读代码逻辑（而不是运行时报错）就能定位，根因在于选 key 时对数据语义的假设有误，不是实现细节的笔误。
- **【Agent / LangGraph 经验】**：与本项目的 LangGraph 编排、Agent/LLM 调用无关，是纯粹的 Diff 算法层面的数据建模问题；但提醒了一个更通用的教训——"规则引擎"类模块的输出通常允许"一条规则产出零到多条结果"，任何下游要对这些结果做匹配/去重/分组的代码，都不能假设"规则的标识符本身就能唯一确定一条结果"，必须把"规则命中的对象是什么"也纳入匹配键。
- **【面试怎么讲】**：一个"用字典推导式构造查找表时，选错了 key 的粒度"的真实案例——`rule_id` 回答的是"哪条规则"，不是"哪条结果"，这个混淆在数据量小、每条规则只命中一次的测试场景下完全不会暴露，只有在"同一条规则命中多个条款"这个真实会发生的场景下才会触发静默的数据丢失，这也是为什么它能在只读审计阶段才第一次被发现——此前的测试覆盖（`tests/` 目录在修复前没有任何 `risk_diff` 测试）从未构造过这种多命中场景。修复的关键不是"加个判断"，而是重新定义"两条结果算不算同一条"这个匹配语义本身。
- **【是否已解决】**：是。已通过新增单元测试复现并验证修复，现有相关测试与全仓库语法检查均通过；`fastapi`/`chromadb` 等依赖该功能的端到端 HTTP 层验证（如果未来给 `DiffApplicationService.risk_diff` 补充基于真实 `ContractManager` 数据的集成测试）本沙箱无法执行，留给有真实依赖的环境。

---

## P-27 `probation_salary` 百分比正则遗漏"零"导致 0% 试用期工资漏检

- **【问题】**：`rules/probation_salary.py::_PERCENT_RE` 用来匹配中文百分比数字的字符类是 `[一二三四五六七八九十百]`，不包含"零"；全角百分号 `％` 也没有被接受，正则硬编码只认半角 `%`。
- **【现象】**：这是在为端到端评估体系搭建 50 份评估合同样本后，`evaluation/diagnostics.py::experiment6_rule_layer_check()` 真实运行 `rules.RuleChecker` 时发现的，不是凭空猜测的——样本 `clear_risk_06` 的条款原文是"试用期工资为正式工资标准的**百分之零**"（0%，比任何法定下限都低，理应是最明显的风险），但规则没有产出任何结果，在诊断报告里表现为一条真实漏检。
- **【最初怀疑】**：无——拿到具体样本和具体漏检记录后直接去读 `_PERCENT_RE` 的字符类，一次定位。
- **【定位过程】**：用 `_extract_percent()` 对 `clear_risk_06` 的条款原文手动跑一遍，确认 `_PERCENT_RE.search()` 直接返回 `None`；对照字符类 `[一二三四五六七八九十百]` 逐字核对，确认"零"确实不在其中，而 `_cn_percent_to_int()` 里恰恰已经有 `_CN_DIGIT = {"零": 0, ...}` 这个映射——也就是说数值转换逻辑本来就支持"零"，只是正则在更早的匹配阶段就把它过滤掉了，根本没机会走到转换这一步。
- **【真正根因】**：`_PERCENT_RE` 的字符类是对着"一到十、百"这类常见百分比数字手写的，编写时没有把"零"当作一个会在"百分之 X"这个固定搭配里出现的数字对待（可能是惯性觉得"百分之零"不是常见表达），属于枚举字符类时遗漏了一个合法取值，不是算法逻辑错误。全角 `％` 同理：当时只按半角 `%` 写的测试用例覆盖，没人验证过全角写法。
- **【解决方案】**：把字符类从 `[一二三四五六七八九十百]` 改成 `[零一二三四五六七八九十百]`，并把百分号从 `%` 改成 `[%％]` 同时接受半角全角——两处都是在现有正则上加一个字符类成员，不改变整体匹配结构，也不新增捕获组或分支。
- **【为什么这样解决】**：`_cn_percent_to_int()` 已经原生支持"零"→0 的转换，不需要改转换逻辑；问题纯粹在"正则匹配阶段有没有机会把'零'这个字符捕获进来"，所以修复范围严格限定在正则本身，不触碰下游的比较逻辑（`percent >= MINIMUM_PERCENT`），避免了"为了修一个漏检顺手改了判断阈值"这类范围扩大。
- **【验证结果】**：先在**不改动源码**的情况下给 `tests/test_rules_probation_salary.py` 新增 7 个测试（3 个复现漏检的 `test_detects_*`，4 个边界/防误报测试），跑一遍确认旧实现下 `test_detects_cn_zero_percent`、`test_detects_fullwidth_percent_sign_zero`、`test_detects_fullwidth_percent_sign_below_80` 三个按预期失败（半角 `0%` 本来就能识别，没有失败——说明问题确实只在"零"和全角符号这两点，不是更大范围的回归）；修复后 16/16 全部通过。修复前后用 `scripts/run_eval_samples.py` 跑同一次 50 份样本的规则层诊断（实验6）对比：`missed_count` 从 3 降到 2（`clear_risk_06` 不再漏检），`false_positive_count` 不受影响（本条修复不涉及误报），`recall` 从 0.8235 升到 0.8824；同时跑了 `test_rules_checker.py`（5/5）、`test_rules_merge.py`（7/7）、`test_rules_probation_duration.py`（16/16，含 P-28 的修复）确认无回归。
- **【工程经验】**：手写的正则字符类本质上是"枚举法"，枚举法最容易漏的不是罕见值，而是"写的人下意识认为不会出现"的那个值——"零"在数学上和"一到九十九"没有任何特殊性，但在"试用期工资百分比"这个业务语境下，"0%"恰恰是最极端、最值得关注的违规取值，枚举字符类时如果只靠"常见表达"直觉去凑成员，很容易漏掉业务上最重要而口语上最少见的那一项。
- **【Agent / LangGraph 经验】**：与本项目的 LLM/LangGraph 调用链无关，是规则引擎（确定性正则规则）层面的问题；但这类"规则引擎正则覆盖不全"的 bug 有一个共同特征——单元测试覆盖的都是"典型值"（50%、65%、75%），没有人专门为"0 这个边界值"写过测试，直到真实评估数据集里出现了这个值才被暴露，提示规则类测试应该系统性地覆盖数值范围的两端（0 和 100），不能只覆盖中间的典型值。
- **【面试怎么讲】**：一个"字符类枚举遗漏合法值"的典型案例，特点是定位过程极短（一旦有具体失败样本，几分钟内就能从现象定位到正则本身），但发现过程值得讲——这个 bug 存在了很久都没被现有单元测试发现，是因为现有测试全部用"典型违规值"构造，直到搭建了程序化生成的评估样本集、覆盖到"0%"这个真实会在合同里出现但很少被当作测试用例写的边界值，才第一次被真实运行暴露，说明评估体系本身的价值不只是"量化准确率"，还包括"系统性地撞出手写测试覆盖不到的边界"。
- **【是否已解决】**：是。已通过新增回归测试复现并验证修复，`probation_salary` 相关测试、全部规则层测试、评估集诊断实验（实验6）均已重新运行确认指标提升且无回归。

---

## P-28 `probation_duration` 跨条款配对取"第一次出现的值"导致误报

- **【问题】**：`rules/probation_duration.py::check_probation_duration()` 对"合同期限"和"试用期月数"分别独立地在条款列表里取**各自第一次能提取到的值**，不检查两者是否来自同一条款、是否逻辑上应该配对。
- **【现象】**：同样是在评估体系的实验6真实运行中发现的——样本 `boundary_01` 里，第三条"试用期工资"条款原文为了测试 `probation_salary` 规则，恰好复述了一句"乙方试用期为3个月"（这只是给工资比例判断提供上下文，不是真正的合同期限条款），第四条"合同期限及试用期"才是真正描述期限（一年）和试用期（2个月）的条款。规则按条款顺序扫描，在第三条就抢先拿到了 `probation_months=3`，和后面第四条提取到的 `duration=12个月` 错误配对，算出"3个月 > 1年期合同2个月上限"，误判为违规——而条款四本身描述的"一年期+2个月试用期"完全合规。
- **【最初怀疑】**：无——拿到具体的误报样本（`boundary_01_c02`/`c03` 同时出现在 `false_positive` 列表里）后，直接对照 `check_probation_duration()` 的逐条款扫描循环，一次定位到"两个变量各自独立扫描、互不感知对方来自哪个条款"这个结构性问题。
- **【定位过程】**：手动对 `boundary_01` 的两条相关条款文本分别调用 `_extract_duration()`/`_extract_probation_months()`，确认第三条文本 `_extract_duration()` 返回 `None`（没有"合同期限"字样）、`_extract_probation_months()` 返回 `3`；第四条文本两者都能提取到（`12`个月 / `2`个月）。对照 `check_probation_duration()` 的循环顺序，确认"probation_months 在遍历到第三条时就已经被设为 3，不会再被第四条的 2 覆盖"，精确复现了错误配对的发生过程。
- **【真正根因】**：原实现把"提取期限"和"提取试用期月数"当成两个完全独立、互不relate的子任务，分别用"条款列表里第一次成功提取到的值"作为结果，隐含假设是"一份合同里只有一处会提到试用期月数、一处会提到合同期限，顺序扫描到的就是对的"。这个假设在"期限和试用期分别单独成条款、且全文只各提一次"的简单场景下是对的（现有测试全部是这种结构），但不符合真实合同常见写法——某些条款会在描述其他事项（比如试用期工资比例）时附带复述一次试用期月数作为上下文，一旦这类"旁白式提及"先于真正的期限条款出现，配对就会错位。
- **【解决方案】**：改成两步策略：第一步优先扫描是否存在**同一条款内**同时能提取出期限和试用期月数的情况（真实合同最常见的写法——期限和试用期写在同一条里），一旦找到就直接采用这对值并 `break`，不再看其它条款；只有当没有任何一条条款同时具备两者时，才退回原来的"分别取各自第一次出现的值"逐条款扫描（保留这个分支是为了不破坏现有全部测试用例的写法——它们都把期限和试用期分别写在两条独立的条款里）。
- **【为什么这样解决】**：没有改变规则 v1 本来就声明的"只用正则、覆盖范围有限"的设计定位，也没有引入更复杂的语义理解（比如判断哪句话是"真正描述期限的条款"、哪句话是"旁白式提及"）——"同条款内共同出现"是一个成本极低、误伤概率极低的启发式：真实合同里期限和试用期写在一起时，就是在描述同一件事，这种情况下的配对天然不存在歧义；而"不改动退回分支"保证了现有 16 个测试用例（都用两条独立条款）继续按原逻辑工作，不会因为新加的优先级判断而产生任何行为变化。这是在不扩大正则覆盖范围、不引入新的语义假设的前提下，用现有信息能做到的最小修复。
- **【验证结果】**：先在**不改动源码**的情况下给 `tests/test_rules_probation_duration.py` 新增 4 个测试，跑一遍确认旧实现下 `test_unrelated_earlier_probation_mention_is_not_paired_with_later_duration_clause`（精确复现 `boundary_01` 场景）和 `test_same_clause_pairing_still_detects_real_violation_despite_unrelated_distractor`（确认修复不会把真实违规也一起隐藏）两个按预期失败，另外两个边界测试（`test_no_single_clause_has_both_falls_back_to_cross_clause_scan` 确认退回分支语义不变、`test_multiple_same_clause_pairs_use_the_first_one_in_order` 确认多个同条款配对时行为确定）在旧实现下碰巧也通过（不是修复目标，是用来在修复后继续守住"没有被破坏"）。修复后 16/16 全部通过。修复前后用 `scripts/run_eval_samples.py` 跑同一次 50 份样本的规则层诊断（实验6）对比：`false_positive_count` 从 2 降到 0（`boundary_01` 的两条误报全部消失），`missed_count`/`known_limitation_gap_count` 不受影响（本条修复不涉及漏检），`precision` 从 0.875 升到 1.0；`recall` 同一轮里从 0.8235 升到 0.8824 是 P-27 修复贡献的，不是本条修复的直接效果（两条修复在同一次运行里合并对比，已在 `docs/EVAL_BASELINE.md`/`docs/EVAL_DIAGNOSTICS.md` 里分别说明各自贡献了哪部分变化）。
- **【工程经验】**："从一堆条款文本里分别独立提取两个相关的事实字段，再假设各自第一次提取到的值就是互相对应的一对"，本质上是一种隐式的"顺序耦合"假设——这类假设在测试数据恰好"干净"（每种信息只出现一次、且恰好分布在不同条款里）时完全不会暴露，必须有"同一类信息在多个不相关的位置被提及"的真实数据才能触发，这也是为什么它能在系统性生成的评估样本集里才第一次被真实撞出来，而不是在手写的单元测试里。
- **【Agent / LangGraph 经验】**：与本项目的 LLM/LangGraph 调用链无关；但这类"跨条款事实配对"的问题，在接下来如果要用 LLM 或更复杂的流程去关联多条款信息时会更容易隐藏（LLM 的"看起来合理"的回答会让错误配对更难被发现），提示跨条款的事实关联逻辑无论是规则还是未来的 LLM 流程，都应该优先用"同一条款内共同出现"这类结构性强信号，而不是"扫描顺序"这类偶然性强的信号。
- **【面试怎么讲】**：一个"用错误的隐式假设（扫描顺序=配对关系）简化了本该做关联判断的逻辑"的真实案例——表面上代码逻辑没有任何语法或类型错误，两个变量各自的提取逻辑都是对的，错的是"默认两个独立提取出来的值就应该配对在一起"这个没有被显式检验过的假设，而这个假设只有在"同一种信息在不相关的上下文里被重复提及"这个真实会发生的写作习惯下才会暴露，这也是为什么它直到接入系统性生成的 50 份评估样本、而不是靠人工构造的典型测试用例，才第一次被真实撞出来。
- **【是否已解决】**：是。已通过新增回归测试复现并验证修复，`probation_duration` 相关测试、全部规则层测试、评估集诊断实验（实验6）均已重新运行确认指标提升（误报清零）且无回归；`task_based` 合同类型的漏检（`clear_risk_10`/`mixed_08`）是另一个独立问题，本次修复未触及、也未受影响，详见 `docs/EVAL_DIAGNOSTICS.md`。

**【面试怎么讲】**：这是一次"把隐式状态变成显式状态"的典型重构——`COMPLETED` 状态被拆成"任务自己的终态（CONFIRMED/ABANDONED）"和"批次的 V2 生成结果（V2_GENERATED/V2_FAILED）"两个独立的状态机，背后的设计原则是"一个状态位只应该表达一件事"：旧的 `COMPLETED` 同时隐含"律师确认过"和"V2 生成成功过"两层含义，一旦需要支持"V2 生成失败后重试"，这两层含义就会打架（任务到底该不该退回非 COMPLETED？退回会不会丢失"律师确认过"这个事实？）。拆成两个独立状态机后，"确认"和"生成"互不影响，这也是为什么 `V2GenerationService.generate` 失败/重试全程不触碰 `ModificationTask.status`。

---

## P-29 `KnowledgeLoader.index()` 不做去重，导致重复加载知识库时数据翻倍

- **【问题】**：`rag/knowledge_loader.py::KnowledgeLoader.index()` 直接把 `Evidence` 列表转成 `texts`/`metadatas` 调 `ChromaKnowledgeBase.add_texts(texts, metadatas)`，不传 `ids`，等价于每次调用都让 Chroma 随机生成新 id——同一份知识库文件被重复加载（比如误操作跑了两次 `load_and_index_file`，或者某个未来的自动化流程在知识库更新后忘了先清空旧数据）就会把相同内容再写入一份，不是覆盖。
- **【现象】**：这不是在真实运行中报错发现的（本沙箱缺 `langchain_chroma`/`chromadb`，连这条代码路径都无法真实执行），而是在**任务二**（核验知识库与评估集）第六节要求的不变量"重复运行知识库加载不会造成重复数据"逐条核对现有自动化检查时发现的——`tests/test_rag_loader.py` 里原本就有一条测试 `test_reindexing_appends_duplicates_by_design`，名字和断言（`kb.count() == 6`，即加载两次、数量翻倍）已经如实记录了这个行为，只是当时把它定性为"已知、被接受的设计"，而不是"需要修的问题"。
- **【最初怀疑】**：无——测试名字和断言已经把问题说得很清楚，不需要猜测，只需要判断"这个已知行为现在是否还可以被接受"。
- **【定位过程】**：读 `KnowledgeLoader.index()` 的实现和它自己的旧 docstring（原话"注意：本方法不做去重，重复调用会把相同内容再写入一份"），确认这是设计决策，不是疏忽；再读 `ChromaKnowledgeBase.add_texts()`，确认它已经支持可选的 `ids` 参数（`self._store.add_texts(texts=texts, metadatas=metadatas, ids=ids)`），只是 `index()` 从来没有传过这个参数——说明修复所需的底层能力已经就位，缺的只是"算出一个确定性 id 并传进去"这一步。
- **【真正根因】**：最初设计 `index()` 时，知识库预期的使用场景是"一次性加载，之后很少变动"，所以没有考虑"同一批内容被重复写入"这个场景下应该有什么行为；而本次任务二明确把"重复加载不产生重复数据"列为必须满足的不变量，和当时的设计假设直接冲突。
- **【解决方案】**：新增 `KnowledgeLoader._evidence_id(evidence)`，最初对 `(source, article, content)` 三元组算 sha256 摘要作为确定性 id（**2026-10-10 第二轮本地实测后扩展为 `(source, article, part, content)` 四元组，见下方第 5 点**）；`index()` 改为对每个 `Evidence` 算出 id 后，以 `ids=` 显式传给 `ChromaKnowledgeBase.add_texts()`，**并在传给 Chroma 之前按 id 做批内去重（同样见第 5 点）**。
- **【为什么这样解决】**：先查证了 `langchain_chroma.Chroma.add_texts()` 在提供 `ids` 时，三条写入路径（有 metadata/无 metadata/完全没有 metadata）内部统一调用的是 `self._collection.upsert(...)`，不是 `self._collection.add(...)`（已对照 `langchain-ai/langchain` 仓库 `libs/partners/chroma/langchain_chroma/vectorstores.py` 的 `Chroma.add_texts` 源码确认，核验日期 2026-10-10）——chromadb 的 `upsert` 对已存在的 id 是覆盖写入，这意味着"内容相同 → id 相同 → 第二次调用覆盖第一次"是能从底层行为推出来的结论，不是假设；选用内容哈希而不是随机 id 或序号，是因为哈希天然满足"相同内容必须产出相同 id、不同内容必须产出不同 id"这两个幂等性要件，不需要额外维护一个"内容到 id"的映射表。
- **【验证结果】**：**这里必须诚实说明一个局限**——本沙箱没有 `langchain_chroma`/`chromadb`，装不上（无网络）。分两步验证：
  1. 纯 Python 层面（不需要任何第三方库）：`tests/test_rag_loader.py` 新增的 `test_evidence_id_is_deterministic_and_content_sensitive` 确认了 `_evidence_id()` 对相同内容产出相同 id、对相差一个字的内容产出不同 id；原来的 `test_reindexing_appends_duplicates_by_design`（断言 `kb.count() == 6`）改名为 `test_reindexing_is_idempotent_and_does_not_duplicate`，断言改为 `kb.count() == 3`。
  2. **2026-10-10（收到用户质疑后补做）**：用户指出"旧测试仍通过"这个说法后，重新核对了一遍当前文件——确认生产代码和测试文件都已经是修复后的状态（旧测试名已不存在）。为了不只停留在"代码看起来改了"，额外写了一个只在本次排查里用的沙箱替身跑法（`scratchpad/run_rag_loader_tests.py` + `scratchpad/fake_libs/`，不在项目仓库里，不是正式交付物）：给 `langchain_chroma`/`langchain_text_splitters`/`langchain_huggingface` 写最小替身模块，让 `rag/database.py`、`rag/knowledge_loader.py`、`tests/test_rag_loader.py`、`tests/_rag_fakes.py` 这些**一个字没改**的项目源码真的被 import、真的被执行；替身里 `Chroma.add_texts(ids=...)` 的行为严格按照"同 id 覆盖、不同 id 新增"实现（即真实 chromadb `upsert` 的语义，和上面查证的源码结论一致，不是另编一套假设）。真实跑出来的结果：**13 passed, 0 failed, 1 skipped**——`test_reindexing_is_idempotent_and_does_not_duplicate` 在这个替身环境下确认 `kb.count() == 3`（不是 6）；唯一跳过的是 `test_oversized_article_is_split_with_part_metadata`，因为它依赖 `RecursiveCharacterTextSplitter` 的精确切分算法，替身没有尝试还原这部分（没有真实库在手，硬写等于编造），明确标记为 SKIP，不是让它"看起来通过"。
  这个替身跑法比"完全没验证过"强，但**仍然不等于**用真实 chromadb 跑过一遍——它只能证明"按照查证到的 upsert 语义，这段逻辑的行为是对的"，不能排除真实 chromadb/langchain_chroma 版本差异带来的意外行为。**仍然建议、也仍然需要**在装好完整依赖的本地环境里跑一遍真实的 `pytest tests/test_rag_loader.py -v` 做最终确认，这一点没有变化。
  3. **2026-10-10（用户第二次复核，补齐边界场景和迁移风险）**：用户进一步指出两类当时没覆盖到的情况——(a) 哈希 id 只把 `content` 纳入计算够不够、万一不同来源/条号刚好有相同文字会不会被错误覆盖；(b) 切分边界变化（比如以后调整 `chunk_size`）导致旧的 part 失效后，upsert 能不能顺带清理掉它们。核对后发现 (a) 其实原实现已经做对了（`_evidence_id()` 一直是对 `(source, article, content)` 三元组一起算哈希，不是只对 `content`），但**从来没有专门测试**验证过这件事；(b) 则是一个真实存在、之前只在文档里口头提过、没有测试钉住的限制——upsert 只能覆盖"这次写入里出现的 id"，没有能力感知"哪些旧 id 这次没有再出现、应该被认为是失效的"，所以切分边界一变，旧的 part 会变成库里永久的孤儿记录，不会自动清理。新增 4 个测试覆盖这两类场景：`test_evidence_id_differs_by_source_even_with_same_content`、`test_evidence_id_differs_by_article_even_with_same_content_and_source`（确认 (a) 原来就是对的）、`test_index_called_directly_twice_with_same_evidences_list_does_not_duplicate`（把幂等性验证从"经文件 I/O 间接测"收紧到"直接测 `index()` 本身"）、`test_changing_chunk_boundaries_leaves_orphaned_old_chunks_unless_reset`（**用测试显式钉住 (b) 这个限制**，并确认 `kb.reset()` 是清理孤儿记录的正确方式）。用同一套沙箱替身跑法重新跑一遍 `tests/test_rag_loader.py`：**16 passed, 0 failed, 2 skipped**——新增的 3 个纯逻辑测试（不涉及真实切分算法的那 3 个）全部真实通过；第 4 个（`test_changing_chunk_boundaries_...`）和原来的 `test_oversized_article_is_split_with_part_metadata` 一样，因为依赖真实 `RecursiveCharacterTextSplitter` 的精确切分算法，替身没有尝试还原，明确标记 SKIP，必须在本地真实环境里确认。
  4. 另外针对 (b) 暴露出的真实运维风险——`scripts/build_knowledge_base.py` 原来的默认行为是"检测到不是 `--append` 就直接 `kb.reset()`"，这是一次**不可逆的真删除**（chromadb 的 `delete_collection`，已对照源码确认：删除后 collection 对象本身在重新创建前不可用），却完全没有提示、没有备份、没有确认。补了一个 `_confirm_destructive_step()`：在真正执行 reset/append 之前检测 `kb.count()`，有数据就打印清楚的风险提示（reset 模式还会先把整个 `persist_directory` 复制到带时间戳的备份目录），除非传了 `--yes` 否则要求终端输入 `yes` 才继续。这个函数本身用同一套沙箱替身手动跑过一遍（备份目录真的被创建、内容真的被完整复制、`append` 模式确认不会误触发备份），不是只检查过语法。
  5. **2026-10-10（用户在本地真实 Windows 环境跑 `pytest` 发现的新问题，不是沙箱里发现的）**：用户按上面第 2-4 点的修复更新本地文件后，本地真实运行 `pytest tests/test_rag_loader.py -v` 报告 `17 passed, 1 failed`——失败的是 `test_changing_chunk_boundaries_leaves_orphaned_old_chunks_unless_reset`，真实报错是 `chromadb.errors.DuplicateIDError: Expected IDs to be unique`。**根因**：这条测试用的超长法条是同一句话连续重复 20 次构造出来的（`"第一条 " + "违反规章制度的，用人单位可以解除劳动合同。" * 20`），真实 `RecursiveCharacterTextSplitter` 按句号/字符切分这种高度重复的文本时，切出来的多个 `part` 会出现**逐字相同**的内容；而 `_evidence_id()` 当时只对 `(source, article, content)` 算哈希，不看 `part`，于是同一次 `index()` 调用里出现了两个哈希完全相同的 id，被 chromadb 判定为"单次调用内部 id 不能重复"而报错——这和"跨次调用 upsert 覆盖同 id"是完全不同的两件事，不是幂等机制本身的缺陷，是 `_evidence_id()` 原来"同一批不会有内容相同的片段"这个假设被真实数据打破了。**修复**：把 `metadata.get("part")` 纳入 `_evidence_id()` 的哈希输入（没有被二次切分的 Evidence 取不到 `part`，退化为空字符串，等价于原来的行为，不影响已有场景的 id 值）；同时在 `index()` 里对要写入的 `ids`/`texts`/`metadatas` 按 id 做批内去重（保留第一次出现的那条），用来处理另一种更边缘的情况——调用方本身往同一次 `index()` 传入了两条 `(source, article, part, content)` 完全相同的 `Evidence`（不是切分算法产生的，而是调用方自己重复传入）；去重而不是报错或改用随机 id，是因为这种情况下两条记录本来就代表同一件事，去重不丢信息，改用随机 id 反而会重新引入"相同内容每次拿到不同 id、upsert 认不出是同一条"的旧问题。新增两个测试：`test_evidence_id_differs_by_part_even_with_identical_content`（直接测 `_evidence_id()` 对 `part` 的敏感性，以及两个内容相同、`part` 不同的 Evidence 一起 `index()` 不会互相覆盖、不会报错）、`test_index_deduplicates_literal_duplicate_evidences_within_one_call`（测批内去重的处理方式，以及去重之后幂等性没有被破坏）。用同一套沙箱替身跑法重新跑一遍：**18 passed, 0 failed, 2 skipped**——两个新测试都真实通过；仍然跳过的两个（`test_oversized_article_is_split_with_part_metadata`、`test_changing_chunk_boundaries_leaves_orphaned_old_chunks_unless_reset`）都依赖真实 `RecursiveCharacterTextSplitter` 的精确切分算法，本沙箱装不上这个库，**本次修复没有、也不可能在沙箱里真实复现并确认这条曾经报错的测试现在会通过**，必须由用户在本地真实环境重新运行 `pytest tests/test_rag_loader.py -v` 做最终确认——这一点和之前几轮一样，如实标注，不冒充已经验证过。**本轮刻意没有做、也不应该做的事**：没有改动"切分边界变化后旧 part 不会被自动清理"这个已知限制（`test_changing_chunk_boundaries_...` 的核心断言 `count_after_second > len(second_evidences)` 不变），这是 upsert 天然做不到的事，留作已知限制，不是本轮修复范围；也没有引入随机 id、没有清空或重建任何现有知识库数据。
- **【工程经验】**："不做某件事"和"做不到某件事"是两种不同的状态，必须分别对待：这里原来的"不去重"是前一种（技术上能做，当时选择不做），一旦需求变化（任务二提出新的不变量要求），只需要补上缺的那一步（算 id、传 ids 参数），不需要推翻设计；但如果是后一种（比如底层存储压根不支持按 id upsert），那就要先确认底层能力，而不是想当然地加一行代码就以为解决了——这里刚好是先去查了 `Chroma.add_texts` 的真实实现确认了 upsert 语义存在，才敢下"这样改能生效"的结论。
- **【Agent / LangGraph 经验】**：这类"写入操作是否幂等"的问题，在接下来如果有自动化流程（比如知识库文件改了之后自动触发重新索引）会变得更重要——没有幂等性保证的写入操作一旦被自动化、被多次无意触发（重试、并发、流程重复执行），错误会被放大成数据质量问题而不只是性能浪费，所以任何会被自动化重复调用的写入路径，都应该默认要求幂等，而不是等出问题了再补。
- **【面试怎么讲】**：一个"用内容哈希让写入操作幂等"的标准模式，特点是问题本身很好理解（重复写入就会重复），但这次的重点在于"没有臆造一个解决方案"——没有凭感觉说"加个 ids 应该就行了"，而是先去查证了具体调用的 Chroma 方法到底是 `add` 还是 `upsert`、两者在遇到重复 id 时的真实语义差异，确认了 upsert 本身的覆盖行为之后才动手改；同样重要的是老实承认"这个结论本身在当前环境里验证不了端到端的那一半"，而不是因为单元测试跑通了就宣称问题已经彻底解决。
- **【是否已解决】**：**部分，比最初记录时更有把握，但仍不是最终确认**。代码修复已完成、有查证依据（langchain_chroma 源码确认 upsert 语义，以及 `delete_collection` 删除后 collection 不可用、必须重开实例或 `reset_collection` 的真实行为）；纯 Python 层面（id 生成的确定性，包括按 source/article/part 区分的边界场景、批内重复去重）和"用语义忠实的沙箱替身跑一遍真实、未修改的生产代码+测试代码"两层都已经做了，最新一轮（第 5 点，加入 `part` + 批内去重后）结果是 **18 passed/0 failed/2 skipped**；运维层面补上了 `scripts/build_knowledge_base.py` 的检测/提示/备份/确认机制，并手动验证过备份确实会发生、内容确实完整。但"重复加载知识库在真实 Chroma 环境下确实不产生重复数据"、"旧版切分边界产生的孤儿记录在真实环境下确实不会被 upsert 自动清理"、"`test_changing_chunk_boundaries_leaves_orphaned_old_chunks_unless_reset` 这条之前在用户本地真实报过 `DuplicateIDError` 的测试，加了 `part` 之后确实能在真实 chromadb+真实切分算法下通过"这三个最终结论，受限于本沙箱没有真实 `langchain_chroma`/`chromadb`/`langchain_text_splitters`，**仍然必须在本地环境运行 `pytest tests/test_rag_loader.py -v` 才能最终确认**，本次任务如实标注这一点，不冒充已经用真实 chromadb 端到端验证过。本地如果已经有用旧版代码构建过的 `data/chroma`，第一次切到新版代码重建前，务必让 `scripts/build_knowledge_base.py` 的安全提示走完一遍（或自己提前手动备份），不要跳过。
