# 实验管理数据库与可视化设计前提（调研结论，本轮不实施）

## A. 实验管理数据库：最小实体设计（INFERRED，基于 DATA_STORAGE_AUDIT 的证据推理）

当前 `RAG_EXPERIMENT_REGISTER.csv` 的核心问题（CONFIRMED，见 DATA_STORAGE_AUDIT 第5节）：字段过载（一个字段塞多个子结果字符串）、无结构化维度拆分（知识库版本/数据集信息逐行重复）、可复现性标记不统一。最小实体设计应直接对症：

| 实体 | 关键字段 | 解决什么问题 |
|---|---|---|
| `Dataset`（数据集） | dataset_id, name, source_path, sample_count, scenario_count, sha256/manifest_hash, created_at | 把"450份新合同"/"现有50份"/"development 360条"/"final_test 90条"这些反复出现的切片变成独立实体，而不是每行实验都重复描述一遍 |
| `KnowledgeBaseVersion`（知识库版本） | kb_version_id, evidence_count, evidence_set_hash, source_files(list), created_at, is_isolated_reference(bool) | 把 kb26/kb37/kb44/生产26条 等版本显式建模，`evidence_set_hash` 直接对应本轮已确认的 `kb_version_manifest.csv` 里的 `evidence_set_hash` 字段 |
| `ExperimentRun`（实验运行） | run_id(=原experiment_id), dataset_id(FK), kb_version_id(FK), strategy, tokenizer, candidate_k, run_at, runtime_env, reproducible_status(枚举,不是自由文本) | 一行一次真实运行，`reproducible_status` 改成受限枚举（如 `actually_run_on_user_device`/`actually_computed_sandbox`/`actually_computed_from_real_files`），不再允许自由文本变体 |
| `Metric`（指标结果） | metric_id, run_id(FK), metric_name(recall_at_5/recall_at_10/mrr/ndcg_at_10/...), scope(scenario_level/sample_level/macro/micro), dataset_slice(dev/final_test/old50/...), value(float) | **这是最关键的拆分**：把 A005/A006 行里"一个字段塞多个子结果字符串"的问题，拆成"一次运行 × 一个指标名 × 一个数据切片 × 一个浮点值"的窄表，可以直接做 SQL 聚合/画图，不用再解析字符串 |
| `Artifact`（产出文件） | artifact_id, run_id(FK), path, file_type(json/md/csv), role(raw/derived/report) | 对应 `json_path`/`md_path` 字段，升级为可以一次运行关联多个产出文件（当前 CSV 每行只能存一个 json_path 和一个 md_path） |
| `AnnotationStatus`（标注状态） | label_id, dataset_id(FK), sample_id, verification_status(candidate/pending_review/verified), verified_by, verified_at | 独立建模标注状态，回答"哪些是人工已核验的 gold standard，哪些仍是候选标签"——当前这个信息散落在 `candidate_labels_pending_review.csv` 的列名里，没有被当成一等公民 |

**主数据 vs 运行历史 vs 原始文件 vs 报告派生物的区分（INFERRED）**：
- 主数据（Master Data）：`Dataset`、`KnowledgeBaseVersion`、`AnnotationStatus` ——变化频率低，是其他一切的基准；
- 运行历史（Run History）：`ExperimentRun`、`Metric` ——每次实验新增一行，只增不改（审计友好，与 `ContractManager.save_review()` "历史不可覆盖"的既有设计哲学一致）；
- 原始文件（Raw Files）：`bm25_run_result.json`（3.1MB）等体量较大的逐条候选明细——**不建议塞进数据库本体**，数据库只存路径+哈希+关键聚合值（见下方 C 节）；
- 报告派生物：`.md` 报告文件——同样只存路径引用，数据库不重复存储报告正文。

## B. 可视化页面最小功能集（INFERRED）

1. **项目数据总览**：合同数、知识库版本数、实验总数、最近一次实验时间——直接查 `Dataset`/`KnowledgeBaseVersion`/`ExperimentRun` 的 COUNT。
2. **实验目录**：按 `ExperimentRun` 列表展示 name/目标/状态/input_dataset/input_kb_version/关联 Metric 摘要，取代目前手动翻 CSV 的方式。
3. **检索效果对比（26 vs 37 vs 44）**：直接按 `Metric` 表中 `kb_version_id` 分组画折线/柱状图，这正是当前 A006 报告里手工整理的"kb26/37/44 Recall@20 单调下降"这张表的通用化版本。
4. **工作地点场景诊断页**：筛选 `dataset_slice` 包含"工作地点"相关 `scenario_id` 的 Metric 记录，展示第26/35条命中/未命中趋势——对应 D002/A005/A006 反复专项分析的那部分内容。
5. **数据质量页**：按 `AnnotationStatus.verification_status` 分组统计 candidate/pending_review/verified 数量，直接回答"还有多少标签没有人工核验"。
6. **数据维护页**：列出 `Artifact` 的 path+size+hash，并标注"是否可安全归档/删除"（对应本轮已识别的 `tmp_runtime/` 临时文件、`RAG_EXPERIMENT_REGISTER_with_A004.csv` 等）。

以上均为"最小页面/实体"级别的功能点清单，不涉及任何具体技术栈选型或界面设计，也不新增任何代码——按指令要求，本轮止步于此。

## C. 本地数据库与未来迁移（INFERRED）

- **为什么当前适合 SQLite（短期）**：实验运行频率低（本会话至今约17次实验/诊断），单机单用户访问，不需要并发写入控制；SQLite 零部署成本，文件本身就能跟着 `experiment_kb/` 一起被 git 管理或打包交付。
- **SQLite 文件应放在哪**：建议放在 `experiment_kb/` 下一个独立的、与 `baseline/`/`working/` 平级的目录（例如 `experiment_kb/registry.db`，具体命名留给实施阶段），而不是塞进 `results/` 或 `datasets/`——保持"实验元数据"与"实验原始产出文件"物理分离，方便将来迁移时只搬运一个 `.db` 文件。
- **备份方式**：SQLite 单文件可直接复制备份，无需额外工具；建议每次重大实验批次（如 A00N）完成后手动复制一份带时间戳的备份——这和当前 `RAG_EXPERIMENT_REGISTER_with_A004.csv` 这种"历史快照副本"命名习惯是一致的，只是从"复制CSV"变成"复制.db文件"。
- **大型产出文件应存路径+哈希，而不是存入数据库本体**：`bm25_run_result.json`（3.1MB）、`miss_analysis.csv`（158KB）等文件应继续留在文件系统里，数据库的 `Artifact` 表只存 `path`/`sha256`/`size_bytes`/`role`——理由：SQLite 把大 BLOB 存进数据库会让单一 `.db` 文件迅速膨胀且难以用 git/常规文件工具管理，不如维持"数据库存元数据索引，文件系统存内容"的分层。
- **哪些设计选择在未来迁移到远程数据库时能存活**：
  - 实体关系设计（Dataset/KnowledgeBaseVersion/ExperimentRun/Metric/Artifact/AnnotationStatus 六个实体及其外键关系）——与具体数据库引擎无关，迁移到 PostgreSQL/MySQL 时原样保留；
  - "只存路径+哈希，不存大文件本体"的分层策略——迁移到远程数据库后更重要（远程数据库的网络往返成本比本地 SQLite 更敏感）；
  - `reproducible_status` 等字段改成受限枚举而非自由文本——任何数据库引擎下都受益。
  - 不能直接存活的：SQLite 的单文件部署方式本身（远程场景需要真正的数据库服务），需要规划迁移脚本，但这是实施阶段的事，本轮不展开。
- **这个数据库是否应该与未来的合同业务数据库分离**：INFERRED，**应该分离**。理由：实验管理数据库的读写模式是"低频写入、分析查询为主"，服务对象是开发者/研究者；合同业务数据库（如果未来 `ContractManager` 真的要从文件系统迁移到数据库）的读写模式是"高频读写、事务性为主"，服务对象是最终业务用户（律师）。两者的数据生命周期、访问模式、权限模型都不同，混在一个数据库里会让后续运维/权限设计变复杂，且当前两者在代码层面（`contract/manager.py` vs `experiment_kb/`）已经是完全独立的两套系统，分离数据库不会增加额外耦合。

## 结论（本节不涉及实施）

以上是基于本轮真实证据（`RAG_EXPERIMENT_REGISTER.csv` 全文、`contract/manager.py` 全文、实际目录结构）推导出的**调研结论**，不是实施计划，也没有任何代码产出。是否、何时启动实施，等你和 ChatGPT 讨论后再决定下一轮任务范围。
