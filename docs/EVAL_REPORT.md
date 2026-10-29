# 评估报告

## 1. 主评估（50 份合同，fake LLM，BM25）

- 运行时间：2026-10-29
- 检索策略：`bm25`
- Fake LLM：`True`
- 合同数：50

| 指标 | 值 |
|---|---:|
| Recall@5 | 0.9603 |
| MRR@5 | 0.7479 |
| 有 gold 的条款数 | 50 |
| 规则 precision | 1.0 |
| 规则 recall | 0.8824 |
| 规则 false_positive | 0 |
| 规则 missed | 2 |
| LLM risk 一致率 | 0.8571 |
| LLM risk_level 一致率 | 0.8571 |
| 可对齐条款数 | 315 |

> fake-llm 模式下 LLM 始终返回 none，LLM 指标不代表真实模型质量。

## 2. 检索策略对比（10 份合同，fake LLM）

为保证三组可比，三组使用同一批前 10 份合同；数字来自 `data/eval_results/eval_report_{bm25,dense,hybrid}.json`。

| 策略 | Recall@5 | MRR@5 | 条款数 |
|---|---:|---:|---:|
| BM25 | 0.8667 | 0.6650 | 10 |
| Dense | 1.0000 | 0.6343 | 10 |
| Hybrid + RRF | 1.0000 | 0.6994 | 10 |

观察：

- 在这 10 份合同上，Dense/Hybrid 的 Recall@5 都达到 1.0，BM25 为 0.8667。
- Hybrid 的 MRR@5（0.6994）高于 Dense（0.6343）和 BM25（0.6650）。
- 样本只有 10 份，不能外推为全量结论；50 份 BM25 的 Recall@5/MRR@5 分别为 0.9603 / 0.7479。

## 3. 说明

- 检索 gold：`ClauseAnswer.legal_basis` 中的 `article` 是否出现在该条款 top-5 Evidence 的 `article` 中。
- 规则指标复用 `evaluation.diagnostics.experiment6_rule_layer_check`。
- LLM 指标是 fake LLM 与标准答案的 risk / risk_level 一致率，不代表真实模型质量。
