# 劳动合同智能审查系统

输入一份劳动合同文本，系统把它切分成条款，逐条用「RAG 检索法律依据 + LLM 判断」审查，再用确定性规则补充检查 LLM 结构上看不到的问题，最后合并成一份统一的审查结果。

- **当前阶段**：核心审查链路已完成，并在真实环境（真实 BGE-M3 + Chroma + DeepSeek + LangGraph）验证通过。
- **还没有的**：HTTP API、结果格式化输出、PDF / DOCX / 图片解析（详见[已知限制](#18-已知限制)）。
- **定位说明**：严格说这是一个 **LLM 增强的 workflow**（拓扑固定，LLM 只在其中一个节点里做判断），不是由 LLM 自主决定下一步动作的 Agent。
- **免责**：系统输出仅供参考，不构成法律意见。

> 图例：✅ 已在真实环境验证　🧪 仅自动化测试覆盖　📝 未实现　⚠️ 已知限制

## 文档索引

| 文档 | 内容 |
|---|---|
| [docs/DEVLOG.md](docs/DEVLOG.md) | 开发日志：各模块的目的、设计、问题、取舍，以及真实验证记录 |
| [docs/PITFALLS.md](docs/PITFALLS.md) | 问题 / 踩坑知识库：现象、原因、定位、解决、如何避免 |
| [docs/KNOWLEDGE_TREE.md](docs/KNOWLEDGE_TREE.md) | 项目涉及的知识树与概念速查，标注验证状态 |
| [docs/INTERVIEW.md](docs/INTERVIEW.md) | 面试问题、回答思路，以及"我应该能解释什么"清单 |
| [tests/README.md](tests/README.md) | 测试分层说明与写测试时踩过的坑 |

---

## 1. 项目简介

系统处理一份劳动合同的完整流程是：

1. 登记合同文件，得到 `contract_id`，原文件落盘保存；
2. 解析成纯文本，按"第X条 / 款"切成结构化的 `Clause`；
3. **LLM 分支**：逐条款生成检索 query → 从法律知识库检索 `Evidence` → 拼 Prompt → 调用 DeepSeek → 得到 `ReviewResult`；
4. **规则分支**：`RuleChecker` 对整份合同的条款做确定性检查（目前 2 条规则）；
5. 两个分支**并行**执行，之后**汇合**，得到最终的 `ReviewResult` 列表；
6. 用最终结果构造 `ReviewReport`（风险分布、整体风险等级、失败条款）。

## 2. 项目解决的问题

- 劳动合同审查耗时，且依赖对《劳动合同法》的熟悉程度。系统给出「风险点 + 法律依据 + 修改建议」。
- **单条款审查有结构性盲区**：LLM 一次只看一个条款，看不到其他条款。例如"试用期三个月"是否违法取决于"合同期限"，而合同期限写在另一条里。真实验证中 LLM 自己写出了"现有信息未提供合同期限，无法判断"。这类问题由规则分支补上（见[RuleChecker 设计](#10-rulechecker-设计)）。
- **LLM 判断不保证可复现**：`temperature=0` 下，同一份合同两次真实调用，边界条款的风险等级出现过 `low` ↔ `none` 的翻转。规则是系统里唯一能给出可复现结论的部分。

## 3. 整体架构

```
合同文件 (.txt)
   │  ContractManager.create_contract  →  contract_id，落盘 data/contracts/<id>/
   ▼
┌───────────────────────── LangGraph（review/pipeline.py）─────────────────────────┐
│                                                                                 │
│  Contract Loading      parse_contract → split_contract → clauses                │
│         │                                                                       │
│    ┌────┴───────────────────────┐                                               │
│    ▼                            ▼                                               │
│  LLM Review（逐条）          Rule Check（整份）                                   │
│   generate_query               RuleChecker.check(clauses)                       │
│   → RAG 检索 Evidence             ├ probation_salary                            │
│   → Prompt → DeepSeek             └ probation_duration                          │
│   → ReviewResult(source=llm)   → ReviewResult(source=rule)                      │
│    │  失败条款 → failed_clauses     │                                           │
│    └────────────┬────────────────┘                                              │
│                 ▼                                                               │
│             Merge   llm_results + rule_results（拼接，不覆盖、不去重）            │
│                 ▼                                                               │
│         Report Assembly   构造 ReviewReport（构造后 State 不保存）                │
└─────────────────────────────────────────────────────────────────────────────────┘
```

**模块依赖**（按 AST 扫描的真实 import 关系；`schemas` 是唯一的基础层，它不依赖任何模块）

```
schemas   ◄── contract, clause/clause_splitter, rag, llm/prompts, rules, review
parser/document_parser      不依赖任何项目模块

review/reviewer  ──► rag, llm, schemas
config（只放默认值常量，自身零依赖） ◄── contract, rag, llm/client, clause/clause_splitter, review/reviewer

过渡桥接文件（连接 ContractManager 与解析 / 切分）：
  parser/contract_parser.py               ──► contract
  clause/contract_clause_splitter.py      ──► contract, schemas

review/pipeline  ──► contract, parser, clause, rules, review/reviewer, schemas
                     ↑ 唯一"知道所有模块"的文件
```

`contract` / `parser` / `clause` / `rag` / `llm` / `rules` 这几个功能模块之间互相独立（两个桥接文件是明确标注的过渡例外），只依赖 `schemas` 和 `config` 的默认值。`review/reviewer.py` 组合 `rag` 与 `llm`，但不依赖 `contract` / `parser` / `clause`——`Clause` 由外部传入。

## 4. 技术栈

| 类别 | 使用 |
|---|---|
| 语言 / 数据模型 | Python，Pydantic v2 |
| 流程编排 | LangGraph（`StateGraph`，TypedDict State） |
| LangChain 子包 | `langchain-core`、`langchain-text-splitters`、`langchain-chroma`、`langchain-huggingface` |
| 向量库 | Chroma（本地持久化） |
| Embedding | `BAAI/bge-m3`（通过 `sentence-transformers` 本地加载，只用稠密向量，向量归一化） |
| LLM | DeepSeek，通过 `openai` SDK 的 OpenAI 兼容接口，默认模型 `deepseek-flash` |
| 配置 | `python-dotenv`（密钥）、`config/settings.py`（默认值） |
| 测试 | `pytest` |

## 5. 项目目录结构

```
labor_contract_review/
├── README.md
├── requirements.txt          依赖（刻意不锁版本）
├── pytest.ini                pytest 配置：testpaths、pythonpath、marker 注册
├── .env.example              环境变量模板
├── config/
│   └── settings.py           跨模块共享的默认值常量（路径、模型名、chunk、top_k），不含密钥
├── schemas/                  全项目数据契约（Clause / Evidence / Contract / ReviewResult / ReviewReport）
├── contract/manager.py       合同文件的本地存储（文件系统，无数据库）
├── parser/
│   ├── document_parser.py    文档 → 纯文本（目前只实现 .txt）
│   └── contract_parser.py    过渡桥接：ContractManager ↔ DocumentParser
├── clause/
│   ├── clause_splitter.py    全文 → Clause 列表（正则结构切分 + 超长条款二次切分）
│   └── contract_clause_splitter.py   过渡桥接：ContractManager ↔ ClauseSplitter
├── rag/
│   ├── embedding.py          构造 BGE-M3 embedding
│   ├── database.py           Chroma 连接与基础读写（唯一直接接触 Chroma 的文件）
│   ├── loader.py             法律文本 → 按条切分 → Evidence → 写入 Chroma
│   └── retrieval.py          query → 检索 → Evidence 列表
├── llm/
│   ├── client.py             OpenAI 兼容的 LLM 连接层（含 DeepSeek 构造函数）
│   └── prompts.py            审查 Prompt 模板
├── review/
│   ├── reviewer.py           单条款审查（query → RAG → Prompt → LLM → ReviewResult）
│   ├── schemas.py            LLMReviewOutput：要求 LLM 返回的 JSON 结构
│   └── pipeline.py           LangGraph 编排（State + 5 个 Node + 7 条 Edge）
├── rules/
│   ├── checker.py            RuleChecker：规则补充检查的唯一入口
│   ├── probation_salary.py   规则：试用期工资低于 80%
│   ├── probation_duration.py 规则：试用期超过第十九条上限
│   └── merge.py              merge_review_results：拼接 LLM 结果与规则结果
├── api/  output/             📝 空包，尚未实现
├── data/
│   ├── knowledge/劳动合同法.txt   法律知识库原文（《劳动合同法》14 条节选）
│   ├── chroma/               向量库（运行时生成，已 gitignore）
│   └── contracts/            合同数据（运行时生成，已 gitignore）
├── scripts/                  真实环境脚本（见 15）
└── tests/                    258 个测试（见 16）
```

## 6. 核心执行流程

1. `ContractManager.create_contract(path)`：保存原文件、计算 sha256、生成 `contract_id`（uuid4 十六进制），状态 `uploaded`。
2. `parse_contract`：`DocumentParser` 把文件解析成文本，`save_parsed_text`，状态 `parsed`。**解析不改动原文**（不 strip、不换行规范化），保证后续偏移量成立。
3. `split_contract`：`ClauseSplitter.split` 切成 `Clause`，`save_clauses`，状态 `split`。不变量：`full_text[start_char:end_char] == original_text`。
4. **LLM 分支**（逐条）：`generate_query` → `LegalKnowledgeRetriever.search_legal_knowledge` → `build_review_messages` → DeepSeek（JSON 模式）→ 校验为 `LLMReviewOutput` → 补上 `clause_id`、`source=llm` 得到 `ReviewResult`。某条失败（`ReviewError`）记入 `failed_clauses`，继续处理其他条款。
5. **规则分支**：`RuleChecker.check(clauses)` 依次执行已注册的规则，只返回发现的问题。
6. **汇合**：`merge_review_results(llm_results, rule_results)` = 两个列表拼接。
7. **报告**：`ReviewReport(contract_id, results, failed_clauses, versions)`。

## 7. LangGraph 设计

**5 个 Node**（`review/pipeline.py`，每个只是对一个已验证业务函数的薄封装）

| Node | 读 State | 写 State | 调用的真实函数 | 异常 |
|---|---|---|---|---|
| `contract_loading` | `contract_id` | `clauses` | `parse_contract` → `split_contract` | 直接抛出，终止整图 |
| `llm_review` | `clauses` | `llm_results`、`failed_clauses` | 循环调用 `ClauseReviewer.review` | 只捕获 `ReviewError`（逐条），其余抛出 |
| `rule_check` | `clauses` | `rule_results` | `RuleChecker.check` | 直接抛出 |
| `merge` | `llm_results`、`rule_results` | `final_results` | `merge_review_results` | 直接抛出 |
| `report_assembly` | `contract_id`、`final_results`、`failed_clauses` | 无 | `ReviewReport(...)` | 直接抛出 |

**7 条 Edge，全部是无条件边，没有 `add_conditional_edges`：**

```
START → contract_loading
contract_loading → llm_review        ┐ 并行扇出
contract_loading → rule_check        ┘
llm_review → merge                   ┐ 汇合（框架等两个上游都完成）
rule_check → merge                   ┘
merge → report_assembly → END
```

**设计要点**

- **并行的依据**：`RuleChecker.check(clauses)` 的签名里没有 `llm_results`，两个分支没有数据依赖。
- **不需要 reducer**：每个 State 字段只有一个节点写入。若两个并行节点写同一个 key，LangGraph 需要为该字段声明如何合并，否则会拒绝。
- **基础设施不进 State**：`ContractManager` / `ClauseReviewer` / `RuleChecker` 通过 `build_graph(...)` 的参数注入到节点闭包里。
- **异常策略是已确认的架构决策**：除了 LLM 单条款失败，任何节点异常都直接终止整张图，不做统一 error state、条件分支或重试。
- **`ReviewReport` 在 `report_assembly` 里构造后不写回 State**（State 没有 `report` 字段）。调用方用最终 State 里的 `contract_id` / `final_results` / `failed_clauses` 自行构造，构造是纯函数、可重复。

## 8. State 设计

```python
class ReviewGraphState(TypedDict):
    contract_id: str                      # 引用：原文件与解析文本已由 ContractManager 落盘
    clauses: list[Clause]                 # 数据：llm_review 与 rule_check 都直接把它当输入
    llm_results: list[ReviewResult]       # 只有 llm_review 写
    rule_results: list[ReviewResult]      # 只有 rule_check 写
    final_results: list[ReviewResult]     # 只有 merge 写
    failed_clauses: list[FailedClause]    # 只有 llm_review 写（复用 schemas 里的类型）
```

**进不进 State 的判断标准**：这一步产出的东西，是否有下一个节点把它当**直接输入**。

| 不进 State | 原因 |
|---|---|
| `original_file`、`parsed_text` | 解析、切分之后没有任何节点再用；已由 `ContractManager` 落盘，需要时凭 `contract_id` 取 |
| `Evidence` | 只是 `ClauseReviewer.review()` 内部的局部变量，函数返回类型是 `ReviewResult`；且当前 `ReviewResult` 没有字段能装它 |
| LLM client / embedder / Chroma / `ContractManager` / `RuleChecker` | 基础设施实例，不是数据，也通常不可序列化 |
| `report`、`error`、`versions` | 明确决定不加（见已知限制） |

## 9. RAG 设计

**知识库构建**（`scripts/build_knowledge_base.py`）

```
data/knowledge/*.txt → KnowledgeLoader（按"第X条"切分，一条法条一个 Evidence）
  → Chroma.add_texts（内部自动调用 BGE-M3 生成向量）→ data/chroma/
```

**检索**：`query → Chroma 内部 embed_query → 相似度检索 → Document + distance → Evidence`，`distance` 放在 `Evidence.metadata["score"]`，越小越相似（具体度量取决于 Chroma 配置，项目不做二次加工）。

**设计决策**

- `rag` 完全独立，不依赖 `contract` / `parser` / `clause`，只依赖 `schemas` 与 `config`。
- **按条切分**：法律条文天然是逐条罗列的，一条一个 chunk，检索出来的依据是完整、有条号的条文；只有超过 chunk 大小（500/50）的条文才二次切分。
- **Embedding 不是手动调用的步骤**：Chroma 在 `add_texts` / `similarity_search` 内部调用构造时传入的 embedding 函数。
- BGE-M3 只用**稠密向量**，`normalize_embeddings=True`，`device` 默认 `cpu`。
- Chroma metadata 不接受 `None`，所以 `article` 为空时不写这个键。
- `KnowledgeLoader.index` **不去重**，重复导入会产生重复数据；`build_knowledge_base.py` 默认先 `reset()` 再写入，保证幂等。
- 知识库当前是**《劳动合同法》14 条节选**（第 1、2、3、17、19、20、21、23、24、29、30、33、34、35 条）。

## 10. RuleChecker 设计

**定位**：主线路（RAG + LLM）之后的**测试驱动漏检补丁层**，不是第二条独立审查线路，也不是通用规则引擎。规则只在真实测试反复发现某类问题被主线路漏掉或判断不稳时才新增。

**接口**：`RuleChecker().check(clauses: list[Clause]) -> list[ReviewResult]`。外部只依赖这一个入口，不需要知道内部有哪些规则。

**已注册的规则**

| rule_id | 检查什么 | 结果形态 |
|---|---|---|
| `probation_salary_below_80_percent` | 试用期工资写成"正式工资的百分之X / X%"且 X < 80（第二十条） | `clause_id` 指向该条款，`high` |
| `probation_duration_exceeds_legal_cap` | 试用期是否超过第十九条上限 | `clause_id=None`，`related_clause_ids=[合同期限条款, 试用期条款]`，`high` |

第十九条阶梯：合同期限 < 3 个月或"以完成一定工作任务为期限" → 不得约定试用期；3 个月 ≤ 期限 < 1 年 → ≤ 1 个月；1 年 ≤ 期限 < 3 年 → ≤ 2 个月；≥ 3 年或无固定期限 → ≤ 6 个月。

**约束**

- 规则**只在发现问题时返回结果**，没问题返回 `[]`，不返回"合规确认"。
- 每条规则**自己识别、自己提取、自己判断**，没有共享的事实抽取层（不存在 `ContractFacts`）。
- `RuleChecker` **不读 `llm_results`**，也不根据 LLM 是否"不确定"决定是否运行。
- 提取不到需要的信息（例如合同期限写成日期区间）就**跳过**，不猜测、不补默认值。
- ⚠️ 覆盖有限：`probation_salary` 只识别百分比，不识别绝对金额；期限和试用期的中文数字只识别一到十二；日期区间形式的合同期限不识别。

**如何新增一条规则**：① 真实测试确认存在稳定漏检；② 在 `rules/` 下新建文件，函数签名 `list[Clause] -> list[ReviewResult]`，`source=rule`、填 `rule_id`；③ 在 `RuleChecker.__init__` 的 `self.rules` 里注册；④ 补单元测试（含"没问题返回空列表"和"提取不到就跳过"）；⑤ 跑真实脚本验证。

## 11. LLM Review 设计

`ClauseReviewer.review(clause)`：

1. `generate_query`：只去掉"第X条"这个编号（以及 `1.`、`（一）` 这类款编号），**保留标题文字**。标题常是最精准的法律术语，正文常是同义改写（真实踩过坑，见 PITFALLS）。
2. 检索 `top_k`（默认 5）条 Evidence。
3. `build_review_messages`：系统提示要求只依据提供的法律依据、不得编造、依据不足要如实说明、只输出 JSON（`risk` / `risk_level` / `reason` / `legal_basis` / `suggestion`）。
4. `OpenAICompatibleClient.chat(messages, json_mode=True)`，`temperature` 默认 0。
5. 校验为 `LLMReviewOutput`（`risk` 必须与 `risk_level` 一致），再由代码补上 `clause_id`、`source=llm`。**这些字段不让模型自己填。**
6. 检索失败、LLM 调用失败、输出不是合法 JSON、JSON 不符合结构，统一抛 `ReviewError`（消息里带 `clause_id` 与原始输出），不做静默兜底。

**LLM 配置**：`base_url` 固定为 `https://api.deepseek.com`（在 `llm/client.py`）；`DEEPSEEK_API_KEY` 必填；`DEEPSEEK_MODEL` 可选，默认 `deepseek-flash`。

## 12. 最终结果结构

**`ReviewResult` 的粒度是「风险点」，不是「条款」**：一个条款可以对应多条结果，LLM 结果与规则结果都保留。

| 字段 | 含义 |
|---|---|
| `clause_id` | 对应的条款；跨条款问题或缺失类问题为 `None`（仅规则来源允许） |
| `related_clause_ids` | 跨条款问题涉及的其他条款 |
| `risk` / `risk_level` | `none` / `low` / `medium` / `high`；`risk` 必须与 `risk_level` 一致（`none` ⇔ `False`） |
| `reason` / `legal_basis` / `suggestion` | 判断理由 / 法律依据（字符串列表） / 修改建议 |
| `source` / `rule_id` | `llm` 或 `rule`；规则来源必须有 `rule_id`，LLM 来源必须有 `clause_id` 且不能有 `rule_id` |

规则结果示例（来自真实 E2E 的规则输出）：

```json
{
  "clause_id": "clause_003",
  "related_clause_ids": [],
  "risk": true,
  "risk_level": "high",
  "reason": "条款约定试用期工资为正式工资标准的百分之50，低于《劳动合同法》第二十条规定的百分之80下限。",
  "legal_basis": ["《劳动合同法》第二十条"],
  "suggestion": "将试用期工资调整为不低于正式工资标准的百分之80。",
  "source": "rule",
  "rule_id": "probation_salary_below_80_percent"
}
```

跨条款规则结果：`clause_id` 为 `null`，`related_clause_ids` 为 `["clause_001", "clause_003"]`。

**`ReviewReport`**：`contract_id`、`generated_at`（带时区的 UTC）、`results`、`failed_clauses`、`versions`；`summary`（各风险等级的**结果数**）和 `overall_risk_level`（最高等级，无结果为 `none`）由 `results` 自动计算，不单独存储。

- ⚠️ 结果数 ≠ 条款数：5 个条款、5 条 LLM 结果 + 2 条规则结果 = 7 条，`summary` 统计的是这 7 条。
- ⚠️ 有条款审查失败时，它们不在 `results` 里；只看 `overall_risk_level` 可能低估风险，需同时检查 `failed_clauses`。

## 13. 如何安装

已验证环境：**Windows + PowerShell + venv，Python 3.13.12，pytest 9.1.1，LangGraph 1.2.12**。其他依赖的版本没有记录；`requirements.txt` **刻意不锁版本**，用上面的已验证环境作为复现参考。

```powershell
python -m venv venv
venv\Scripts\activate            # macOS / Linux: source venv/bin/activate
pip install -r requirements.txt
```

首次运行会从 HuggingFace 下载 BGE-M3 权重（约 2GB），需要联网。未设置 `HF_TOKEN` 时会看到"未认证请求"的警告，不影响使用。

## 14. 如何配置

**1. 密钥与模型（`.env`，已在 `.gitignore`，不会提交）**

```powershell
Copy-Item .env.example .env      # macOS / Linux: cp .env.example .env
```

```
DEEPSEEK_API_KEY=你的key          # 必填
DEEPSEEK_MODEL=                   # 可选；留空使用默认 deepseek-flash
```

DeepSeek 的模型命名变动比较频繁（旧的 `deepseek-chat` / `deepseek-reasoner` 已下线），请以官方文档当前列出的名称为准。**不要在 `DEEPSEEK_MODEL` 里留占位符**（真实踩过：填了 `DEEPSEEK`，请求被拒）。

**2. 默认值（`config/settings.py`，只有常量，不含密钥）**

| 常量 | 默认值 |
|---|---|
| `CONTRACTS_DIR` / `KNOWLEDGE_DIR` / `CHROMA_DIR` | `data/contracts` / `data/knowledge` / `data/chroma`（基于文件位置推导，不依赖当前工作目录） |
| `CHROMA_COLLECTION_NAME` | `legal_knowledge` |
| `EMBEDDING_MODEL_NAME` | `BAAI/bge-m3` |
| `LLM_MODEL_NAME` | `deepseek-flash` |
| `RETRIEVAL_TOP_K` | `5` |
| `CLAUSE_CHUNK_SIZE` / `CLAUSE_CHUNK_OVERLAP` | `500` / `50` |
| `KNOWLEDGE_CHUNK_SIZE` / `KNOWLEDGE_CHUNK_OVERLAP` | `500` / `50` |

各模块仍可通过构造函数参数覆盖默认值。注意：构造函数的默认参数在**函数定义时**求值，改了 `settings.py` 需要重启进程才会生效。

## 15. 如何运行

```powershell
# 第一步：初始化知识库（只需一次；默认先清空 collection 再写入，重复运行不会产生重复数据）
python scripts/build_knowledge_base.py

# 第二步：完整 LangGraph 流程（真实 BGE-M3 + Chroma + DeepSeek，会消耗 token）
python scripts/verify_full_pipeline.py                     # 使用内置示例合同（5 个条款）
python scripts/verify_full_pipeline.py --file 我的合同.txt   # 审查自己的 .txt 合同
```

| 脚本 | 验证什么 |
|---|---|
| `verify_full_pipeline.py` | 完整 LangGraph 端到端 |
| `verify_review_pipeline.py` | 只验证单条款 LLM 审查（不经过 LangGraph） |
| `verify_rules_pipeline.py` | 只验证 RuleChecker + 合并（不经过 LangGraph；主线路部分仍调用真实 LLM） |
| `verify_rag_pipeline.py` | 只验证「Clause → query → 检索 → Evidence」（临时向量库，跑完删除） |
| `verify_real_retrieval.py` | 从已持久化的 `data/chroma` 用真实 BGE-M3 检索 |

这些脚本**始终使用真实依赖**：模型加载失败、知识库为空、缺 API Key，都只报告环境问题并退出，不会换成假实现。

**代码中调用**

```python
from contract import ContractManager
from llm import build_deepseek_client
from rag import ChromaKnowledgeBase, LegalKnowledgeRetriever, build_embedder
from review import ClauseReviewer
from review.pipeline import run_review
from rules import RuleChecker
from schemas import ReviewReport, ReviewVersions

manager = ContractManager()                            # 默认 data/contracts
contract = manager.create_contract("合同.txt")           # 目前只有 .txt 可以解析
kb = ChromaKnowledgeBase(build_embedder())             # 需要先运行 build_knowledge_base.py
reviewer = ClauseReviewer(LegalKnowledgeRetriever(kb), build_deepseek_client())

state = run_review(contract.contract_id, manager, reviewer, RuleChecker())
report = ReviewReport(
    contract_id=state["contract_id"],
    results=state["final_results"],
    failed_clauses=state["failed_clauses"],
    versions=ReviewVersions(),
)
```

## 16. 如何运行测试

```powershell
pytest                       # 全部自动化测试（不需要网络、API Key，不会下载模型）
pytest -v -rs
pytest -m unit               # 只跑单元测试
pytest -m "unit or module"   # 不含 LangGraph 流程测试
pytest -m graph -v           # 只跑 LangGraph 流程测试
```

| 层 | marker | 验证什么 | 外部服务 |
|---|---|---|---|
| 单元测试 | `unit` | 局部逻辑 | 全部 mock 或用假对象 |
| 模块测试 | `module` | 同一子系统内多个真实组件协作（真实 Chroma、真实文件系统） | embedding 用假向量 |
| LangGraph 流程测试 | `graph` | 拓扑与状态流转：并行、汇合、`failed_clauses`、异常向上抛出 | 只有 LLM 与检索用假对象，**LangGraph 是真实的** |
| 真实端到端 | 不在 pytest 里 | 真实系统链路 | **全部真实，不用 mock** |

- 分层由 `tests/conftest.py` 按文件名自动打标记；**新增测试文件必须在 `TEST_LAYERS` 里登记**，否则收集阶段报错。
- **marker 需要在 `pytest.ini` 里注册**，否则会出现 `PytestUnknownMarkWarning`。真实踩过一次：根因是本地的 `pytest.ini` 没有同步更新（交付的文件本来就是对的）。修改配置文件后，请确认本地文件确实被更新。
- PowerShell 里没有 `tail`，取输出最后一行用 `| Select-Object -Last 1`。
- 更多细节见 [tests/README.md](tests/README.md)。

## 17. 当前已验证能力

| 项目 | 结果 | 类型 |
|---|---|---|
| 自动化测试 | **258 passed**（Python 3.13.12 / pytest 9.1.1 / LangGraph 1.2.12） | ✅ 真实环境 |
| Graph 测试 | `pytest -m graph`：**12 passed，246 deselected**（真实 LangGraph 上，覆盖并行、汇合不覆盖、`failed_clauses`、Contract Loading 与 Rule Check 抛错时异常向上抛出） | ✅ 真实环境 |
| 真实检索（BGE-M3 + 持久化 Chroma，知识库 14 条） | "试用期工资不得低于多少" → 第二十条居首（distance 0.4469）；"竞业限制期限" → 第二十四条居首（0.4434）；"劳动合同必备条款有哪些" → 第十七条居首（0.4782） | ✅ 真实环境 |
| 单条款 LLM 审查（三个案例） | 试用期工资 50% → `high`，依据第二十条、第十九条；正常工时条款 → 依据不足时如实说明，未编造；竞业限制三年且无补偿 → `high`，依据第二十四条、第二十三条，且额外指出了主体范围问题 | ✅ 真实环境 |
| LLM + 规则 + 合并（10 条款合同） | 10 条 LLM 结果 + 2 条规则结果 = 12，0 失败；规则只影响 `clause_001` 与 `clause_004`，其余不受影响；`clause_004` 上 LLM 与规则两条结果并存 | ✅ 真实环境 |
| **完整 LangGraph E2E（5 条款示例合同）** | **5 个条款 → 5 条 LLM 结果 + 2 条规则结果 → 7 条最终结果，0 条失败**；整体风险 `high`，`summary`：high 4 / none 3 | ✅ 真实环境 |
| 整理（配置集中、测试分层、scripts 整理）后重跑 | 258 passed；真实 E2E 复跑无问题 | ✅ 真实环境 |
| 整理前后默认值 | 11 项逐项等价（沙箱机械校验） | 🧪 |
| 各层测试数量 | 总数 258、graph 12 已在真实环境确认；`unit 184 / module 62` 按 `conftest.py` 登记推算，未逐层单独核对 | 🧪 |
| 变异检查 | 故意把 merge 改成覆盖式、吞掉规则异常、让 LLM 永不失败，对应测试均变红 | 🧪（沙箱） |

**关于真实 E2E 里的 `high 4 / none 3`**：`clause_003`（试用期）与 `clause_005`（竞业限制）的 LLM 结果为 `high`，加上 2 条规则的 `high` 共 4 条；其余 3 条 LLM 结果为 `none`。LLM 结果对边界条款有非确定性（见已知限制），所以复跑时 `none` / `low` 的具体分布可能不同，规则部分（2 条，文字完全相同）和两个 `high` 的 LLM 结论应保持稳定。

## 18. 已知限制

**功能范围**
- ⚠️ 只能解析 `.txt`；PDF / DOCX / 图片（OCR）解析器是占位，调用会抛 `NotImplementedError`。
- 📝 没有 HTTP API（`api/` 为空包），没有结果格式化输出（`output/` 为空包）。
- ⚠️ 知识库只有《劳动合同法》14 条节选，没有工时、加班费、经济补偿金、社保等内容。对这类条款，LLM 会如实说"依据不足"，这是覆盖问题，不是缺陷。
- ⚠️ 规则只有 2 条，且识别范围有限（见 RuleChecker 设计）。

**结果可信度**
- ⚠️ **LLM 输出不保证可复现**：`temperature=0` 也不能保证。同一份合同两次真实运行，边界条款出现过 `low` ↔ `none` 的翻转；证据明确的高风险条款两次都稳定。
- ⚠️ **单条款审查看不到其他条款**，只有试用期相关的跨条款问题被规则覆盖。
- ⚠️ `ReviewResult` 没有保存检索到的 `Evidence`，无法事后审计"模型当时看到了哪些法条"。
- ⚠️ `ReviewVersions` 全部为空（`llm_model`、`prompt_version` 等都没有数据来源）。
- ⚠️ 同一个风险可能同时出现 LLM 与规则两条内容相近的结果（v1 不做去重）。

**流程与健壮性**
- ⚠️ 除 LLM 单条款失败外，任何节点异常都会终止整张图；没有重试；`RuleChecker` 内部没有逐规则的容错，一条规则的 bug 会让整个规则检查失败。
- ⚠️ 没有任何代码把合同状态置为 `reviewed` 或 `failed`（状态只推进到 `uploaded → parsed → split`）。
- ⚠️ `ReviewReport` 在图内构造后不保存，调用方需要自己重建。
- ⚠️ LLM 分支在一个节点内**顺序**逐条调用，耗时随条款数线性增长。

**代码与文档一致性**
- ⚠️ **部分文档字符串已漂移**（本次整理没有修改代码，只记录）：`schemas/contract.py`、`schemas/_time.py` 仍提到 SQLite，实际是纯文件系统存储；`schemas/review_report.py` 提到"重试"和"formatter"，实际都不存在。
- 两个过渡桥接文件（`parser/contract_parser.py`、`clause/contract_clause_splitter.py`）仍被 `pipeline.py` 直接调用，原计划的"被 pipeline 收编"尚未做。
- 各验证脚本开头各有一份 `sys.path` 引导；`tests/test_review_reviewer.py` 与 `tests/test_review_pipeline.py` 里有相似的假对象。
- 已验证环境只记录了 Python、pytest、LangGraph 的版本，其他依赖版本未记录。

## 19. 后续优化方向

以下是候选方向，**不是已承诺的计划**；按"真实测试暴露了什么再做什么"的原则排序。

1. **补规则**：用更多真实合同做迭代测试，把稳定漏检的问题沉淀成规则（例如竞业限制的期限与补偿），而不是提前写通用规则引擎。
2. **扩充知识库**：加入工时、加班费、经济补偿金、社保等条文，并考虑多部法规。
3. **解析能力**：实现 PDF / DOCX，必要时 OCR。
4. **应用层**：`api/`（HTTP 接口）、`output/`（结果格式化）；让流程更新合同状态（`reviewed` / `failed`）。
5. **可审计性**：在结果中保留 `Evidence`；填充 `ReviewVersions`；持久化 `ReviewReport`。
6. **稳定性**：为 LLM 分支加超时 / 重试；`RuleChecker` 增加逐规则容错；针对非确定性，可评估只对 `none` / `low` 结果做重复采样（成本与延迟会上升，需权衡）。
7. **性能**：LLM 分支的逐条调用可并发。
8. **结果展示**：真实数据证明 LLM 与规则重复率过高时，再设计"风险级"的去重 / 合并展示。
9. **整理遗留**：收编过渡桥接文件；修正漂移的文档字符串；合并测试里重复的假对象。
