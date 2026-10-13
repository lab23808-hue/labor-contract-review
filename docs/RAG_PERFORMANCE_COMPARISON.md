# RAG 检索策略质量与真实耗时对照表

> 新建独立文件，不覆盖任何历史文档。完整结构化数据见
> [`experiment_kb/results/RAG_PERFORMANCE_COMPARISON.csv`](../experiment_kb/results/RAG_PERFORMANCE_COMPARISON.csv)（20行：working/baseline两个知识库 × Dense/BM25/RRF三策略 × K=5/10/20，加上每个知识库各一行hybrid串行端到端总耗时）。
> 数据来源：`experiment_kb/results/working_kb_retrieval_experiment_20261012_150058_char_bigram.json`（37条Evidence）、
> `experiment_kb/results/baseline_kb_retrieval_experiment_20261012_151710_char_bigram.json`（26条Evidence）。
> 本轮未重新运行质量实验（Recall/MRR/nDCG直接复用上述两份已核验一致的真实结果文件），只新增了耗时口径的整理和注明；
> 细粒度的Dense embedding-only/向量检索-only、BM25分词-only/排名-only拆分**在已有结果文件中不存在**，
> 已新增补测脚本 `experiment_kb/scripts/eval_timing_breakdown.py`，**待用户在本机运行**（见第4节），本次未在云端执行。

---

## 0. 数据规模与指纹（两个知识库严格分开，不混成一组）

| 项目 | working（37条Evidence，本session当前候选知识库） | baseline（26条Evidence，历史对照基线） |
|---|---|---|
| Evidence数量 | 37 | 26 |
| 知识库路径 | `experiment_kb/working/` | `experiment_kb/baseline/` |
| 快照指纹(`snapshot_check.before_run.current_fingerprint`，覆盖knowledge+eval+config整体) | `1bf38ca720fd65f8b0de3e4f0a42c8a0e68bdd2908ecd49e6469afccc00c894c` | `5ea17f262959b4a5665e720ba9b33b9d4196179ffa4ba3c7bd52f41115b9f505` |
| 评估数据文件 | `experiment_kb/working/data/eval_samples/retrieval_eval_samples.json` | `experiment_kb/baseline/data/eval_samples/retrieval_eval_samples.json`（内容与working一致，运行前后均核验未变） |
| 原始有效评估样本数(evaluable=true) | 188 | 188 |
| 独立Query-标签场景数 | 47 | 47 |
| 数据来源合同数量 | 未在本结果文件单独统计（315条样本来自50份评估合同，见`docs/RAG_EXPERIMENTS.md`第一节；本次漏检分析按contract_sample_id去重后的合同数见`RAG_MISS_ANALYSIS.csv`） | 同左 |
| 分词器 | char_bigram（forced via --tokenizer char_bigram） | char_bigram（forced via --tokenizer char_bigram） |
| candidate_k | 20 | 20 |
| rrf_k | 60 | 60 |

> **说明**：此处的快照指纹与`experiment_kb/results/RAG_EXPERIMENT_REGISTER.csv`/`RAG_COMPLETE_EXPERIMENT_DATA.csv`里记录的`kb_fingerprint`/`eval_fingerprint`（如working的`5bce72e5...`、baseline的`f9a4897645...`）是**不同的指纹函数**算出来的（本表引用的是`build_snapshot_fingerprint.py`的整体快照指纹，用于运行前后"内容是否被改动"的核验；register.csv里的是另一套用于"Dense结果是否可复用"判断的知识内容/评估集指纹）。两者本轮未互相核对是否一致，只是分别如实引用各自来源的真实字段，不代表矛盾或错误。

---

## 1. 质量指标（Recall / MRR / nDCG，两种口径都保留）

### 1.1 working（37条Evidence）

**原始样本口径（188条，macro平均）：**

| 策略 | K | Recall | MRR | nDCG |
|---|---:|---:|---:|---:|
| Dense | 5 | 0.7766 | 0.5771 | 0.6205 |
| Dense | 10 | 0.9681 | 0.6037 | 0.6852 |
| Dense | 20 | 0.9787 | 0.6047 | 0.6887 |
| BM25(char_bigram) | 5 | 0.9468 | 0.8644 | 0.8797 |
| BM25(char_bigram) | 10 | 0.9548 | 0.8644 | 0.8834 |
| BM25(char_bigram) | 20 | 0.9920 | 0.8663 | 0.8929 |
| RRF(char_bigram) | 5 | 0.9388 | 0.7314 | 0.7789 |
| RRF(char_bigram) | 10 | 0.9707 | 0.7360 | 0.7900 |
| RRF(char_bigram) | 20 | 0.9920 | 0.7370 | 0.7966 |

**独立场景口径（47个，等权重）：**

| 策略 | K | Recall | MRR | nDCG |
|---|---:|---:|---:|---:|
| Dense | 5 | 0.9238 | 0.7606 | 0.7892 |
| Dense | 10 | 0.9557 | 0.7637 | 0.8015 |
| Dense | 20 | 0.9716 | 0.7649 | 0.8070 |
| BM25(char_bigram) | 5 | 0.9344 | 0.9007 | 0.9020 |
| BM25(char_bigram) | 10 | 0.9468 | 0.9007 | 0.9080 |
| BM25(char_bigram) | 20 | 0.9894 | 0.9030 | 0.9190 |
| RRF(char_bigram) | 5 | 0.9238 | 0.7553 | 0.7887 |
| RRF(char_bigram) | 10 | 0.9610 | 0.7607 | 0.8024 |
| RRF(char_bigram) | 20 | 0.9894 | 0.7621 | 0.8112 |

### 1.2 baseline（26条Evidence，历史对照基线，不与working混合统计）

**原始样本口径（188条）：**

| 策略 | K | Recall | MRR | nDCG |
|---|---:|---:|---:|---:|
| Dense | 5 | 0.9628 | 0.6290 | 0.7055 |
| Dense | 10 | 0.9707 | 0.6290 | 0.7095 |
| Dense | 20 | 0.9840 | 0.6301 | 0.7137 |
| BM25(char_bigram) | 5 | 0.9468 | 0.8644 | 0.8797 |
| BM25(char_bigram) | 10 | 0.9840 | 0.8681 | 0.8928 |
| BM25(char_bigram) | 20 | 0.9920 | 0.8681 | 0.8953 |
| RRF(char_bigram) | 5 | 0.9707 | 0.7394 | 0.7944 |
| RRF(char_bigram) | 10 | 0.9761 | 0.7394 | 0.7966 |
| RRF(char_bigram) | 20 | 0.9920 | 0.7404 | 0.8013 |

**独立场景口径（47个）：**

| 策略 | K | Recall | MRR | nDCG |
|---|---:|---:|---:|---:|
| Dense | 5 | 0.9450 | 0.7713 | 0.8033 |
| Dense | 10 | 0.9610 | 0.7713 | 0.8113 |
| Dense | 20 | 0.9787 | 0.7728 | 0.8169 |
| BM25(char_bigram) | 5 | 0.9344 | 0.9007 | 0.9020 |
| BM25(char_bigram) | 10 | 0.9787 | 0.9050 | 0.9184 |
| BM25(char_bigram) | 20 | 0.9894 | 0.9050 | 0.9218 |
| RRF(char_bigram) | 5 | 0.9610 | 0.7677 | 0.8097 |
| RRF(char_bigram) | 10 | 0.9681 | 0.7677 | 0.8126 |
| RRF(char_bigram) | 20 | 0.9894 | 0.7691 | 0.8189 |

**两个知识库版本的质量指标严格分表展示，未合并成一组"公平对照"数字**——如需比较26→37条Evidence后的变化，请对照同一策略、同一K值的两张表分别读数（例如：BM25在两个知识库下数值完全相同；Dense在K=5层面下降明显，完整定点归因见`docs/RAG_COMPLETE_EXPERIMENT_DATA.md`第4节与`experiment_kb/results/DENSE_RECALL5_DIAGNOSIS.md`，本文件不重复推导过程）。

---

## 2. 真实运行耗时（与质量指标同一张对照表的耗时列，已有数据部分）

### 2.1 working（37条Evidence）

| 策略 | 平均单Query耗时 | P50 | P95 | 47场景总耗时 | 计时边界说明 |
|---|---:|---:|---:|---:|---|
| Dense | 0.1193s | 0.1079s | 0.1778s | 5.609s | **合并计时**：embed_query+向量检索一次调用内完成，未拆分，见第4节补测脚本 |
| BM25(char_bigram) | 0.0001s | 0.0001s | 0.0002s | 0.005s | **合并计时**：分词(含规范化，代码里无独立规范化步骤)+BM25排名一次调用内完成，未拆分 |
| RRF(char_bigram) | N/A(非单一Query延迟分布) | N/A | N/A | 0.002s(仅融合本身) | RRF耗时=Dense通道total(5.609s)+BM25通道total(0.005s)+融合total(0.002s)=**5.616s串行端到端**；真正的并行耗时`parallel_total_seconds: null`，**明确NOT_MEASURED**，不得用5.616s当作并行结果 |

索引构建/更新/删除：Dense构建14.013s(37篇)，更新单条0.262s；**删除**——working主实验JSON记录的是修复前的AttributeError失败记录（如实保留未覆盖），真实修复验证后的删除耗时见独立测试`dense_delete_test_20261012_150149.json`：**0.019s**（37→36，`delete_verified_correct: true`）。BM25构建0.001s，更新0.001s，删除0.001s。冷启动(BGE-M3模型加载)：12.977s。

### 2.2 baseline（26条Evidence）

| 策略 | 平均单Query耗时 | P50 | P95 | 47场景总耗时 | 计时边界说明 |
|---|---:|---:|---:|---:|---|
| Dense | 0.1458s | 0.1316s | 0.2266s | 6.851s | 合并计时，同上口径 |
| BM25(char_bigram) | 0.0001s | 0.0001s | 0.0003s | 0.005s | 合并计时，同上口径 |
| RRF(char_bigram) | N/A | N/A | N/A | 0.002s(仅融合) | 串行端到端=6.851+0.005+0.002=**6.858s**；并行NOT_MEASURED |

索引：Dense构建10.863s(26篇)，更新0.247s，删除0.018s（本轮Dense为真实强制重跑，未复现working那边的旧AttributeError记录，删除代码路径本身已修复）。BM25构建0.002s，更新0.001s，删除0.001s。冷启动：11.728s。

**working比baseline耗时更长是否"公平"？** Dense单Query耗时working(0.1193s均值)比baseline(0.1458s均值)反而更短——**不能解读为"37条比26条更快"**，这组数字本身受模型冷启动后GPU/CPU状态、系统负载等未控制变量影响，当前只有每个知识库各一次运行的数据，没有重复多次取统计量，**标记为NOT_COMPARABLE_WITHOUT_MORE_RUNS**（样本量n=1次run，不是n=47次独立重复实验的严格统计比较）；47个Query各自的延迟分布(P50/P95)在"同一次run内部"是有效的相对比较，但"working run"和"baseline run"是两次不同时间点的进程，之间的耗时差不能排除环境噪声。

---

## 3. 尚未满足"统一比较条件"、按规则标记NOT_COMPARABLE的项目

| 缺口 | 现状 | 标记 |
|---|---|---|
| Dense：Query Embedding 耗时 vs 向量检索耗时 | 已有结果文件只有合并耗时(`dense_query_embedding_and_retrieval`)，两步在`rag/database.py`的`similarity_search()`内部一次调用完成，没有分别计时 | `NOT_MEASURED`——已写补测脚本`eval_timing_breakdown.py`，见第4节，待本机运行 |
| BM25：Query规范化 vs 分词 vs 排名 | 当前`char_bigram_baseline`实现里规范化和分词是同一步（过滤空白后直接两两配对），代码里没有独立的规范化子步骤；已有结果文件的`bm25_tokenization_and_ranking`是"分词+排名"合并耗时 | 规范化：`NOT_MEASURED_NO_SEPARATE_STEP_IN_CODE`（不是漏测，是代码没有这一步）；分词vs排名两段：已在补测脚本中拆分，待本机运行 |
| RRF：真正并行端到端耗时 | 脚本里Dense/BM25候选是两个独立串行循环产生的，不是真正用线程池并发测的 | `NOT_MEASURED`，且已有结果文件和本文件都未用串行数字冒充并行结果 |
| 跨working/baseline的Dense单Query耗时严格对比 | 每个知识库只运行了一次（n=1 run），没有重复多次 run 来排除环境噪声 | `NOT_COMPARABLE_WITHOUT_MORE_RUNS`（第2.2节已注明） |
| 数据来源合同数量（Task 1范围内） | 本结果文件级别未单独统计；合同去重统计见`RAG_MISS_ANALYSIS.csv`（Task 2产出） | 见Task 2文件，Task 1本身不重复统计 |

---

## 4. 补测脚本（已新增，待用户在本机运行）

`experiment_kb/scripts/eval_timing_breakdown.py` ——只补测缺失的耗时拆分，**不重新计算Recall/MRR/nDCG**（质量指标继续使用本文件第1节已复用的真实结果），不重新实现知识库加载/BM25算法/Dense检索调用本身（直接`import eval_working_kb_retrieval as base`复用其函数和模块全局变量）。

**它做的事**：
- Dense：单独计时`embedder.embed_query(query)`（embedding-only）和`kb._store._collection.query(query_embeddings=[已算好的向量], n_results=candidate_k)`（vector_search-only，用标准chromadb Collection公开方法，不重复计算embedding），避免"分开计时却重复付一次embedding成本"污染向量检索那一段。
- BM25：单独计时`tokenize(query)`（分词，含规范化，因代码无独立规范化步骤）和打分+排序循环（与`_BM25Index.search()`内部逐行一致，未改算法）。
- 运行前后复用主脚本的知识库/评估集指纹核验，不一致直接中止。
- 默认重复扫描47个Query共3轮（`--repeats 3`），既给出"不同Query单次延迟分布"(P50/P95)，也给出"同一Query重复3次"的标准差（`same_query_repeat_stability`字段），两种统计分开标注，不混淆。
- 产出独立文件`experiment_kb/results/timing_breakdown_{working|baseline}_{时间戳}.json`，不覆盖任何历史结果。

**运行方式**（需在用户本机已配置好的venv里，真实BGE-M3+网络环境下运行；本次云端沙箱不执行，原因与此前所有BGE-M3相关实验相同——沙箱DNS/代理策略拒绝chromadb/BGE-M3相关依赖的网络访问，已在此前多轮中反复确认）：

```
python experiment_kb/scripts/eval_timing_breakdown.py --kb-source working
python experiment_kb/scripts/eval_timing_breakdown.py --kb-source baseline
```

运行后请把真实输出路径和终端打印的P50/P95粘贴回来，我会把结果核对后补充进本文件（新增章节，不覆盖已有内容）。
