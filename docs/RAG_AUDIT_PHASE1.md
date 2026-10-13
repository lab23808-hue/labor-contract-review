# RAG 全面审计 — 第一阶段：现有工程与数据审计

审计时间：2026-10-11（UTC+0 时间戳以下方各项为准）
审计方式：**本次通过设备桥接直连用户真实机器（`desktop-59khkro`，项目路径
`C:\Javase\pythonproject\labor_contract_review`）重新列目录、重新拉取并读取当前真实文件内容、
对 `data/chroma/chroma.sqlite3` 用 Python `sqlite3` 模块重新查询真实表数据计算得出**——
不是复述此前任何一轮会话的报告结论。本机没有可用的远程 shell 工具（`device_bash` 在本次连接中不可用，
仅有 `device_list_dir`/`device_stage_files`/`device_commit_files`），因此本阶段**没有在用户机器上
重新执行任何脚本**，所有数字都来自对真实文件内容的直接读取和计算，不是脚本打印出来的日志。
这一限制和它的影响在下面逐项标注，不隐藏。

---

## 0. 门控检查结论（先说结论）

**发现一个需要停下来由人工处理的问题，其余未触发"停止"条件。**

🔴 **触发「法律权威来源不足 / 数据可信度问题」门控**：
`data/knowledge/SOURCES.md` 自己记录的事实是——当前知识库里 27 条法条中有 **12 条
（第22/25/26/36/39/40/46/47/48/82/85/87条）的文本内容"仅凭模型对公开法条的记忆写出，
未能通过工具逐字核对官方原文"**，也就是说这 12 条的具体文字**可能是模型凭记忆生成、
并非逐字核实的官方原文**，文件里原话建议"正式使用前人工核对条文原文"。这不是本次新发现的
风险，而是此前会话已经如实记录在案、但从未被本次任务明确要求过的视角（"法律内容本身是否
权威可信"）重新审视过。在没有人工核对这 12 条真实法条原文之前：
- 第二阶段"国家层面法律覆盖审计"不应该把这 12 条当作"已收录、可信"的基线去扩展；
- 第三阶段任何引用了这 12 条作为标准答案法律依据的新合同样本，其 gold answer 的法律
  权威性同样存疑；
- 所有基于这 26 个 chunk 跑出来的检索指标（Recall/MRR/nDCG）衡量的是"检索器能不能找到
  知识库里已有的这段文字"，**不是"找到的是不是真实有效的法律条文"**——这是两个独立的
  维度，不能互相替代。

**建议**：在继续后续阶段之前，先由人工（或至少用能逐字抓取官方原文的工具）核对这 12 条
的文本内容，确认后更新 `SOURCES.md` 的核验状态；或者至少在继续阶段二/三之前，明确接受
"当前阶段性结论建立在未逐字核验的法条文本之上"这个前提，不要在后续报告里把"检索指标很高"
说成"法律依据可信"。

其余 6 类门控条件（结构性不一致、gold-answer 对应关系不可确认、无法隔离生产索引、
人工核验不足、环境/依赖缺失、数据可信度的其它子问题）**本次审计未发现触发**，具体证据见下文。

---

## 1. 生产 RAG 工程链路审计

### 1.1 Query 如何生成

`generate_query()` 的真实定义在 **`agents/review_agent.py` 第 43-58 行**（不是 `rag/` 包内，
这一点此前文档里提到过，本次重新读取源码确认位置和实现未变）：

```python
def generate_query(clause: Clause) -> str:
    text = _ARTICLE_NUMBER_RE.sub("", clause.original_text, count=1)   # 只去掉开头"第X条"编号
    text = _ITEM_PREFIX_RE.sub("", text, count=1)                      # 只去掉"1."/"（一）"这类编号
    text = text.strip()
    return text or clause.original_text.strip()
```

只剥编号前缀，保留条款标题和正文（docstring 里解释了为什么不剥标题：标题词往往是最精准的
法律术语）。`scripts/build_retrieval_eval_samples.py` 确认调用的是这同一个真实函数
（`from agents.review_agent import generate_query`），不是另写的近似实现——本次重新读取
两个文件的 import 语句和调用点，确认一致。

### 1.2 生产检索链路的真实调用顺序

```
Clause
  → agents.review_agent.generate_query(clause)                     # 生成 query 文本
  → rag.retriever.LegalKnowledgeRetriever.search_legal_knowledge(query, k=top_k)
      → rag.database.ChromaKnowledgeBase.similarity_search(query, k)
          → self._store.similarity_search_with_score(query, k=k)   # langchain_chroma.Chroma
  → LegalKnowledgeRetriever._to_evidence(doc, score)  →  list[Evidence]
  → prompts.review.build_review_messages(..., evidence=evidence)
  → llm.client.OpenAICompatibleClient.chat(messages, json_mode=True)
```

**关键发现（本次审计最重要的一条，直接影响如何理解此前所有 BM25/RRF 实验的定位）**：

生产链路里 `rag/database.py::ChromaKnowledgeBase.similarity_search()` 只调用了
`langchain_chroma.Chroma.similarity_search_with_score()`，这是**纯稠密向量检索（Dense，
BGE-M3 via Chroma HNSW 索引）**。整个 `rag/` 包（`database.py`/`embedding.py`/
`knowledge_loader.py`/`retriever.py`）里**没有任何 BM25、分词器、RRF 融合的代码**。

也就是说：此前所有轮次的 BM25 分词器/预处理/边界实验、RRF、加权 RRF 实验，**全部只存在于
`scripts/eval_*_experiment.py` 这些独立实验脚本里，从未被接入 `rag/retriever.py` 或
`agents/review_agent.py`，生产环境现在、以及此前所有实验轮次期间，一直只用 Dense 检索**。
`scripts/README.md`/`docs/RAG_EXPERIMENTS.md` 里"保留 char_bigram baseline"等措辞指的是
"实验对照里选哪个 BM25 变体作为参照基线"，不是"生产正在用 BM25"——本次重新读取
`rag/` 全部源码后确认这一点此前的表述本身没有造成误导（文档没有宣称 BM25 已上线），
但这里明确点出来，避免第二阶段/第五阶段讨论"是否接入加权 RRF"时，误以为现在生产已经是
BM25 或 RRF 在跑。

### 1.3 Top-K 配置

`config/settings.py` 第 23 行：`RETRIEVAL_TOP_K = 5`。`ClauseReviewer.__init__` 和
`LegalKnowledgeRetriever.__init__` 都用这个默认值，没有发现任何地方在运行时覆盖它。

### 1.4 知识库构建/更新/删除/重复导入行为

`scripts/build_knowledge_base.py`：
- 默认行为（不传 `--append`）：先 `kb.reset()`（`delete_collection()` 后重新打开），再写入——
  **每次默认运行都是完全重建**，不是增量更新。
- `--append`：不清空，直接写入。
- `rag/knowledge_loader.py::KnowledgeLoader.index()`：id 由 `(source, article, part, content)`
  的 sha256 确定性生成，**同批次内先按 id 去重（保留第一条），跨批次靠 Chroma 的 upsert 覆盖
  同 id**——docstring 里坦诚写明"upsert 真的覆盖而不是追加"这一半**没有在沙箱里端到端验证过，
  依赖 chromadb 真实行为"，以及一个已知未解决的限制："改变 chunk_size 重新索引后，旧的 part
  不会被自动清理（upsert 机制做不到）"。本次审计确认这两条记录仍然真实存在于当前代码里，
  不是已经修复、文档忘了更新的情况。

### 1.5 真实验证：当前生产 Chroma 的实际状态（本次直接查询，不是读日志）

直接 stage 了 `data/chroma/chroma.sqlite3`，用 Python `sqlite3` 模块查询：

| 项目 | 真实查询结果 |
|---|---|
| collection 数量 | 1 个：`legal_knowledge`（id `5c4c5a88-...`） |
| embeddings 表总行数 | **26**（distinct id 也是 26，无重复） |
| `embedding_metadata` 里 `source` 字段分布 | 全部 26 条 `source = "劳动合同法"`，没有第二个来源 |
| segments 表 | 1 个 VECTOR 段（id `e0de18f2-e3f2-...`）+ 1 个 METADATA 段，都属于同一个 collection |

**磁盘上发现一个真实但不影响正确性的工程卫生问题**：`data/chroma/` 目录下还有一个
`9c262c7b-7d52-4e29-98c6-c215daf5b2de` 子目录，但 `segments` 表里**没有任何记录引用这个
id**——它不是当前 collection 的任何段，是历史某次 `reset()`/重建遗留下来的孤立目录，
不参与当前检索、不影响结果，但会占用磁盘空间、也可能在未来排查问题时造成混淆。本次审计
**只记录事实，不建议本阶段自行删除它**（删除不可逆，且超出"只读审计"范围）。

**结论：生产知识库当前真实只有 26 个 Evidence chunk，全部来自单一法律文件
`劳动合同法.txt`，与此前历史实验报告里反复出现的"26"一致——这不是 26 份法律文件，
是从 1 份法律文件（节选 27 条）切出来的 26 个 chunk（其中一条因为是空产出或被去重，
后面 1.6 节说明具体差异）。**

### 1.6 为什么是 27 条法条但只有 26 个 chunk

`SOURCES.md` 记录"历史遗留 15 条 + 本次新增 12 条 = 27 条"。真实 chroma 里是 26 个 chunk。
本次审计**没有在用户机器上重新跑 `build_knowledge_base.py`（没有 shell 权限），所以无法
在本阶段现场重新验证这 1 条的具体差异来自哪一条**——可能是某条文本经二次切分后产出 0 个
非空 block，也可能是两条 (source, article, part, content) 完全相同被去重。这一点标记为
**「未验证，需要后续在可执行脚本的环境里重新运行 `KnowledgeLoader.load_file()` 并对比
条号列表才能确认」**，不是本阶段能下结论的事，不编造解释。

---

## 2. 知识库内容审计（真实读取 `data/knowledge/` 当前内容）

- `data/knowledge/` 目录下**只有一个法律文本文件**：`劳动合同法.txt`（10,067 字节），
  以及 `SOURCES.md`、`VERSION`（内容是 `kb-2026-10-10-01`）、`.gitkeep`。
  **没有第二个法律文件**——此前任何报告如果暗示"知识库"涵盖多部法律，本次审计确认
  真实情况是：目前只有《劳动合同法》的部分条文。
- `SOURCES.md`（本次完整重新读取全文，不是摘要）记录的真实收录范围：
  - 《劳动合同法》全文 98 条，本知识库**只收录 27 条**（历史 15 条 + 本次新增 12 条）。
  - 新增的 12 条（第22/25/26/36/39/40/46/47/48/82/85/87条）**文本内容未逐字核验**，
    已在第 0 节的门控结论里点出，不重复。
  - 《劳动合同法实施条例》《最高法劳动争议案件法律适用解释（一）》《劳动法》
    **均未收录任何条文内容**，只记录了"法律确实存在、现行有效"这类结构性事实，
    标记为 `pending_source`。
- **结论（直接影响第二阶段）**：当前知识库的法律覆盖面非常窄——只有《劳动合同法》
  的四分之一左右，且其中接近一半（12/27）文本未经逐字核验。第二阶段"国家层面法律
  覆盖审计"如果要做，起点不是"检查现有覆盖是否全面"，而是"现有覆盖本身就明确不全面、
  且部分内容可信度未知"，这一点第一阶段已经可以直接给出结论，不需要等到第二阶段
  才发现。

---

## 3. 评估数据审计（真实读取 + 重新计算，不是复述历史数字）

重新 stage 并用 Python 对 `data/eval_samples/retrieval_eval_samples.json`（当前真实文件，
`generated_at: 2026-10-10T14:36:48Z`）做了独立重新计算（不是读取文件里预先写好的汇总字段，
是对 315 条 `samples` 数组本身重新数数和去重）：

| 统计量 | 文件自带汇总字段 | 本次独立重新计算 | 是否一致 |
|---|---:|---:|---|
| 总条款数 | 315 | 315（`len(samples)`） | ✅ |
| 可评估（evaluable=True） | 188 | 188 | ✅ |
| 不可评估 | 127 | 127 | ✅ |
| 多标签样本 | 20 | 20（`len(relevant)>1`） | ✅ |
| 覆盖率 | 0.5968 | 188/315=0.5968 | ✅ |
| 不同合同数 | （未在汇总字段里） | **50**（`contract_sample_id` 去重） | — |
| 不同 query 数（全部 315 条） | （未在汇总字段里） | **53** | — |
| 不同 query 数（仅 188 条可评估） | （未在汇总字段里） | **47** | — |

**47 这个数字本次独立验证为真实计算结果，不是沿用历史报告**，且与此前所有轮次报告的
"47 个独立场景"完全一致。

### 3.1 为什么 50 份合同只产出 47 个不同场景（本次给出确认依据，不是猜测）

读取 `data/eval_samples/manifest.json` 发现：50 份评估合同按 `sample_type` 分为
`clear_risk`（20 份）、`compliant`（10 份）、`mixed`（10 份）、`boundary`（10 份）四类，
每一类里同类型的多份合同共享**同一句 `description`**（例如 `clear_risk_01` 到
`clear_risk_20` 全部是"以「试用期工资」为主导的明确风险样本，用于测量漏检"）——
这说明合同生成逻辑（`evaluation/generate_contracts.py`，本次未重新读取该文件源码，
留到需要时核实）是**基于有限模板批量生成**的，同一个风险模式会在多份合同里重复出现
（文字可能有合同主体名称等差异，但核心条款的法律问题模式相同）。

结合 `generate_query()` 只保留条款标题+正文、剥掉编号，不同合同里同一模板产出的条款
原文/标题高度相似甚至相同，于是生成的 query 文本大量重复，去重后从 315 条收窄到
53（全部）/47（可评估）个不同 query。**这是模板化生成设计的自然结果，不是去重逻辑的
bug，也不是对同一批数据重复计数**——本次审计确认了这个结论链路（manifest 的
description 重复模式 → query 生成规则 → 去重计数），但没有重新读取
`evaluation/generate_contracts.py` 的具体模板代码来逐一核对每个模板对应多少份合同，
这部分标记为「结论可信但模板明细未逐一核对，如需要可下一步补充」。

### 3.2 gold answer 与 Evidence 的对应关系

`scripts/build_retrieval_eval_samples.py` 第 58-69 行 `_knowledge_base_articles()`：
按文件名扫描 `data/knowledge/*.txt`，用正则 `第[X]条` 提取条号集合，构建
`{source_filename: {条号集合}}`；第 116-122 行用这个集合过滤——标准答案引用的
`(source, article)` **只有真的存在于当前知识库的那个文件里，才会被标记为
`evaluable=True`**，否则标记 `evaluable=False` 并写明 `exclude_reason`。这意味着：
**188 条"可评估"样本的 gold answer，100% 保证在生成时就已经验证过"引用的法条确实在
知识库文件里"**，不存在"标准答案引用了知识库里根本没有的条文"这种结构性错配。

但这只验证了"条号存在"，**不验证"条号对应的文本内容是否逐字正确"**——如果 1.6 节/
第 0 节提到的那 12 条未逐字核验的条文本身内容有误，那么即使"条号匹配"，检索到的
内容也可能和真实法条不符，这类错误不会被现在的 `evaluable` 判定捕捉到。

---

## 4. 历史实验可复用性审计

逐一核对了 `scripts/README.md`/`docs/RAG_EXPERIMENTS.md` 列出的 9 个 RAG 实验脚本
（02-09 号）依赖的两份共享输入：

| 依赖项 | 本次真实核验结果 |
|---|---|
| 知识库快照（26 个 chunk，`劳动合同法`） | 与 1.5 节真实查询结果一致；`VERSION` 文件 `kb-2026-10-10-01` 自本次审计期间未变（`data/knowledge/VERSION` mtime 早于所有实验结果文件） |
| `retrieval_eval_samples.json`（315/188/127/47） | 本次重新计算后与历史报告完全一致（见第 3 节），且该文件的 `mtime`（2026-10-11 真实设备时间戳对应 `1791643008313`）早于本次能看到的所有实验结果文件，确认实验运行时用的是这同一份快照，不存在"实验用的是旧版样本集"的风险 |

**结论：此前完成的 Dense 基线、BM25 分词器/预处理/边界实验、RRF、加权 RRF、315 条全量
诊断，全部基于同一个 26-chunk 知识库快照和同一份 315/188 样本快照计算得出，内部一致，
标记为「已复核可复用，指标数字不需要重新跑」。** 但这个"可复用"的范围**只限于
"检索算法在当前这个窄知识库上的相对表现对比"**，不能被引用为"系统法律覆盖是否完整"
或"法律内容是否准确"的证据——这两类结论需要第二阶段单独审计，且已经在第 0/2 节
提前发现了明确的负面信号。

---

## 5. 工程文件清单（本次真实列目录结果，非历史记忆）

```
labor_contract_review/
├── agents/        review_agent.py（含 generate_query）、modification_agent.py、review_schemas.py、risk_analyzer.py
├── config/        settings.py（RETRIEVAL_TOP_K=5 等）
├── rag/           __init__.py、database.py、embedding.py、knowledge_loader.py、retriever.py（共 5 个 .py，纯 Dense）
├── rules/         checker.py、merge.py、probation_duration.py、probation_salary.py（4 个真实规则文件，仅试用期相关）
├── scripts/       28 个脚本（9 个 RAG 实验 + 1 个临时探测脚本 + 18 个其他验证/工具脚本）
├── data/
│   ├── knowledge/   仅 1 个法律文件（劳动合同法.txt）+ SOURCES.md + VERSION
│   ├── chroma/      1 个 collection（legal_knowledge，26 个 embedding）+ 1 个孤立遗留目录
│   ├── eval_samples/  50 份评估合同（contracts/+answers/，各 50 个 json/txt）+ retrieval_eval_samples.json（315 条）+ manifest.json + rule_candidate_cases.json + full_sample_diagnostics.json/.md + results/（23 个历史实验结果文件）
│   └── contracts/   22 个 UUID 目录——**这是生产应用真实使用产生的合同审查记录（clauses.json/metadata.json/review/等），与 eval_samples 完全无关，不要在后续阶段的"合同数据"统计里把两者混在一起**
└── docs/          12 个 .md 文档（含本次延续维护的 RAG_EXPERIMENTS.md）
```

---

## 6. 本阶段的局限性声明（如实列出，不隐藏）

- **没有在用户机器上重新执行任何脚本**：本次会话的设备桥接只提供了 `device_list_dir`/
  `device_stage_files`/`device_commit_files`，没有可用的远程 shell（`device_bash` 工具
  连接失败，提示该工具在本次连接里不可用）。因此"真实运行一次 `build_knowledge_base.py`
  /`eval_retrieval_baseline.py` 确认当前环境依赖完整、脚本能跑通"这件事**本阶段没有做**，
  标记为「未验证」，不是「已验证通过」。
- `evaluation/generate_contracts.py`（50 份合同的具体模板实现）本次**没有读取源码**，
  3.1 节的结论是通过 `manifest.json` 的描述文本模式 + `generate_query` 规则推出的，
  链路合理但不是逐行代码核对，如果后续阶段需要精确知道"每个模板具体生成了几份合同、
  模板之间文字差异有多大"，需要补充读取这个文件。
- 1.6 节"27 条法条为何只有 26 个 chunk"的具体原因未查明，标记为未验证。
- 本次没有对 `data/contracts/` 下 22 份真实生产数据的内容做任何读取（超出"只读审计
  RAG 工程"的范围，且可能涉及真实用户上传内容，第一阶段没有必要也没有被要求去看）。

---

## 7. 下一步建议（不代表已经决定，等待用户确认）

1. **优先处理第 0 节的门控问题**：人工核对（或用能逐字抓取的工具重新核对）那 12 条
   未验证法条的真实文本，再决定第二阶段怎么做。
2. 如果用户认为"检索算法相对表现"和"法律内容准确性"可以分开推进，那么：
   - 依赖"检索算法对比"的部分（第五阶段的 Dense/BM25/RRF/加权RRF 公平对比）理论上可以
     在**不等法律内容核验完成**的前提下独立推进，因为它测的是"在当前知识库快照上检索
     算法谁更好"，这个相对比较不依赖条文内容本身是否权威；
   - 但依赖"法律覆盖是否完整/准确"的部分（第二阶段、以及第三阶段任何新增 gold answer
     引用了那 12 条的样本）**不建议现在推进**，需要先完成上面第 1 条。
3. 如果需要，可以补充一次有真实 shell 权限的验证，跑一遍 `build_knowledge_base.py --append`
   或等价操作，现场确认 1.6 节的 1-chunk 差异来源，以及确认当前环境依赖（BGE-M3/chromadb等）
   是否仍然能正常跑通——这不是必须现在做的事，取决于用户是否需要这份"环境可运行性"证据。

---

## 8. 补充核验（2026-10-12）：独立重新执行加权 RRF 历史实验，而不是复述报告数字

用户提供的新指令要求"先核对以下文件是否真实存在、结构是否一致、数据能否复算，不要把历史报告
简单复制为新实验结果"。本次没有停在"读取 `.md` 报告里写的数字"这一步，而是**把脚本真的重新
跑了一遍，用真实计算结果和历史报告逐项比对**。

### 8.1 文件真实存在性（真实列目录确认，见第一阶段报告正文的 `data/eval_samples/results/`
清单，这里不重复列）

`retrieval_strategy_experiment_20261011_030953.json/.md`、
`weighted_rrf_experiment_20261011_223313.json/.md`、`scripts/eval_weighted_rrf_experiment.py`、
`docs/RAG_EXPERIMENTS.md`、`scripts/README.md` **全部真实存在**，大小与此前记录一致。

### 8.2 独立重新执行 `eval_weighted_rrf_experiment.py`（不是读取历史 JSON 里已经算好的字段）

把脚本、依赖的 `eval_retrieval_strategy_experiment.py`（只用其中的纯函数，不触发任何
langchain/chromadb 导入——本次确认了这一点：模块顶部只 import 标准库和 `config.settings`，
真实 Dense/Chroma 相关的 import 都在函数内部，不会在被当作库 import 时触发），以及真实的
`retrieval_strategy_experiment_20261011_030953.json` 一起拉到沙箱里，**用 Python 直接调用
`weighted_mod.run(input_path, 60)` 重新跑了一次完整融合计算**，不是读取历史结果文件里已经
存好的数字。重新计算结果与历史报告逐项比对：

| 核验项 | 历史报告记录 | 本次独立重新计算 | 是否一致 |
|---|---|---|---|
| 对称 1:1 自检（47 个场景逐一比对） | 0 处不一致 | **重新跑出 0 处不一致**（`symmetric_sanity_check_mismatches: []`） | ✅ |
| 对称 RRF 1:1，K=5，独立场景口径 | Recall 0.9610 / MRR 0.7571 / nDCG 0.8049 | 0.9610 / 0.7571 / 0.8049 | ✅ |
| Dense 偏重 2:1 | 0.9557 / 0.8050 / 0.8310 | 0.9557 / 0.8050 / 0.8310 | ✅ |
| BM25 偏重 1:2 | 0.9397 / 0.8766 / 0.8931 | 0.9397 / 0.8766 / 0.8931 | ✅ |
| BM25 强偏重 1:3 | 0.9291 / 0.8723 / 0.8881 | 0.9291 / 0.8723 / 0.8881 | ✅ |
| 纯 BM25（来自 030953 输入文件本身，不是加权 RRF 脚本产出） | 0.9344 / 0.9007 / 0.9020 | 0.9344 / 0.9007 / 0.9020（直接读取 `030953.json` 的 `aggregate_scenario_level.bm25.5`） | ✅ |
| 知识内容指纹字段 | 声称存在，Dense 因无法证明一致被真实重跑 | 真实读到 `timing.dense.knowledge_chunk_content_fingerprint`（26 个哈希）、`knowledge_content_shared_with_bm25: true`、`mode: "rerun"`，原因字段原样写着"知识内容无法证明一致，按规则不允许复用" | ✅ |
| 5 个已知失败案例的具体排名（社保放弃第十七条→19名；延迟支付第二十六条 BM25排名6→融合后17-18；工作地点第二十六条两通道均未召回；加班费/合同解除的 Top-5 掉出） | 见指令原文第 3.2 节 | **逐一重新跑出完全相同的排名数字**（细节见本次会话工具调用记录），包括"工作地点"场景下第二十六条在全部 4 个权重配置下 `fused_ranks` 均为 `null`——确认"任何权重都无法凭空找回"这句话不是夸大 | ✅ |

**结论：历史加权 RRF 实验的全部关键数字，本次独立重新执行后完全可复算、完全一致，没有发现
任何编造或篡改的数字。** 这是真正意义上的"复核"，不是对历史报告的二次转述。

### 8.3 顺带确认的一个已知但容易被忽略的细节

`retrieval_strategy_experiment_20261011_030953.json` 的 `knowledge_base_consistency` 字段
记录：`content_match_exactly: true`（26 个 chunk 内容逐字相同）但 `ids_match_exactly: false`
——原因是 `_evidence_id()` 在"加入 part 字段"那次修复前后算法不同，不是内容本身变了。
本次重新读取确认这条记录目前仍然真实存在、未被后续任何修改掉，供阶段四建立快照指纹时参考
（不能只看 id 是否相同来判断知识内容是否一致，要看这个字段里实际比对的内容哈希）。

### 8.4 正式代码保持未改动的交叉验证

本次独立执行过程中重新读取了 `rag/database.py`/`rag/retriever.py`/`rag/knowledge_loader.py`/
`agents/review_agent.py` 的当前真实内容（与第一阶段审计时读取的内容逐字相同），以及这些文件
在用户机器上的 mtime（均早于本轮和历史所有实验结果文件的时间戳）——确认加权 RRF 实验前后，
正式 `rag/`、`agents/`、规则引擎代码没有被改动，`data/chroma` 也没有被本次沙箱内的复核操作
触碰（本次全部计算在沙箱里用拉取下来的文件副本完成，没有任何一步连接用户机器上的真实 Chroma
或调用真实 BGE-M3）。

### 8.5 历史实验可复用性分类（按本轮指令要求的四分类）

| 实验 | 分类 | 依据 |
|---|---|---|
| Dense Top-K(5/10/20) 基线 | **仅能复用部分结果** | 结果数字本身可信（历史已验证），但该文件没有保存 `knowledge_chunk_content_fingerprint`，后续如果要把它当作"与当前知识库内容一致"的证据来复用，证不出来——这正是 030953 号实验选择真实重跑 Dense 而不直接复用它的原因，本次审计确认这个限制依然存在 |
| BM25 分词器/预处理/边界实验（05/06/07号） | **可复用且已复核** | 本次 Phase 1 审计已确认知识库快照（26 chunk）、样本快照（315/188/47）均未变化，历史结果内部口径一致，此前轮次已做过真实运行 |
| Dense+BM25+RRF 策略对比（030953号，04号脚本） | **可复用且已复核** | 本次直接重新读取并核对了 `knowledge_base_consistency`/`timing`/`aggregate_scenario_level` 等关键字段，数字自洽，Dense 通道明确标注为真实重跑（非虚假复用） |
| 加权 RRF（09号脚本，223313号结果） | **可复用且已复核（本次独立重新执行验证，最高置信度）** | 见 8.2 节，是本报告目前验证强度最高的一项——不是"读取历史文件确认结构"，是"重新跑出一样的数字" |
| 315 条全量诊断 | **可复用且已复核** | 此前轮次已有运行时断言（`all_hit_top5==bool(hit_top5)`）保证内部一致性，本次 Phase 1 独立重新计算过 315/188/127/47 这组基础数字，与诊断脚本的输入假设一致 |
| 规则候选清单（`rule_candidate_cases.json`） | **仅能复用部分结果** | 候选模式和出现次数的统计可信，但"是否纳入 RuleChecker"本身明确标注为未决策，且本次指令要求"经人工核验后才能进入核心评估指标"，候选清单目前的 `needs_rule_review` 等字段都是 AI 判断，不是人工核验结果，不能当作已核验结论复用 |

---

## 9. 本轮门控结论（覆盖/延续第 0 节，按新指令的阶段推进规则重新表述）

- **不触发"结构性不一致"或"数据不可复算"门控**：第 8 节的独立复核证明历史实验数字真实、
  可复算、未被编造。
- **仍然触发第 0 节已经指出的"法律权威来源不足"门控，且按本轮指令的措辞，这现在明确升级为
  "暂停依赖这些数据发布正式最终 Recall 结论"**：知识库里 12 条法条文本未逐字核验、
  127 条无标签样本尚未人工复核、188 条已标注样本尚未重新核查漏标错标——在这些完成之前，
  任何"Dense/BM25/RRF 谁更好"的结论都只能是"在当前未完全核验的数据上，候选方案之间的相对
  比较"，不能发布为正式最终结论。这和用户在新指令里"核心评估标准答案未核验时，不得发布正式
  最终 Recall 结论"的规则完全对应。
- **不依赖上述未核验内容、可以安全独立推进的工作**（按"阶段推进规则"里"独立的小问题受阻可以
  继续其他不依赖该问题且安全的工作"）：
  - 阶段二里"核查权威来源"（给法律文件找官方 URL、效力状态、修订历史）——这是独立的调研工作，
    不依赖评估数据是否核验完成；
  - 阶段四的"知识库与评估快照指纹"机制建设（脚本/哈希方案本身）——这是工程基础设施，可以先
    把机制搭好，不代表现在就能拿它去发布正式结论；
  - 阶段三的"合同去重与重复场景审计"——是对现有数据做结构性检查，不需要等法律内容核验完成。

本报告到此结束，等待用户审阅后决定是否、以及如何继续后续阶段。
