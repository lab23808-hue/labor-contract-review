# 历史指标可比性核验（26/37/44条知识库）

## 1. 结论先行

**历史已发布的26条KB指标与44条KB(`full_kb_experiment`轮)指标，以及本轮重新生成的26条KB指标，三者口径并不完全一致，不能逐位直接相减得出"扩容导致下降X个百分点"的结论。** 但经本轮逐项核查，三者在**方向上高度一致**（recall随KB扩容单调下降），本轮已在相同口径下重新生成了可直接比较的数字（见`rank_change_detail.csv`/`BM25_KB_GROWTH_DIAGNOSIS_20261013.json`），下方逐条说明差异来源。

## 2. 逐项核查

### 2.1 是否使用同一批query、同一组标签、同一分母

| 轮次 | query来源 | 样本数(分母) | dev/test是否分离 |
|---|---|---|---|
| A001/A002(历史26条KB) | 老50份合同的188可评估样本 | 188(样本级)/47(场景级) | 该数据集本身无dev/test划分概念 |
| 历史"26条KB+450份"轮(私有`bm25_run_result.json`，未在本轮register中登记为独立行) | 450份新合同全部候选标签 | 450(未分dev/test，混合) | **未分离**——development与final_test混在一起计算 |
| 本轮full_kb_experiment(44条KB) | 450份新合同全部候选标签 | development 360 / final_test 90 分别报告 | **已分离** |
| 本轮kb_growth_diagnosis(26/37/44条KB) | 450份中development子集 | 360（三版本完全相同的360条query） | 只用development，final_test全程未参与 |

**结论**：历史"26条KB+450份"轮与本轮diagnosis轮的**样本范围不同**（450混合 vs 360纯development），
因此两者的汇总Recall数字**不可逐位相减**。本轮已用完全相同的360条development query对26/37/44三版本
重新测了一遍，这才是真正可比的数字（见下表）。

### 2.2 是否混用样本级/场景级/宏平均/微平均

A001/A002已确认存在宏平均(场景级,47)与微平均(样本级,188/215)两套数字，相差可达3个百分点
（见`RAG_METRIC_AUDIT_20261013.json`，本轮未重新核查，沿用已发布结论）。

本轮diagnosis轮与此前full_kb_experiment轮**统一使用"样本级"(每条query各自计算recall再求平均)**，
未引入场景级宏平均，内部口径一致。但与A001/A002的历史老50份数字对比时，**老50份自己历史上同时报告过
场景级和样本级两套数字**——本报告仅引用其样本级(188)数字做对照，不与其场景级(47)数字混用。

### 2.3 26/37/44版本中，相关目标法条是否都存在于各自索引

本轮用**与`full_kb_experiment`轮完全相同**的候选标签解析方法论（法规名显式锚定/无法规名默认归属
《劳动合同法》）重新对360条development query做了覆盖判定，并validate了**26⊆37⊆44的真实嵌套关系**
（`evidence_id`集合包含关系，程序assert通过，非口头声明）——kb26=26条，kb37=37条，kb44=44条，
`kb_version_manifest.csv`给出三版本完整清单。

### 2.4 原报告中"知识库外目标"与"知识库内未召回"是否被正确区分

`full_kb_experiment`轮的`miss_analysis.csv`已经做了这个区分(`target_article_not_in_kb` vs
`in_kb_but_not_in_top20_candidate_pool`)，本轮diagnosis延续同一区分标准，用`kb{26,37,44}_in_kb`
三个独立字段记录每个版本各自的覆盖状态(见`rank_change_detail.csv`)——**这一点历史记录与本轮口径一致，
没有发现需要修正的问题**。

### 2.5 第26/35条漏检统计是否使用了相同的15个工作地点场景和同一组标签

核查`manifest_450.csv`中`scenario_id=="workplace_unilateral"`的记录：**恒定为15条，且15条全部落在
development集**（无一条在final_test），这15条样本及其`candidate_relevant_law`标签原文
(`第三十五条|第二十六条`)在本轮diagnosis与此前full_kb_experiment轮之间**未被修改、未被删除、未被新增**，
已逐条比对contract_id集合完全一致。因此26条→44条前后的第26/35条对比，样本集合层面是公平的；
两轮之间数字差异的来源是KB版本范围不同(26 vs 44)，而不是样本集合被悄悄换了。

## 3. 本轮重新生成的、可直接比较的development-only数字

| 版本 | n(development) | Recall@20(口径A) | Recall@20(口径B，各版本自己的KB覆盖子集) | MRR@10 | nDCG@10 |
|---|---|---|---|---|---|
| kb26 | 360 | 0.5755 | 0.9502 | 0.3392 | 0.3354 |
| kb37 | 360 | 0.5296 | 0.8197 | 0.3321 | 0.3378 |
| kb44 | 360 | 0.4991 | 0.7658 | 0.3235 | 0.3283 |

以上三行**query集合完全相同(360条development)**、**label解析方法论完全相同**、**BM25参数/实现完全相同**，
是本轮真正意义上"苹果对苹果"的对照，取代了历史轮次之间不能直接相减的汇总数字。

**三版本共同覆盖子集**（317个query-target对，目标在kb26中即存在——因26⊆37⊆44，这是对覆盖范围最严格的
子集）上的指标见`BM25_KB_GROWTH_DIAGNOSIS_20261013.json`的`common_covered_subset`字段，用于剥离"覆盖面
变化"这个变量，单纯比较排序质量变化。

## 4. 未能完全确认的事项

- 历史"26条KB+450份"轮(`bm25_run_result.json`)当时记录的是否也是K=20候选池、是否逐条记录了`actual_rank`
  字段的完整细节——本轮确认该JSON文件本身保留了完整的`candidates_top20`字段(未丢失数据)，但该轮次
  **没有在`RAG_EXPERIMENT_REGISTER.csv`中登记为独立的experiment_id**，只是A004行描述中的一部分，
  因此严格意义上它不是一条"已登记可追溯"的历史记录，本报告只把它当作背景参考，不作为对照基准。
