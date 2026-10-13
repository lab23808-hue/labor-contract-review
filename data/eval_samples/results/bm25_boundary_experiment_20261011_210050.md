# BM25 字符二元分词跨空白边界处理对照实验：char_bigram_baseline vs char_bigram_boundary_aware

运行时间（UTC）：2026-10-11T13:00:50.740736+00:00

BM25 参数：k1=1.5, b=0.75；candidate_k=20；final_top_k=[5, 10, 20]；样本数=188；独立场景数=47

知识库一致性核验：`{'checked': False, 'reason': '无法只读连接官方 Chroma collection 做核验: ModuleNotFoundError("No module named \'chromadb\'")', 'content_match_exactly': None, 'ids_match_exactly': None, 'problems': []}`

## 指标对照

| 版本 | 口径 | K | Recall | MRR | nDCG |
|---|---|---|---|---|---|
| char_bigram_baseline | 原始样本(188) | 5 | 0.9468 | 0.8644 | 0.8797 |
| char_bigram_baseline | 原始样本(188) | 10 | 0.984 | 0.8681 | 0.8928 |
| char_bigram_baseline | 原始样本(188) | 20 | 0.992 | 0.8681 | 0.8952 |
| char_bigram_baseline | 独立场景(47) | 5 | 0.9344 | 0.9007 | 0.902 |
| char_bigram_baseline | 独立场景(47) | 10 | 0.9787 | 0.905 | 0.9184 |
| char_bigram_baseline | 独立场景(47) | 20 | 0.9894 | 0.905 | 0.9217 |
| char_bigram_boundary_aware | 原始样本(188) | 5 | 0.9468 | 0.8644 | 0.8797 |
| char_bigram_boundary_aware | 原始样本(188) | 10 | 0.984 | 0.8681 | 0.8928 |
| char_bigram_boundary_aware | 原始样本(188) | 20 | 0.992 | 0.8681 | 0.8952 |
| char_bigram_boundary_aware | 独立场景(47) | 5 | 0.9344 | 0.9007 | 0.902 |
| char_bigram_boundary_aware | 独立场景(47) | 10 | 0.9787 | 0.905 | 0.9184 |
| char_bigram_boundary_aware | 独立场景(47) | 20 | 0.9894 | 0.905 | 0.9217 |

## 重点场景排名

- 社保补偿条款：`{'char_bigram_baseline': {'劳动合同法第十七条': 1, '劳动合同法第二十六条': 15}, 'char_bigram_boundary_aware': {'劳动合同法第十七条': 1, '劳动合同法第二十六条': 15}}`
- 工作地点条款：`{'char_bigram_baseline': {'劳动合同法第三十五条': 10}, 'char_bigram_boundary_aware': {'劳动合同法第三十五条': 10}}`
- 延迟支付(劳动报酬)条款：`{'char_bigram_baseline': {'劳动合同法第三十条': 1, '劳动合同法第八十五条': 2, '劳动合同法第二十六条': 6}, 'char_bigram_boundary_aware': {'劳动合同法第三十条': 1, '劳动合同法第八十五条': 2, '劳动合同法第二十六条': 6}}`

## baseline vs boundary_aware 差异

- baseline 找到但 boundary_aware 没找到：[]
- boundary_aware 找到但 baseline 没找到：[]
- 两者都没找到：[{'query': '工作地点\n乙方工作地点为深圳市。甲方可以根据经营需要随时调整', 'article': ['劳动合同法', '第二十六条']}]
- 两者都找到但排名变化：[]

## 结论与限制

详见对话中的文字分析（是否消除了跨边界 token、指标是否改善、是否建议采用、限制）。本报告只保留可复现的真实数字。
