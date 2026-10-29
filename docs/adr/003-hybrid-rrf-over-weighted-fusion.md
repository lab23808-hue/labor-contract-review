# ADR 003：Hybrid 采用 RRF，而不是加权分数融合

## 背景

BM25 分数越大越好，Chroma 返回的是距离（越小越好），两者量级和方向不同，直接加权需要额外归一化，且对语料敏感。

## 决策

`HybridBackend` 分别取 dense/BM25 的候选，按文档内容与 source/article/part 生成稳定 key，使用 RRF（k=60）融合排名，再返回 top-k。

## 评估结果（10 份合同，fake LLM）

| 策略 | Recall@5 | MRR@5 |
|---|---:|---:|
| BM25 | 0.8667 | 0.6650 |
| Dense | 1.0000 | 0.6343 |
| Hybrid + RRF | 1.0000 | 0.6994 |

## 结果

Hybrid 在该子集上 MRR 高于单路；样本较小，结论仅作为当前实现记录。
