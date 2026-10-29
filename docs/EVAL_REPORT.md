# 评估报告

- 运行时间：2026-10-29T10:42:39.957370+00:00
- 检索策略：`bm25`
- Fake LLM：`True`
- 合同数：50

## 检索指标（gold legal_basis 的 article 是否在 top-5）

| 指标 | 值 |
|---|---:|
| Recall@5 | 0.9603 |
| MRR@5 | 0.7479 |
| 有 gold 的条款数 | 50 |

## 规则层指标

| 指标 | 值 |
|---|---:|
| precision | 1.0 |
| recall | 0.8824 |
| false_positive | 0 |
| missed | 2 |

## LLM 风险判定

| 指标 | 值 |
|---|---:|
| risk 一致率 | 0.8571 |
| risk_level 一致率 | 0.8571 |
| 可对齐条款数 | 315 |

> fake-llm 模式下 LLM 始终返回 none，LLM 指标不代表真实模型质量。
