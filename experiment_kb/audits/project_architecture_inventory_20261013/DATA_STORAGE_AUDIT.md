# labor_contract_review 数据存储现状审计（本轮：2026-10-13）

标签含义见 PROJECT_ARCHITECTURE_OVERVIEW.md 开头说明。**隐私规则遵照执行**：本文件不包含任何身份证号/电话/真实姓名/完整合同正文，数量统计以文件数/字节数/SHA256 为主。

## 1. 总览结论（先给结论，后给证据）

**本项目当前没有任何通用关系型/文档型数据库实现。** 所有"数据库"字样的目录/模块，实测后发现都是别的东西：

| 看起来像"数据库"的东西 | 真实实现 | 标签 |
|---|---|---|
| `data/contracts/` 目录名含糊，容易被误以为是"合同数据库" | 纯文件系统：22 个 UUID 命名目录，每个目录下是 JSON/TXT 文件（见下）。没有任何数据库引擎介入 | CONFIRMED |
| `rag/database.py` | 类名 `ChromaKnowledgeBase`，本质是对 **Chroma 向量库**（`langchain_chroma.Chroma`）的薄封装，只服务于"法律知识相似度检索"这一单一场景，不是通用数据库 | CONFIRMED |
| `data/chroma/chroma.sqlite3`（401408B） | 是 Chroma 内部自带的 SQLite 文件（Chroma 的实现细节），**不是项目自己设计的业务数据库**，不能直接拿来存合同/实验数据 | CONFIRMED |
| `experiment_kb/results/RAG_EXPERIMENT_REGISTER.csv` | 一张手工维护的宽表 CSV，字段里混杂大量自由文本（见第5节），不是结构化数据库表 | CONFIRMED |

## 2. 业务数据存储分类与定位

### 2.1 合同相关数据（CONFIRMED，来自 `contract/manager.py` 全文 + `data/contracts/` 真实目录列表）

存储介质：**纯文件系统**，JSON + TXT，无数据库引擎。

| 数据 | 格式 | 位置 | 可覆盖性 |
|---|---|---|---|
| 原始合同文件 | 任意（保留原扩展名） | `<contract_id>/original_file/<原文件名>` | 不可覆盖（审计依据） |
| 解析文本 | TXT（`newline=""` 保证逐字节一致） | `<contract_id>/parsed_text.txt` | 可覆盖 |
| 条款列表 | JSON（Pydantic `Clause` 列表） | `<contract_id>/clauses.json` | 可覆盖 |
| 合同元数据 | JSON（Pydantic `Contract`） | `<contract_id>/metadata.json` | 每次状态流转覆盖写（先 `.tmp` 后 `os.replace`） |
| 审查记录 | JSON（Pydantic `ReviewRecord`，含完整 `ReviewReport`） | `<contract_id>/review/review_<version>_<seq>.json` | **不可覆盖**，历史永久保留 |
| 修改任务 | JSON（Pydantic `ModificationTask`） | `<contract_id>/modification_tasks/task_<seq>.json` | 整体覆盖重写（状态流转） |
| 修改批次 | JSON（Pydantic `ModificationBatch`） | `<contract_id>/modification_batches/batch_<seq>.json` | 整体覆盖重写 |
| 版本记录（V1→V2） | JSON（Pydantic `ContractVersion`） | `<contract_id>/versions/version_<version_number>.json` | **不可覆盖**（重复 version_number 报错） |

**contract_id ↔ 各类数据的关联机制（CONFIRMED）**：全部通过"同一个 `contract_id` 对应同一个目录"这一约定关联，**没有任何外键/索引结构**，关联完全依赖目录命名约定。`_CONTRACT_ID_RE = re.compile(r"[0-9a-f]{32}")` 校验格式，防止路径穿越，但这不是关系完整性保证——如果目录被手动改名，关联立即失效（**目录改名脆弱性，CONFIRMED 的架构事实**）。

**V1/V2 关联机制**：`ContractVersion.contract_id`（= family_id，取 V1 的 contract_id）+ `linked_contract_id`（这个版本数据实际存放的 contract_id）。V2 本身是用和用户上传完全一样的 `ContractManager.create_contract()` 创建的、数据结构上与普通合同无区别的一个"真合同实例"，只是被 `list_contracts(exclude_version_hosts=True)` 从合同库列表里过滤掉。**这意味着 V2 数据在存储层面是完全独立、合法的 Contract，只在 API 层被"隐藏"**——这是真实的架构事实，不是我的推测。

**实测规模（CONFIRMED，来自本轮真实设备列表）**：`data/contracts/` 下 22 个 UUID 目录，每个含 `clauses.json`/`metadata.json`/`parsed_text.txt`/`original_file/`/`review/`，部分还有 `modification_tasks/`/`modification_batches/`/`versions/`。本轮**未**逐一读取这 22 个目录的内容统计总字节数/sha256（超出本轮时间预算），这是一个明确的 UNKNOWN 项，留给下一轮。

### 2.2 正式知识库（生产，RAG 用）

| 内容 | 位置 | 规模 | 标签 |
|---|---|---|---|
| 法律原文（BM25 路径读取源） | `data/knowledge/劳动合同法.txt` | 10067B，26 条 Evidence（经 A001/A004 多轮验证） | CONFIRMED |
| 来源说明文档 | `data/knowledge/SOURCES.md` | 9719B | CONFIRMED（存在性）|
| 知识库版本号 | `data/knowledge/VERSION` | 17B，内容形如 `kb-2026-10-10-01`（A004 轮记录的 sha256=`62810baeb84ef24d04ca4f082fc67668f3dd62a22d77cb142c499760d6bf97e8`） | REPORTED（来自A004，本轮未重新读取校验） |
| Dense 向量库（可选策略） | `data/chroma/`：`chroma.sqlite3`(401408B) + 2 个 HNSW 索引目录 | collection=`legal_knowledge` | CONFIRMED |

**知识库内部结构**：BM25 路径下知识库是**纯内存索引**（`BM25KnowledgeIndex`，服务启动时从 `KNOWLEDGE_DIR` 构建，不持久化到磁盘，重启即重建）；Dense 路径下才真正落盘到 `data/chroma/`。**当前 `RETRIEVAL_STRATEGY = "bm25"`（默认），意味着生产环境实际运行的检索路径不依赖 Chroma 持久化数据**——`data/chroma/` 目前更像是"保留的备选方案遗留数据"，而非当前实际在用的生产索引（CONFIRMED，来自 `config/settings.py` 的默认值注释）。

### 2.3 实验知识库（baseline / working / reference_only）

| 名称 | 规模 | 与生产知识库关系 | 标签 |
|---|---|---|---|
| `experiment_kb/baseline/` | 26 条 Evidence（镜像生产知识库） | 冻结快照，含自己的 `rag/`、`config/settings.py`（2317B，**与生产 3143B 不同**，证明是独立快照而非软链接） | CONFIRMED |
| `experiment_kb/working/` | 37 条 Evidence（26 生产 + 11 新增：`LAW_01_劳动合同法_第五十条.txt`471B + `LAW_02_劳动法_第三十六条至第四十五条.txt`2407B） | 在 baseline 基础上扩充 | CONFIRMED |
| `experiment_kb/reference_only/` | 7 条（仲裁法参考材料，`仲裁法_第十条至第十六条_参考材料.txt`1946B） | **明确隔离**，未混入 baseline/working 的常规检索对照，只在 A005/A006 的 44-Evidence 全量实验里被显式引用 | CONFIRMED |

**快照滞后发现（CONFIRMED，本轮新增核实的问题）**：`experiment_kb/baseline/rag/retriever.py` 与 `experiment_kb/working/rag/retriever.py` 均为 1818B，但生产 `rag/retriever.py` 实测为 2761B——本轮已读取生产版本全文，确认差异来源是生产代码新增了 `SimilaritySearchBackend` Protocol 抽象层（2026-10-12 BM25 正式接入时引入），**这两份快照的 `retriever.py` 冻结时间早于这次改造，属于"快照已知滞后于生产代码一个文件"，不影响快照本身用于检索质量对比实验的有效性（因为快照测试调用的是快照自己的 `retriever.py`，逻辑自洽），但如果有人直接拿快照代码去对比"生产代码的检索行为"，会产生误导**——这是需要写进 PITFALLS 的真实发现。

### 2.4 experiment_kb 的其余三类数据（详见 Part 四 专篇，这里只做分类定位）

| 分类 | 位置 | 标签 |
|---|---|---|
| 实验评测数据集 | `experiment_kb/datasets/contract_eval_500_20261013/`（450+50份合同评测集及衍生文件） | CONFIRMED（结构）|
| 实验运行结果 | `experiment_kb/results/`（含 `bm25_kb_growth_diagnosis_20261013/` 子目录） | CONFIRMED（结构）|
| 实验注册表 | `experiment_kb/results/RAG_EXPERIMENT_REGISTER.csv`（48365B，本轮全文读取） | CONFIRMED（全文内容）|

### 2.5 500 份合同工作区规模（CONFIRMED，来自本轮真实设备列表）

`experiment_kb/datasets/contract_eval_500_20261013/` 下：
- `source_450/`：`manifest_450.csv`(306014B)、`candidate_labels_pending_review.csv`(169082B)、`synthetic_contracts/`（450份合同文件，本轮未逐一统计总字节数）
- `retrieval_runs/`：`bm25_run_result.json` 单文件 **3235429B（约3.1MB）**——这是最大的单个实验产出文件
- `audit/label_audit_450.csv`：136945B
- `normalized/unified_eval_manifest_500.csv`：157596B
- `full_kb_experiment/`：8个文件，合计约 490KB（`knowledge_coverage_audit.csv`153425B 最大）

### 2.6 前端状态（CONFIRMED，基于代码结构INFERRED存储方式）

`frontend/` 是 React+Vite SPA，`src/api/client.js`(14951B) 负责与后端 API 通信。**本轮未读取 `App.jsx`/组件源码，无法 100% 确认前端是否有任何本地持久化（如 localStorage）**——按项目既有架构约定（Review/Modification 全部走后端 API），INFERRED 前端状态应为"内存态，刷新即丢，所有权威数据由后端文件系统持有"，但这是推断，不是读码验证，标注 INFERRED。

## 3. 持久化关系与数据关联评估

### 3.1 contract_id ↔ 各类数据（CONFIRMED，见2.1）：目录命名约定，无索引结构，目录改名会导致数据失联。

### 3.2 experiment_id ↔ 数据集/知识库版本/策略/结果（CONFIRMED，来自 RAG_EXPERIMENT_REGISTER.csv 全文）

注册表（`RAG_EXPERIMENT_REGISTER.csv`）每行一个 `experiment_id`（E001-E010, D002, A001-A006），字段包括 `kb_path`/`kb_fingerprint`/`eval_path`/`eval_fingerprint`/`json_path`/`md_path` 等——**这些字段确实存在，理论上可以做关联**，但：
- 关联方式是**文本字符串路径**，不是外键，路径一旦目录重命名（如 `experiment_kb/results/bm25_kb_growth_diagnosis_20261013/` 这种按日期命名的目录）就会断链；
- 多个字段（`conclusion`/`limitation`/`next_step`/部分指标字段如 `index_build_update_delete`）是**自由文本或嵌套 JSON 字符串**，不是结构化数值字段，无法直接做 SQL 聚合查询；
- `recall_at_5`/`recall_at_10` 等指标字段在不同实验行里，有时是单一数值，有时是"new450_dev(口径A)=0.3657/口径B=0.5558；new450_final_test(口径A)=0.3556/口径B=0.5597；old50_188=0.9468"这种**把多个子结果拼成一个字符串塞进一个字段**（A005/A006 行）——这是明确的"表格字段过载"问题，会让未来真正入库变得困难。

### 3.3 跨目录数据重复（CONFIRMED，本轮发现的具体实例）

1. **`RAG_EXPERIMENT_REGISTER_with_A004.csv`**（`experiment_kb/datasets/contract_eval_500_20261013/`，34827B）与当前权威的 `experiment_kb/results/RAG_EXPERIMENT_REGISTER.csv`（48365B，已含 A001-A006）——前者是 A004 时期的历史快照副本，内容已被后者完全覆盖超越，是一份**可安全归档但不应继续被引用**的冗余文件。
2. **`experiment_kb/tmp_runtime/`** 下 4 个临时 Dense/Chroma 实验索引目录（`dense_20261012_143924_431239/`、`dense_20261012_151640_546480/`、`dense_delete_test_20261012_150120_712479/`、`timing_dense_20261012_184956_524621/`），每个约 400-487KB（`chroma.sqlite3`+HNSW二进制），是 E001-E010 时期 Dense 实验的临时索引残留，**纯磁盘占用，无独立保留价值**（本轮不删除，只报告）。
3. **文档重复候选**（REPORTED，未逐篇比对内容，仅凡文件名相似+体量接近列为候选）：`docs/DEVELOPMENT_LOG.md`(58378B) vs `docs/DEVLOG.md`(31869B)；`docs/INTERVIEW_QA.md`(31536B) vs `docs/INTERVIEW.md`(26326B)——是否内容重复需下一轮专门比对，本轮只列为 OPEN_QUESTION。

### 3.4 可重新生成 vs 不可替代的数据（INFERRED，基于以上 CONFIRMED 的存储设计）

| 数据 | 可重新生成？ | 依据 |
|---|---|---|
| `parsed_text.txt`/`clauses.json` | 可（`ContractManager` 本身设计为允许覆盖重新生成） | CONFIRMED（代码注释明确说明） |
| `original_file/` | **不可**（唯一真实凭证，代码明确禁止覆盖） | CONFIRMED |
| `review/*.json` | **不可替代**（历史审查记录，唯一凭证，禁止覆盖） | CONFIRMED |
| `experiment_kb/baseline/`、`working/` 快照 | 理论可重建（`build_snapshot_fingerprint.py` 存在），但**生产代码已经漂移**（见2.3），重建出来的新快照会与旧快照指标不可比 | INFERRED |
| `data/chroma/` | 可重建（BM25 是当前默认策略，Chroma 数据非当前路径强依赖） | INFERRED |
| `RAG_EXPERIMENT_REGISTER.csv` | **不可重新生成**（记录的是历史实验的人工/半自动归档结果，很多实验引用了用户本机真实跑分数据，云端沙箱无法复现"用户本机venv(Windows)"环境下的真实耗时数字） | CONFIRMED（寄存器里逐行声明了 `runtime_env` 字段，明确写了"用户本机venv(Windows)"等不可复现环境标签） |

## 4. 规模与风险统计（不含任何个人信息，只统计数量/大小/指纹）

| 项目 | 数量/大小 | 标签 |
|---|---|---|
| `data/contracts/` 合同目录数 | 22 | CONFIRMED |
| 正式知识库 Evidence 数 | 26 | CONFIRMED |
| `experiment_kb/working` 知识库 Evidence 数 | 37 | CONFIRMED |
| 44-Evidence 全量实验知识库（26+working新增11+reference_only 7） | 44 | CONFIRMED |
| 500 份合同评测工作区单个最大文件 | `bm25_run_result.json`，3235429B（约3.1MB） | CONFIRMED |
| `RAG_EXPERIMENT_REGISTER.csv` 当前大小 | 48365B，19行（含表头，E001-E010/D002/A001-A006共17条实验记录） | CONFIRMED |
| 临时/残留文件（已识别，建议归档不建议本轮删除） | `tmp_runtime/`4个目录（各约400-487KB）+ `RAG_EXPERIMENT_REGISTER_with_A004.csv`(34827B) | CONFIRMED |
| 疑似重复文档（未核实内容） | 2 对（DEVELOPMENT_LOG/DEVLOG，INTERVIEW_QA/INTERVIEW） | REPORTED/候选 |
| `data/chroma/chroma.sqlite3` | 401408B | CONFIRMED |
| 增长最快的目录（INFERRED，基于本轮体量观察） | `experiment_kb/datasets/contract_eval_500_20261013/`（已达数MB量级，且每轮新实验都会在其下新增报告+原始JSON，是当前体量增长最快的位置） | INFERRED |

## 5. 结论：文件整理能解决的 vs 需要真实数据库的

**文件整理/归档能解决的问题**：
- `RAG_EXPERIMENT_REGISTER_with_A004.csv` 等历史快照副本的归档；
- `tmp_runtime/` 下 4 个临时 Dense 索引目录的清理（需等用户确认后执行，本轮不删除）；
- 两对疑似重复文档的核实与合并（需先读内容确认是否真重复）。

**文件整理无法解决，需要真正数据库的问题**（INFERRED，这是本轮审计的核心结论之一）：
1. **路径即关联**的脆弱性：`contract_id`、`experiment_id` 全部靠目录/文件命名约定关联，没有任何机制能在"目录被重命名/实验被重跑覆盖"时自动发现数据不一致——这是关系完整性缺失，文件系统天然做不到。
2. **字段过载**：`RAG_EXPERIMENT_REGISTER.csv` 里把多个子结果（不同数据集切片、不同口径）塞进同一个字符串字段（如 A005/A006 行的 `recall_at_5`），导致无法做结构化查询/聚合统计，这是"表格形状不对"的问题，不是"文件太分散"的问题，加字段整理也解决不了，本质需要重新设计成正规化的表结构（`ExperimentRun` × `Metric` × `DatasetSlice` 的多对多关系）。
3. **可复现性标记缺失结构化字段**：`reproducible_status` 字段里混用了 `ACTUALLY_RUN_ON_USER_DEVICE`/`ACTUALLY_COMPUTED`/`ACTUALLY_COMPUTED_FROM_REAL_FILES` 等多种自由文本写法，没有统一枚举，未来做"哪些实验可复现"筛选时无法可靠做字符串匹配。
4. **没有"数据集版本"和"知识库版本"的独立实体**：当前 `kb_fingerprint`/`eval_fingerprint` 是挂在每一行实验记录上的冗余字段，同一个知识库版本被多行实验重复记录同一个指纹字符串，这正是关系型数据库"维度表拆分"能解决的典型问题。

详细的最小数据库实体设计见 `FUTURE_DB_AND_VISUALIZATION_DESIGN.md`。
