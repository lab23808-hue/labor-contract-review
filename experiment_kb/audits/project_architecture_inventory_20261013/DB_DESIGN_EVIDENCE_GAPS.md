# 数据库设计实际依据（补查轮，2026-10-14）

基于本轮新增证据（`RAG_HUMAN_REVIEW_BATCH1.xlsx` 全量读取、`scripts/README.md` 全文、6个脚本全文/docstring读取、`RAG_EXPERIMENT_REGISTER.csv` 全文——后者为上一轮已读）回答用户提出的7个问题。不实施任何代码，仅给出调研结论。

## 1. 哪些现有数据文件应当作为原始记录保留（CONFIRMED为主）

- `data/knowledge/*.txt`（生产26条Evidence源文件）——原始法律文本，不可再生成（内容来自官方法律条文，非程序生成）。
- `data/eval_samples/contracts/*.txt` + `answers/*.json`（50份合成合同+标准答案）——CONFIRMED（上轮A003已确认）是 `evaluation/generate_contracts.py` 程序化生成，**理论上可重新生成**，但由于 `scripts/README.md` 明确警告"后续所有实验共用的固定输入"，且本轮未核实 `generate_eval_contracts.py` 是否带随机种子保证可复现同一批内容，**实践中应当视为原始记录对待**（一旦重新生成且种子/版本不同，所有历史实验的 gold_answer_content_fingerprint 会失配）。
- `data/eval_samples/retrieval_eval_samples.json`——本轮确认其生成脚本 `build_retrieval_eval_samples.py` 会**覆盖写**此文件，且 README 原话"不要随便重跑覆盖"——这是一份事实上的原始记录，即便理论上可重新生成。
- `RAG_HUMAN_REVIEW_BATCH1.xlsx`——即使当前内容全部是 pending（未完成人工核验），这份文件本身记录了"候选法条+AI置信度+不确定性原因"这一组**不可重新生成的、针对特定11个样本的人工审查工作底稿**，一旦完成人工确认（填入human_confirmed_evidence_ids），其价值不可替代。
- `RAG_EXPERIMENT_REGISTER.csv`——不可重新生成（本轮上一轮已确认，部分实验标注"用户本机venv(Windows)"真实环境，云端无法复现其耗时类数字）。

## 2. 哪些数据是可重新生成的派生结果（CONFIRMED为主）

- `parsed_text.txt`/`clauses.json`（合同解析/切分产物）——`contract/manager.py` 代码明确允许覆盖。
- `experiment_kb/results/` 下各带时间戳的实验JSON/MD——理论可重新生成，但**前提是知识库+评估数据集指纹不变**（本轮读到的 `eval_working_kb_retrieval.py`/`eval_timing_breakdown.py` 都在运行前显式校验指纹，指纹不一致会直接中止，这是一个很强的"可复现性守门"机制，CONFIRMED）。
- `experiment_kb/tmp_runtime/` 下的临时Dense索引——明确是派生/临时产物，脚本本身设计为运行后清理（只是历史运行中部分未清理干净，残留至今）。
- `data/chroma/`——当前非生产强依赖路径（BM25是默认策略），理论可重建。

## 3. 哪些文件代表一个数据集/一次实验/一个知识库版本/一个人工标注版本（CONFIRMED，本轮新增证据）

- **数据集**：`retrieval_eval_samples.json`（本轮确认其 `gold_answer_content_fingerprint` 字段，由 `build_snapshot_fingerprint.py` 计算，显式排除 `generated_at` 等元数据——这是数据集版本的真实、已实现的指纹机制）；`experiment_kb/datasets/contract_eval_500_20261013/source_450/manifest_450.csv`（450份合同清单）。
- **一次实验**：`RAG_EXPERIMENT_REGISTER.csv` 的每一行（`experiment_id`），对应一个 `json_path`+`md_path` 产出对。
- **一个知识库版本**：`experiment_kb/snapshots/{baseline,working}_snapshot.json`（本轮确认是 `build_snapshot_fingerprint.py` 的产出格式：`knowledge_snapshot_fingerprint`=文件级哈希+Evidence级哈希的组合）；A006的 `kb_version_manifest.csv`（26/37/44三版本的 `evidence_set_hash`）。
- **一个人工标注版本**：目前**只有** `RAG_HUMAN_REVIEW_BATCH1.xlsx` 这一个实例，且其中全部11行仍为 pending——换言之，"人工标注版本"这个实体类型当前在项目里**只有一份"第0版"（待完成）**，没有任何"已完成"的标注版本可以参照建模。

## 4. 当前是否存在可用且可信的人工核验数据（CONFIRMED，本轮核心新发现）

**不存在。** 本轮全量读取 `RAG_HUMAN_REVIEW_BATCH1.xlsx` 确认：11行全部 `human_review_status=pending`，`human_confirmed_evidence_ids` 全部为空，0条记录完成人工确认。叠加上一轮已确认的 `candidate_labels_pending_review.csv`（450份合同候选标签）和 `retrieval_eval_samples.json`（188条现有样本标签）的 `verification_status` 字段——上一轮A003已记录"315条款中只有candidate(309)和pending_review(6)两种取值，无一条verified"——**三份数据源的结论完全一致**：当前项目里不存在任何已经过人工确认的法律依据标注，所有现有指标（Recall/MRR/nDCG等）都是基于AI生成的候选标签计算的，**不是基于gold standard计算的**，这是对未来DB设计和所有已发布指标诚实性都至关重要的证据。

## 5. 注册表、清单、原始JSON、排名CSV之间的实际可建立关联键（CONFIRMED+INFERRED）

| 关联 | 关联键 | 可靠性 |
|---|---|---|
| `RAG_EXPERIMENT_REGISTER.csv`行 ↔ 其 json_path/md_path | 文件路径字符串 | CONFIRMED存在,但是路径字符串而非ID引用,目录改名会断链(上一轮已指出) |
| `experiment_kb/snapshots/*.json` ↔ `RAG_EXPERIMENT_REGISTER.csv`的kb_fingerprint字段 | 指纹哈希值字符串比对 | CONFIRMED可行(本轮读取build_snapshot_fingerprint.py确认两者用的是同一套哈希算法) |
| `retrieval_eval_samples.json`的sample_id ↔ `RAG_HUMAN_REVIEW_BATCH1.xlsx`的contract_id+clause_id | 需要拼接`{contract_id}::{clause_id}`格式(本轮确认build_retrieval_eval_samples.py正是用这个格式生成sample_id) | CONFIRMED对于xlsx里5行有真实ID的记录；UNKNOWN对于6行占位描述文字记录 |
| `manifest.json`的sample_id ↔ `RAG_HUMAN_REVIEW_BATCH1.xlsx`的contract_id | 字符串直接相等 | CONFIRMED(本轮实测5/5匹配) |
| A006的`kb_version_manifest.csv` ↔ `rank_change_detail.csv` | query+target的复合键(推断) | INFERRED(上一轮已指出,本轮未新增验证) |

## 6. 数据库应登记哪些元数据，哪些大型文件仍保存在文件系统（INFERRED，延续上轮FUTURE_DB设计并补充本轮证据）

**登记进数据库**：`experiment_id`/`dataset`指纹/`kb_version`指纹/`Metric`数值(拆分后的窄表)/`Artifact`路径+哈希/`AnnotationStatus`(本轮新确认：当前这张表应该长期保持"大部分candidate/pending，极少verified"的真实分布，而不是假设未来会很快变成"主要verified")。

**仍留在文件系统**：`bm25_run_result.json`(3.1MB)等大型原始候选明细；`RAG_HUMAN_REVIEW_BATCH1.xlsx`本身（作为人工工作底稿，人工复核流程通常更适合继续用表格工具而不是数据库表单，数据库只登记它的路径+行数+状态分布摘要）；`data/eval_samples/retrieval_eval_samples.json`等数据集原始内容。

## 7. 现有文件导入数据库时，哪些可自动迁移/哪些需人工确认/哪些暂不能导入（INFERRED，基于本轮证据的新结论）

**可自动迁移**：`RAG_EXPERIMENT_REGISTER.csv` 里结构清晰的字段（experiment_id/run_at_utc/kb_path/evidence_count/sample_count等）——可以写脚本直接解析成 `ExperimentRun` 行；`experiment_kb/snapshots/*.json` 的指纹字段可直接映射成 `KnowledgeBaseVersion` 行。

**需要人工确认**：`RAG_EXPERIMENT_REGISTER.csv` 里被"字段过载"的那些混合字符串字段（如A005/A006行的`recall_at_5`），必须人工逐行拆解成多条`Metric`记录才能导入，不能靠正则自动解析（字符串格式本身不统一）；`RAG_HUMAN_REVIEW_BATCH1.xlsx`当前全部pending，**不建议现在导入**到`AnnotationStatus`表（会让数据库里出现大量"状态未定"的占位记录，不如等第一批人工复核真正完成后再导入有意义的结果）。

**暂时不能导入**：6行占位描述文字（`RAG_HUMAN_REVIEW_BATCH1.xlsx`里缺少真实ID的那部分），因为缺少可靠的主键，导入前必须先人工把描述文字映射成真实`sample_id`；`scripts/README.md`里README自述但本轮未读源码确认的21个脚本的运行记录——这些脚本"是否曾经运行过、产出了什么"目前没有任何机器可读的记录（不像`experiment_kb/scripts`的3个脚本那样有本会话内的真实执行记录），无法确认是否存在遗漏的历史`ExperimentRun`需要补登。

## 本轮实际读取范围声明

**全量读取**：`RAG_HUMAN_REVIEW_BATCH1.xlsx`（2个工作表全部15行）、`scripts/README.md`（全文）、`scripts/build_snapshot_fingerprint.py`（全文，并与`experiment_kb/build_snapshot_fingerprint.py`做字节级diff确认完全一致）、`scripts/build_retrieval_eval_samples.py`（全文）、`scripts/compare_eval_results.py`（全文）、`scripts/validate_knowledge_base.py`（全文）、`data/eval_samples/manifest.json`（全文，用于交叉核实xlsx的contract_id）。

**部分读取**：`experiment_kb/scripts/eval_working_kb_retrieval.py`（53060B，只读了docstring+前120行的import部分，未读完整实现）、`experiment_kb/scripts/eval_timing_breakdown.py`（17929B，读了docstring+前100行）。

**未读取**（按用户"不机械逐一深读不相关脚本"的指令，仅转述`scripts/README.md`自述内容，标注REPORTED，不冒充CONFIRMED）：`_common.py`/`_samples.py`/`_jieba_probe_tmp.py`/`build_knowledge_base.py`/`eval_retrieval_baseline.py`/`eval_retrieval_topk_experiment.py`/`eval_retrieval_strategy_experiment.py`（46811B，体量最大，建议下一轮优先读取，因为是04-09号实验的共享基础模块）/`eval_bm25_tokenizer_experiment.py`/`eval_bm25_preprocessing_experiment.py`/`eval_bm25_boundary_experiment.py`/`eval_full_sample_diagnostics.py`（建议优先，因其产出被本轮数据盘点多次引用）/`eval_weighted_rrf_experiment.py`/`generate_eval_contracts.py`（建议优先，因疑似会覆盖现有50份评估合同，风险较高）/`run_eval_samples.py`（建议优先，是端到端诊断链路入口）/全部9个`verify_*.py`验证脚本。

**未执行的检查**：未打开 `retrieval_eval_samples.json`/`clauses.json`/`data/eval_samples/answers/*.json` 去定位xlsx里6行占位描述文字对应的真实sample_id；未对A006的`kb_version_manifest.csv`与`rank_change_detail.csv`的关联键做实际的逐行验证（仍是INFERRED）。

本轮到此停止。未开始任何数据库开发，未执行任何RAG实验，未清理或迁移任何现有数据。
