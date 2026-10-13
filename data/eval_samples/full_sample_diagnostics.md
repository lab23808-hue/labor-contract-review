# 全部 315 条样本检索诊断摘要

运行时间（UTC）：2026-10-11T14:05:53.366228+00:00

检索策略：char_bigram BM25（保留版生产候选策略，k1=1.5, b=0.75）；生产 top_k=5；candidate_k=20

总样本数：315（有标签 188 / 无标签 127）

## 状态分布（二值分类：是否全部标准相关法条都命中）

| 状态 | 数量 |
|---|---:|
| no_gold_label_needs_review | 127 |
| verified_hit_top20_only | 12 |
| verified_hit_top5 | 173 |
| verified_miss | 3 |

### 状态定义（必须严格按下面的语义理解，不要只看名字猜）

- `verified_hit_top5`：**Top-5 内命中了该样本全部标准相关法条**（多标签样本要求全部命中，不是至少命中一条）。
- `verified_hit_top20_only`：**Top-5 未能命中全部标准相关法条**，但 Top-20 内能够全部找全。这里的"Top-5 未能全部命中"包含两种真实情况——Top-5 一条都没命中（零命中），或者 Top-5 命中了一部分、但没有命中全部（部分命中）——这个状态本身不区分这两种情况，下面的「Top-5 命中情况三态分布」才区分。
- `verified_miss`：candidate_k=20 内也没有找到任何一个标准相关法条。
- `no_gold_label_needs_review`：没有标准答案可比对，不代表检索错误，不参与任何命中/漏检判定，需要人工核验后才能转入可计算指标的样本集。

## Top-5 命中情况三态分布（互斥、覆盖全部 188 条有标签样本）

这组统计直接从「Top-5 实际检索结果」与「标准相关法条集合」的交集数量计算，不从上面的状态名称反推，和状态分布是两个角度的统计：

| 分类 | 定义 | 数量 |
|---|---|---:|
| `zero_hit`（零命中） | Top-5 内一条标准相关法条都没找到 | 7 |
| `partial_hit`（部分命中） | Top-5 内命中了至少一条，但没有找全 | 8 |
| `all_hit`（全部命中） | Top-5 内找全了该样本的全部标准相关法条 | 173 |

校验：`all_hit`（173）应等于上面状态分布里的 `verified_hit_top5`（173）——两者算法不同（一个是直接计数交集，一个是 `_score()` 的 recall==1.0），脚本内置了断言保证二者永远一致，不一致会直接报错而不是悄悄产出矛盾数字。`zero_hit + partial_hit` 对应`verified_hit_top20_only + verified_miss` 的样本集合（但不是逐一相等，因为 `verified_hit_top20_only`/`verified_miss` 的区分依据是 Top-20 能不能找全，不是 Top-5 命中了几条）。

## Recall@5 宏平均 与 verified_hit_top5 计数 不是同一个指标

- Recall@5 宏平均（逐样本 `命中数/标准相关法条总数` 取平均）= **0.9468**，这个数字和 01-07 轮实验里 BM25 char_bigram 在 188 条口径下报告的 Recall@5 应该完全一致（历史真实数字见 `docs/RAG_EXPERIMENTS.md` 表 B/C）。
- `verified_hit_top5` 计数占比（173/188 = 0.9202）是二值计数（全部命中才算1，部分命中算0），**不等于**上面的 Recall@5 宏平均，两者是不同的统计量，不能互相替代或换算——差值正好等于所有 `partial_hit` 样本贡献的部分召回分数之和除以总样本数。

完整逐条记录（含 `relevant_hit_count_top5/top20`、`zero_hit_top5/top20`、`partial_hit_top5/top20`、`all_hit_top5/top20` 等新增字段）见同名 `.json` 文件，不在此 Markdown 中展开。