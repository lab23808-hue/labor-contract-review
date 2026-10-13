# experiment_kb/working/ 检索策略实验报告（Dense / BM25 / RRF）

> **阶段性结果声明**：标准答案尚未全部人工核验，以下指标不是最终真实 Recall。

运行时间（UTC）：2026-10-12T07:17:10.302076+00:00

知识库来源：experiment_kb/baseline/（不是生产 data/knowledge/），共 26 条 Evidence

candidate_k=20  final_top_k=[5, 10, 20]  rrf_k=60  tokenizer=char_bigram (forced via --tokenizer char_bigram)

样本/场景：188 条有效样本，47 个独立场景

Dense 通道：rerun_forced（本轮规则：不允许把旧版 26 条 Evidence 上的 Dense 历史结果当作本轮基线，experiment_kb/working/ 的知识库内容与历史结果不同，强制真实重跑。）

## 质量指标（原始样本口径，188）

| 策略 | K | Recall | MRR | nDCG |
|---|---|---|---|---|
| dense | 5 | 0.9628 | 0.629 | 0.7055 |
| dense | 10 | 0.9707 | 0.629 | 0.7095 |
| dense | 20 | 0.984 | 0.6301 | 0.7137 |
| bm25 | 5 | 0.9468 | 0.8644 | 0.8797 |
| bm25 | 10 | 0.984 | 0.8681 | 0.8928 |
| bm25 | 20 | 0.992 | 0.8681 | 0.8953 |
| rrf | 5 | 0.9707 | 0.7394 | 0.7944 |
| rrf | 10 | 0.9761 | 0.7394 | 0.7966 |
| rrf | 20 | 0.992 | 0.7404 | 0.8013 |

## 质量指标（独立场景口径，等权重）

| 策略 | K | Recall | MRR | nDCG |
|---|---|---|---|---|
| dense | 5 | 0.945 | 0.7713 | 0.8033 |
| dense | 10 | 0.961 | 0.7713 | 0.8113 |
| dense | 20 | 0.9787 | 0.7728 | 0.8169 |
| bm25 | 5 | 0.9344 | 0.9007 | 0.902 |
| bm25 | 10 | 0.9787 | 0.905 | 0.9184 |
| bm25 | 20 | 0.9894 | 0.905 | 0.9218 |
| rrf | 5 | 0.961 | 0.7677 | 0.8097 |
| rrf | 10 | 0.9681 | 0.7677 | 0.8126 |
| rrf | 20 | 0.9894 | 0.7691 | 0.8189 |

## Top-20 漏检（Dense 和 BM25 都没召回的相关法条）：1 个场景

- query: 工作地点
乙方工作地点为深圳市。甲方可以根据经营需要随时调整乙方工作地点，乙方应无条件服从。... 漏检: [('劳动合同法', '第二十六条')]

## 六项性能测量

```json
{
  "dense_query_embedding_and_retrieval": {
    "distinct_query_count": 47,
    "total_seconds": 6.851,
    "mean_seconds": 0.1458,
    "p50_seconds": 0.1316,
    "p95_seconds": 0.2266,
    "raw_seconds": [
      0.14592,
      0.16719,
      0.12507,
      0.13426,
      0.13063,
      0.12094,
      0.12184,
      0.11599,
      0.12209,
      0.12868,
      0.10561,
      0.11452,
      0.12096,
      0.1415,
      0.1213,
      0.16065,
      0.21197,
      0.15412,
      0.13757,
      0.13159,
      0.18283,
      0.10735,
      0.12713,
      0.12286,
      0.11098,
      0.13408,
      0.1314,
      0.12316,
      0.12353,
      0.10683,
      0.23637,
      0.1871,
      0.35908,
      0.14138,
      0.15697,
      0.13833,
      0.11652,
      0.11381,
      0.21085,
      0.12763,
      0.13352,
      0.17208,
      0.17227,
      0.15659,
      0.20736,
      0.1071,
      0.13182
    ]
  },
  "bm25_tokenization_and_ranking": {
    "distinct_query_count": 47,
    "total_seconds": 0.005,
    "mean_seconds": 0.0001,
    "p50_seconds": 0.0001,
    "p95_seconds": 0.0003,
    "raw_seconds": [
      6e-05,
      6e-05,
      5e-05,
      5e-05,
      5e-05,
      5e-05,
      4e-05,
      6e-05,
      5e-05,
      4e-05,
      5e-05,
      5e-05,
      6e-05,
      6e-05,
      4e-05,
      6e-05,
      9e-05,
      0.0008,
      0.0001,
      7e-05,
      9e-05,
      6e-05,
      6e-05,
      6e-05,
      5e-05,
      5e-05,
      4e-05,
      5e-05,
      6e-05,
      4e-05,
      0.0001,
      0.00026,
      0.00011,
      0.00012,
      0.00016,
      0.00033,
      0.00011,
      7e-05,
      0.00012,
      7e-05,
      7e-05,
      8e-05,
      8e-05,
      6e-05,
      0.00011,
      6e-05,
      0.00028
    ]
  },
  "rrf_fusion_overhead": {
    "total_seconds_for_all_scenarios": 0.002,
    "distinct_scenario_count": 47,
    "mean_seconds_per_scenario": 4.3e-05
  },
  "hybrid_end_to_end": {
    "serial_total_seconds": 6.858,
    "parallel_note": "本脚本的 Dense/BM25 候选是分两个独立循环产生的（不是真正逐 query 用线程池并发跑两个通道），所以这里不伪造一个'并行耗时'数字——如果需要真实的 query 级并行耗时，需要在本机真实运行时改成 concurrent.futures.ThreadPoolExecutor 同时发起 Dense 检索和 BM25 检索，这里先如实标注未测量，不用 serial_total_seconds 近似代替。",
    "parallel_total_seconds": null
  },
  "index_build_update_delete": {
    "dense": {
      "initial_build_seconds": 10.863,
      "initial_doc_count": 26,
      "update_one_evidence_seconds": 0.247,
      "doc_count_after_update": 26,
      "delete_one_evidence_seconds": 0.018,
      "doc_count_after_delete": 25
    },
    "bm25": {
      "initial_build_seconds": 0.002,
      "initial_doc_count": 26,
      "update_one_document_seconds": 0.001,
      "doc_count_after_update": 27,
      "delete_one_document_seconds": 0.001,
      "doc_count_after_delete": 25
    },
    "skipped": false
  },
  "cold_start_and_model_init": {
    "embedder_load_seconds": 11.728
  }
}
```

## 限制声明

- 标准答案（relevant 标签）尚未全部人工核验，本结果中的 Recall/MRR/nDCG 是基于当前（尚待完善人工核验的）标准答案标签算出的阶段性指标，不是最终真实 Recall。
- 《劳动法》第三十六—四十五条来源版本仍标注为'尚待进一步核实'，《劳动合同法》第五十条确定性文本比对（difflib）仍未完成——这两点不阻塞本次工程实验，但本结果不能作为这两条法律文本本身已核验正确的证据。
- 仲裁法第十—十六条全程未参与本次检索实验（未被本脚本读取，见启动断言），不在 Dense/BM25/RRF 任何候选列表中。
- 本脚本尚未在真实环境中实际运行过——本次只完成静态代码检查和逻辑复核，任何数字性结果只有在你本机运行后才算'已实际验证'。
