# experiment_kb/working/ 检索策略实验报告（Dense / BM25 / RRF）

> **阶段性结果声明**：标准答案尚未全部人工核验，以下指标不是最终真实 Recall。

运行时间（UTC）：2026-10-12T07:00:58.328491+00:00

知识库来源：experiment_kb/working/（不是生产 data/knowledge/），共 37 条 Evidence

candidate_k=20  final_top_k=[5, 10, 20]  rrf_k=60  tokenizer=char_bigram (forced via --tokenizer char_bigram)

样本/场景：188 条有效样本，47 个独立场景

Dense 通道：reused_this_round（知识库快照指纹和评估集指纹与本轮前一次运行逐一核对一致，场景集合/样本映射逐条相等，Dense 不受 BM25 分词器切换影响，复用真实结果，不重复调用 BGE-M3。）

## 质量指标（原始样本口径，188）

| 策略 | K | Recall | MRR | nDCG |
|---|---|---|---|---|
| dense | 5 | 0.7766 | 0.5771 | 0.6205 |
| dense | 10 | 0.9681 | 0.6037 | 0.6852 |
| dense | 20 | 0.9787 | 0.6047 | 0.6887 |
| bm25 | 5 | 0.9468 | 0.8644 | 0.8797 |
| bm25 | 10 | 0.9548 | 0.8644 | 0.8834 |
| bm25 | 20 | 0.992 | 0.8663 | 0.8929 |
| rrf | 5 | 0.9388 | 0.7314 | 0.7789 |
| rrf | 10 | 0.9707 | 0.736 | 0.79 |
| rrf | 20 | 0.992 | 0.737 | 0.7966 |

## 质量指标（独立场景口径，等权重）

| 策略 | K | Recall | MRR | nDCG |
|---|---|---|---|---|
| dense | 5 | 0.9238 | 0.7606 | 0.7892 |
| dense | 10 | 0.9557 | 0.7637 | 0.8015 |
| dense | 20 | 0.9716 | 0.7649 | 0.807 |
| bm25 | 5 | 0.9344 | 0.9007 | 0.902 |
| bm25 | 10 | 0.9468 | 0.9007 | 0.908 |
| bm25 | 20 | 0.9894 | 0.903 | 0.919 |
| rrf | 5 | 0.9238 | 0.7553 | 0.7887 |
| rrf | 10 | 0.961 | 0.7607 | 0.8024 |
| rrf | 20 | 0.9894 | 0.7621 | 0.8112 |

## Top-20 漏检（Dense 和 BM25 都没召回的相关法条）：1 个场景

- query: 工作地点
乙方工作地点为深圳市。甲方可以根据经营需要随时调整乙方工作地点，乙方应无条件服从。... 漏检: [('劳动合同法', '第二十六条')]

## 六项性能测量

```json
{
  "dense_query_embedding_and_retrieval": {
    "distinct_query_count": 47,
    "total_seconds": 5.609,
    "mean_seconds": 0.1193,
    "p50_seconds": 0.1079,
    "p95_seconds": 0.1778,
    "raw_seconds": [
      0.1141,
      0.10777,
      0.10694,
      0.10677,
      0.10401,
      0.10463,
      0.10726,
      0.10249,
      0.10977,
      0.10531,
      0.0979,
      0.09827,
      0.10129,
      0.12299,
      0.0958,
      0.13645,
      0.16563,
      0.12744,
      0.12778,
      0.12349,
      0.1694,
      0.10492,
      0.11735,
      0.11011,
      0.10744,
      0.10462,
      0.10793,
      0.09738,
      0.10203,
      0.09705,
      0.16647,
      0.16227,
      0.18558,
      0.10479,
      0.13039,
      0.13087,
      0.10513,
      0.10201,
      0.18309,
      0.11334,
      0.109,
      0.11352,
      0.12078,
      0.10653,
      0.16997,
      0.09895,
      0.1219
    ]
  },
  "bm25_tokenization_and_ranking": {
    "distinct_query_count": 47,
    "total_seconds": 0.005,
    "mean_seconds": 0.0001,
    "p50_seconds": 0.0001,
    "p95_seconds": 0.0002,
    "raw_seconds": [
      0.00012,
      7e-05,
      6e-05,
      6e-05,
      7e-05,
      6e-05,
      6e-05,
      7e-05,
      6e-05,
      6e-05,
      6e-05,
      6e-05,
      7e-05,
      8e-05,
      0.00103,
      0.0001,
      0.00012,
      0.0001,
      0.0001,
      9e-05,
      0.00012,
      7e-05,
      8e-05,
      0.00018,
      8e-05,
      7e-05,
      7e-05,
      7e-05,
      9e-05,
      6e-05,
      0.00014,
      0.00013,
      0.00014,
      7e-05,
      9e-05,
      0.00011,
      7e-05,
      8e-05,
      0.00012,
      8e-05,
      7e-05,
      9e-05,
      0.00011,
      8e-05,
      0.00014,
      0.00019,
      0.00011
    ]
  },
  "rrf_fusion_overhead": {
    "total_seconds_for_all_scenarios": 0.002,
    "distinct_scenario_count": 47,
    "mean_seconds_per_scenario": 4.3e-05
  },
  "hybrid_end_to_end": {
    "serial_total_seconds": 5.616,
    "parallel_note": "本脚本的 Dense/BM25 候选是分两个独立循环产生的（不是真正逐 query 用线程池并发跑两个通道），所以这里不伪造一个'并行耗时'数字——如果需要真实的 query 级并行耗时，需要在本机真实运行时改成 concurrent.futures.ThreadPoolExecutor 同时发起 Dense 检索和 BM25 检索，这里先如实标注未测量，不用 serial_total_seconds 近似代替。",
    "parallel_total_seconds": null
  },
  "index_build_update_delete": {
    "dense": {
      "initial_build_seconds": 14.013,
      "initial_doc_count": 37,
      "update_one_evidence_seconds": 0.262,
      "doc_count_after_update": 37,
      "delete_test_error": "删除测试失败，如实记录，不影响检索指标本身: AttributeError(\"'ChromaKnowledgeBase' object has no attribute 'collection'\")"
    },
    "bm25": {
      "initial_build_seconds": 0.001,
      "initial_doc_count": 37,
      "update_one_document_seconds": 0.001,
      "doc_count_after_update": 38,
      "delete_one_document_seconds": 0.001,
      "doc_count_after_delete": 36
    },
    "skipped": false
  },
  "cold_start_and_model_init": {
    "embedder_load_seconds": 12.977
  }
}
```

## 限制声明

- 标准答案（relevant 标签）尚未全部人工核验，本结果中的 Recall/MRR/nDCG 是基于当前（尚待完善人工核验的）标准答案标签算出的阶段性指标，不是最终真实 Recall。
- 《劳动法》第三十六—四十五条来源版本仍标注为'尚待进一步核实'，《劳动合同法》第五十条确定性文本比对（difflib）仍未完成——这两点不阻塞本次工程实验，但本结果不能作为这两条法律文本本身已核验正确的证据。
- 仲裁法第十—十六条全程未参与本次检索实验（未被本脚本读取，见启动断言），不在 Dense/BM25/RRF 任何候选列表中。
- 本脚本尚未在真实环境中实际运行过——本次只完成静态代码检查和逻辑复核，任何数字性结果只有在你本机运行后才算'已实际验证'。
