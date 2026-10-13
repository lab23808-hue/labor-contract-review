# scripts/ 目录索引

本文件只回答三个问题：**这个脚本是什么、怎么运行、结果存在哪里**。背景、控制变量、
真实指标和决策依据不在这里重复，统一记录在 [`docs/RAG_EXPERIMENTS.md`](../docs/RAG_EXPERIMENTS.md)。

## 为什么没有把 RAG 实验脚本物理搬进 `scripts/rag_eval/`

考虑过按经验里建议的逻辑顺序迁移到一个子目录，但检查后发现下面 7 个 RAG 检索实验脚本
全部在脚本顶部用

```python
PROJECT_ROOT = Path(__file__).resolve().parent.parent
```

硬编码"自己在 `scripts/` 正下方、项目根目录是上两级"这个假设，`eval_bm25_tokenizer_experiment.py`
/ `eval_bm25_preprocessing_experiment.py` / `eval_bm25_boundary_experiment.py` 还额外用
`importlib.import_module("eval_retrieval_strategy_experiment")` 这种裸模块名互相导入
（靠 `sys.path.insert(0, SCRIPTS_DIR)` 生效）。如果把它们搬到 `scripts/rag_eval/`，
`PROJECT_ROOT` 会算错一层，`from config import settings` 等导入会全部失败，必须逐个改
路径计算逻辑——这正是"移动风险高"的情况。按整理任务里给出的原则：**移动风险高就不强行
迁移，用目录分组和索引文档完成组织**。所以这 7 个脚本原地不动，下面的表格就是分组后的
逻辑顺序索引。

## RAG 检索实验脚本（按实验逻辑顺序，不是文件名顺序）

全部从**项目根目录**运行，例如 `python scripts/eval_retrieval_strategy_experiment.py`。

| 顺序 | 脚本 | 作用 | 运行方式 | 结果目录 |
|---|---|---|---|---|
| 01 | `build_retrieval_eval_samples.py` | 从 `data/eval_samples/` 下的 50 份合同标准答案构建固定检索评估样本（315 条，188 条有 `legal_basis` 标签） | `python scripts/build_retrieval_eval_samples.py` | 覆盖写 `data/eval_samples/retrieval_eval_samples.json`（这是后续所有实验共用的固定输入，不要随便重跑覆盖） |
| 02 | `eval_retrieval_baseline.py` | 测量 Dense（真实 BGE-M3）Top-5 基线 | `python scripts/eval_retrieval_baseline.py [--limit N] [--output PATH]` | `data/eval_samples/results/retrieval_baseline_<时间戳>.json` |
| 03 | `eval_retrieval_topk_experiment.py` | 对比 Dense Top-5/10/20，决定是否继续扩大 Top-K | `python scripts/eval_retrieval_topk_experiment.py [--output PATH]` | `data/eval_samples/results/retrieval_topk_experiment_<时间戳>.json` |
| 04 | `eval_retrieval_strategy_experiment.py` | 对比 Dense、BM25（自实现 BM25Okapi）、对称 RRF 三种策略；**04-07 四个脚本的共享基础模块**，被下面三个脚本用 `importlib.import_module` 原样复用（样本/场景加载、知识库切分、BM25 索引、RRF 融合、评分公式） | `python scripts/eval_retrieval_strategy_experiment.py [--dense-results PATH] [--force-rerun-dense] [--rrf-k 60] [--output PATH]` | `data/eval_samples/results/retrieval_strategy_experiment_<时间戳>.json/.md` |
| 05 | `eval_bm25_tokenizer_experiment.py` | 对比 BM25 分词器：`char_bigram`（保留版）vs `jieba`；同时定义了 `BM25_K1`/`BM25_B` 常量和 `_run_one_tokenizer()` 通用跑分函数，被 06/07 复用 | `python scripts/eval_bm25_tokenizer_experiment.py` | `data/eval_samples/results/bm25_tokenizer_experiment_<时间戳>.json/.md` |
| 06 | `eval_bm25_preprocessing_experiment.py` | 对比 BM25 文本预处理：`char_bigram_baseline`（保留版）vs `char_bigram_clean`（清理标点/空白） | `python scripts/eval_bm25_preprocessing_experiment.py` | `data/eval_samples/results/bm25_preprocessing_experiment_<时间戳>.json/.md` |
| 07 | `eval_bm25_boundary_experiment.py` | 对比 BM25 跨空白边界处理：`char_bigram_baseline`（保留版）vs `char_bigram_boundary_aware`（分段后段内配对） | `python scripts/eval_bm25_boundary_experiment.py` | `data/eval_samples/results/bm25_boundary_experiment_<时间戳>.json/.md` |
| 08 | `eval_full_sample_diagnostics.py` | 对**全部 315 条**样本（不止 188 条有标签的）用保留版 BM25 跑 Top-5/Top-20 诊断，区分「可计算核心指标」和「无标签待复核」两类 | `python scripts/eval_full_sample_diagnostics.py` | `data/eval_samples/full_sample_diagnostics.json/.md` |
| 09 | `eval_weighted_rrf_experiment.py` | 对比 4 组 Dense/BM25 权重比例（1:1/2:1/1:2/1:3）下的加权 RRF 融合效果，**直接复用 04 号实验已有的真实候选列表，不重新调用 BGE-M3/Chroma/BM25** | `python scripts/eval_weighted_rrf_experiment.py [--input PATH] [--rrf-k 60]` | `data/eval_samples/results/weighted_rrf_experiment_<时间戳>.json/.md` |
| 10（预留） | 后续其他实验 | 尚未建立。新脚本请遵循同一套规范（见 `docs/RAG_EXPERIMENTS.md` 第五节「未来规范」），文件名建议延续 `eval_*_experiment.py` 的命名方式 | — | — |

辅助脚本：

| 脚本 | 用途 | 状态 |
|---|---|---|
| `_jieba_probe_tmp.py` | 05 轮实验里一次性获取真实 `jieba.cut()` 分词样例用的临时诊断脚本，不是正式实验脚本，不计入上面的编号序列 | 仅在用户本机留存，未同步到本仓库副本；需要复现时可以直接 `import jieba` 手动跑 `jieba.cut(text)` 替代 |

每个脚本更详细的"解决什么问题 / 控制变量 / 真实结论"记录在 `docs/RAG_EXPERIMENTS.md`，这里不重复。

## 其他脚本（非 RAG 检索实验，本次整理未触碰，原样列出方便查找）

| 脚本 | 用途 |
|---|---|
| `_common.py` | `scripts/` 下各真实环境脚本共用的小工具（真实 BGE-M3 探测、正式知识库只读打开），只服务于 `scripts/`，不是生产包依赖 |
| `_samples.py` | `scripts/` 里各验证脚本共用的示例合同文本（自拟文本），按脚本分类存放，不要为了去重合并 |
| `build_knowledge_base.py` | 用真实 BGE-M3 把 `data/knowledge/` 下的法律文本写入正式知识库 `data/chroma` |
| `compare_eval_results.py` | 对比两次 `run_eval_samples.py` 产出的结果 JSON，只做字段对齐和差值计算，不重新跑实验 |
| `generate_eval_contracts.py` | 生成 50 份评估合同样本 + 标准答案的 CLI 入口（真正逻辑在 `evaluation/generate_contracts.py`） |
| `run_eval_samples.py` | 运行 50 份评估合同样本的端到端诊断实验（支持 `--stage`/`--mode offline/online`） |
| `validate_knowledge_base.py` | 不依赖 chromadb/langchain 的知识库纯文本结构校验 |
| `verify_agent_function_calling.py` | ModificationAgent Function Calling 解析逻辑的替代测试（标注为 mock） |
| `verify_di_fix.py` | 验证 `api/dependencies.py` 依赖注入 bug 的修复 |
| `verify_full_pipeline.py` | 完整 LangGraph 流程的真实端到端验证 |
| `verify_modification.py` | ModificationBatch/Task 状态机、Risk Analyzer、V2 Generation 等改动的真实验证 |
| `verify_p24_newline_write.py` | P-24 换行符修复验证（`newline=""`） |
| `verify_rag_pipeline.py` | RAG 真实链路验证（Clause → query → 检索 → Evidence） |
| `verify_real_retrieval.py` | 从已持久化的正式 `data/chroma` 做真实检索验证（只读） |
| `verify_review_pipeline.py` | LLM Review 真实端到端验证 |
| `verify_rules_pipeline.py` | RuleChecker + 结果合并的真实端到端验证 |
| `verify_v2_article_reconstruction.py` | `document/reconstructor.py` 条款重组逻辑的真实验证 |

## 面向初学者的快速上手路径

1. 先看 `docs/RAG_EXPERIMENTS.md` 的"结论速览"表，了解当前检索策略是什么、为什么（BM25 char_bigram，保留原版）。
2. 想复现某一轮实验，按上面 01-08 表格找到脚本，`cd` 到项目根目录直接 `python scripts/<脚本名>.py` 运行。
3. 想看某一轮实验的真实数字和逐场景细节，去 `data/eval_samples/results/` 找对应时间戳的 `.json`/`.md`，不要只看本文件。
4. 想了解某条款在检索里的真实表现（包括没有标准答案的那 127 条），看 `data/eval_samples/full_sample_diagnostics.json`。
5. 想了解哪些漏检模式已经被跟踪、是否该加规则，看 `data/eval_samples/rule_candidate_cases.json`。
