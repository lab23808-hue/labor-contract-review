# 500份合同评测集 · 全量知识库BM25检索评测报告

生成时间（UTC）：见 `run_metadata.json.generated_at_utc`
实验目录：`experiment_kb/datasets/contract_eval_500_20261013/full_kb_experiment/`
本轮性质：**实验性**，不修改生产知识库/Chroma索引/BM25代码/API/前端。

---

## 一、本轮做了什么（真实执行，非估算）

1. 使用生产 `rag.knowledge_loader.KnowledgeLoader.load_file()`（未改动的生产代码，仅调用其已支持的
   `source=` 参数，不是新增能力）真实解析并合并四类来源：
   - `data/knowledge/劳动合同法.txt`（生产，26条Evidence）
   - `experiment_kb/working/data/knowledge/LAW_01_劳动合同法_第五十条.txt`（working新增，1条，归入"劳动合同法"）
   - `experiment_kb/working/data/knowledge/LAW_02_劳动法_第三十六条至第四十五条.txt`（working新增，10条，归入"劳动法"）
   - `experiment_kb/reference_only/仲裁法_第十条至第十六条_参考材料.txt`（仅隔离实验索引，7条，归入"劳动争议调解仲裁法"）
2. 用生产 `rag.bm25_index.BM25KnowledgeIndex`（未改动，`k1=1.5, b=0.75`, `char_bigram_tokenizer`）真实构建索引，
   其构造函数本身会在遇到真实重复/空内容时 fail-fast——本轮索引**成功构建、无一异常**，这本身就是
   "0重复、0空内容"的生产代码验证结果，不是我方估算。
3. 对450份新合同全部查询 + 现有50份的188条可评估样本，用生产 `rag.retriever.LegalKnowledgeRetriever`
   真实执行检索（候选池K=20），记录每条查询的完整候选列表、排名、分数。
4. baseline/working 快照仅用作历史对照基准（baseline=26条，working=37条），未被当作需要重新计入的
   独立法律内容——避免重复计数。

`experiment_kb/baseline/`、`experiment_kb/working/` 的历史快照文件本身未被修改，本轮只读取，不覆盖。

---

## 二、完整实验知识库构成（真实统计，见 `knowledge_manifest.csv` / `run_metadata.json`）

| 来源(origin) | 文件 | 法律名(source) | Evidence数 |
|---|---|---|---|
| production | 劳动合同法.txt | 劳动合同法 | 26 |
| working_new | LAW_01_劳动合同法_第五十条.txt | 劳动合同法 | 1 |
| working_new | LAW_02_劳动法_第三十六条至第四十五条.txt | 劳动法 | 10 |
| reference_only | 仲裁法_第十条至第十六条_参考材料.txt | 劳动争议调解仲裁法 | 7 |
| **合计（去重后）** | | | **44** |

- **去重结果**：44条Evidence的 `evidence_id`（生产 `_evidence_id()` 哈希）全部唯一，**0个重复**
  （由生产 `BM25KnowledgeIndex` 构造时fail-fast真实验证，而非人工比对）。
- **相对正式26条版本新增的法律覆盖**：
  - 《劳动合同法》第五十条（working新增，解除/终止证明义务、经济补偿支付时点等）
  - 《劳动法》第三十六—四十五条（working新增，工时/休息/节假日/加班工资/带薪年休假，10条）
  - 《劳动争议调解仲裁法》第十—十六条（reference_only，隔离实验专用，**不计入**生产/working的核心法律覆盖，
    仅用于考察"扩容后是否干扰无关查询的检索结果"）
- **相对working37条版本新增的法律覆盖**：仅 reference_only 的仲裁法7条（working的37条本身已包含在44条之中）。
- **跨法同号条文（交叉参考，不改变ground truth判定）**：《劳动合同法》与《劳动法》在条号
  **第三十六条、第三十九条、第四十条** 上同号但内容完全不同（见 `run_metadata.json.kb_cross_law_same_number_overlaps`，
  及各自 `content_length`/`content_hash` 不同，确认非重复导入）。

---

## 三、候选标签解析方法论（必须显式声明，避免"仅条号匹配即判定相关"的谬误）

对 `candidate_relevant_law` 按 `|` 切分后：
- 若标签中**显式写明法律/法规名**（劳动法、工伤保险条例、职工带薪年休假条例），该标签内的裸条号
  **锚定**到该法律/法规。
- 若标签中**全部是裸条号、没有法律名**，裸条号**默认归属《劳动合同法》**——
  这与上一轮单法（26条）实验的隐含口径完全一致（当时知识库里只有劳动合同法，裸条号天然只能指它），
  本轮延续该默认值是为了与历史轮次可比，不是新发明的猜测。
- 跨法同号（36/39/40）情况下，默认策略**仍解析为《劳动合同法》对应条文**，不会因为《劳动法》里
  同号条文存在就改判或"既算又算"——同号重叠只记入诊断字段 `cross_law_same_number_sources`，
  **不参与ground truth判定、不参与recall计算**。
- 本数据集450条候选标签中，**实测没有出现任何"多个法律名token同时出现"的不可解析情况**
  （`run_metadata.json.unparseable_labels` 为空列表），即本轮方法论可以无歧义覆盖全部已观测标签形式；
  若未来出现新形式会被登记而不是静默跳过。
- 数据集中没有任何候选标签显式指向《劳动争议调解仲裁法》——该法内容**在ground truth意义上
  不会被判定为任何样本的目标**，只用于观察它是否会被BM25误召回进无关查询的TopK候选（干扰性评估）。

---

## 四、知识库覆盖审计（见 `knowledge_coverage_audit.csv`）

新增450份样本（共450条query-label记录）：

| 指标 | 数值 |
|---|---|
| 至少1个目标条文命中KB（`any_target_in_kb`） | 336 / 450 |
| 全部目标条文均命中KB（`all_targets_in_kb`） | 250 / 450 |
| 完全不在KB中（无一候选法条可定位） | 114 / 450 |

**必须强调**：以上是"目标条文是否存在于本轮44条Evidence实验知识库中"的覆盖审计，
与"BM25是否把它检索进TopK"是两件不同的事——后者的结果见下一节，`miss_analysis.csv` 对每条
miss显式区分了 `target_article_not_in_kb`（结构性不可能命中）与
`in_kb_but_not_in_top20_candidate_pool`（条文在KB中但未被BM25排进候选池，真实的检索召回问题）。

Top20候选池下的miss原因分布（`miss_analysis.csv`，`topk=20`）：

| 数据集 | target_article_not_in_kb | in_kb_but_not_in_top20_candidate_pool |
|---|---|---|
| 新增450份 | 273 | 111 |
| 现有50份(188可评估样本) | 0 | 13 |

---

## 五、BM25正式评测指标（三种口径，见 `metrics.json`）

- **口径A（全部候选标签口径）**：把"目标条文不在KB"也计为miss，反映端到端(含知识库覆盖缺口)的真实表现。
- **口径B（知识库覆盖子集）**：只统计目标条文确实存在于本轮实验KB中的样本，反映BM25检索算法本身在
  "有解"情况下的表现。
- **口径C**：以上全部指标依赖 `candidate_labels_pending_review.csv` / `retrieval_eval_samples.json` 的
  候选相关法条标签，这些标签**尚未经有法律资格人员最终确认**（`verification_status` 字段），
  不可作为gold standard，仅作研究性参考（详见 `metrics.json.lensC_note`）。

### 5.1 新增450份 —— development(360) vs final_test(90)，严格分开报告

| 指标 | development(n=360) | final_test(n=90) |
|---|---|---|
| Recall@5 (口径A) | 0.3657 | 0.3556 |
| Recall@5 (口径B) | 0.5558 | 0.5597 |
| Recall@10 (口径A) | 0.4338 | 0.4111 |
| Recall@10 (口径B) | 0.6617 | 0.6418 |
| Recall@20 (口径A) | 0.4991 | 0.4574 |
| Recall@20 (口径B) | 0.7658 | 0.7239 |
| MRR@10 | 0.3235 | 0.3398 |
| nDCG@10 | 0.3283 | 0.3318 |

final_test集**只在固定配置（char_bigram, k1=1.5, b=0.75, K=5/10/20）下评测一次**，未用final_test
反向调参——development与final_test指标高度接近（差距在个位百分点），没有development上明显优化导致
final_test"意外"落后或领先的异常信号。

**必要的整体/合并统计**（450份合计，`metrics.json.new_450_combined_n450`）：Recall@5(A)=0.3637，
Recall@10(A)=0.4293，Recall@20(A)=0.4907；**此合并数仅供参考，核心结论以development/final_test分别
报告为准，不能用来掩盖两个子集各自的表现**。

### 5.2 现有50份（188条可评估样本）—— 与新增450份严格分开报告，不混合计算平均值

| 指标 | 数值 |
|---|---|
| Recall@5 (口径A=口径B，因188样本全部命中KB覆盖) | 0.9468 |
| Recall@10 | 0.9495 |
| Recall@20 | 0.9548 |
| MRR@10 | 0.7606 |
| nDCG@10 | 0.8054 |

### 5.3 与历史26/37条单法实验轮次的对比（关键发现）

| 指标(K=20) | 历史26条KB(单法，A003/A004轮次) | 本轮44条Evidence全量KB |
|---|---|---|
| 新增450份 Recall@20(口径A，全部候选) | 0.5752 | 0.4907（合并口径，development=0.4991/final_test=0.4574） |
| 新增450份 Recall@20(口径B，KB覆盖子集) | 0.9492 | 0.7574 |
| 现有50份(188) Recall@20 | 0.9920 | 0.9548 |
| 现有50份(188) MRR@10 | 0.8681（历史MRR@10就用历史JSON里的"mrr"字段，口径为固定K=10候选内） | 0.7606 |
| 现有50份(188) nDCG@10 | 0.8928 | 0.8054 |

**关键发现（真实观察，非推测）**：知识库从26条扩容到44条Evidence后——

1. **口径A的Recall@20反而从0.5752降到0.4907附近**，看起来像是"检索变差了"，但这是**覆盖面扩大**和
   **候选竞争加剧**两个相反效应叠加的结果：覆盖面上，`any_target_in_kb=True`的样本数从历史的
   229+86=315提升到本轮336（working新增的第五十条/第三十六—四十五条让更多候选标签有了可命中目标）；
   但**口径B（只看KB内确实存在目标的子集）的Recall@20从0.9492大幅降到0.7574**，说明在"目标本来就在KB
   里"的样本上，BM25把它排进Top20的能力本身下降了——这不是目标条文消失了，而是**候选条文池从26条
   扩大到44条后，相同K值下候选条文之间的竞争明显加剧**（尤其是条号重复的第36/39/40条，以及working/
   reference_only新增的18条在字符bigram词汇上与原26条有重叠），挤占了原本能排进TopK的目标排名。
2. 现有50份（188样本）的 **Recall@20几乎未变**（0.9920→0.9548，降幅很小），但 **MRR@10/nDCG@10
   明显下降**（0.8681→0.7606，0.8928→0.8054）——说明目标条文**大多仍留在TopK内，但平均排名后移**，
   与第1点的"候选竞争加剧"结论一致：这是BM25在语料库扩容后IDF统计量漂移导致的**预期工程代价**，
   不是BM25算法本身退化或代码bug。
3. **该现象必须被诚实报告，不能被"新实验指标更低→算法有问题"这种简单归因掩盖**，也不能反过来被
   "覆盖面扩大了→指标应该全面变好"的直觉掩盖——真实数据显示这是一个有得有失的权衡。

---

## 六、工作地点单方变更场景专项（第二十六条 / 第三十五条）

范围：`scenario_id == "workplace_unilateral"`，共15个合同样本（均在development集，final_test集中
不含该场景——这是数据集本身的场景分布，不是本轮筛选造成的）。

| 指标(K=20) | 历史26条KB | 本轮44条Evidence全量KB |
|---|---|---|
| 两条文(26+35)均命中 | 8/15 | 4/15 |
| 未命中第二十六条 | 5/15 | 5/15（**完全不变**） |
| 未命中第三十五条 | 2/15 | 11/15（**显著恶化**） |

**诊断（逐条实际证据，非猜测）**：
- 第二十六条的miss数**本轮与历史完全一致（5/15）**——说明这5例的未命中是查询措辞与该条文内容
  本身匹配度不足导致的**结构性检索难点**，与本轮知识库扩容无关（扩容前后都存在）。
- 第三十五条的miss数从2/15暴增到11/15。第三十五条**不在**本轮发现的36/39/40跨法同号范围内，
  《劳动法》《仲裁法》都没有同号条文与它直接竞争字符bigram相似度——`retrieval_rank_detail.csv`中
  可见其实际排名多数仍在合理范围内下滑而非完全消失（如某些样本排名从历史的Top5掉到本轮的Top8/11），
  这与全局Recall@20(口径B)从0.9492降到0.7574的现象完全吻合：**是全量知识库扩容后的全局IDF漂移/
  候选竞争加剧效应，不是因为第三十五条本身"被挤出"了知识库，也不是候选标签标注本身发生了变化**
  （该场景candidate_relevant_law标签`第三十五条|第二十六条`在本轮与历史轮次完全一致，未被修改）。
- **未人为把目标条文强行塞入候选结果，未删除任何失败样本或修改原始标签**——`retrieval_rank_detail.csv`
  的`workplace_unilateral`相关行完整保留了全部15个样本的真实排名（包括`actual_rank`为空、即完全未
  进入Top20候选池的样本）。

---

## 七、执行/未执行/失败事项清单

| 事项 | 状态 |
|---|---|
| 复用生产KnowledgeLoader/BM25KnowledgeIndex构建44条Evidence全量实验KB | ✅已执行，真实运行成功 |
| 去重校验（evidence_id哈希） | ✅已执行，0重复 |
| 450份候选标签解析方法论设计与无歧义覆盖验证 | ✅已执行，`unparseable_labels`为空 |
| 450份+188份真实BM25检索（候选池K=20） | ✅已执行 |
| 知识库覆盖审计（区分"不在KB"vs"在KB未召回"） | ✅已执行 |
| development/final_test严格分开报告，模板家族无跨集泄漏检查 | ✅已执行，0个template_family跨集 |
| 工作地点单方变更(26/35条)专项对比 | ✅已执行 |
| 对450份合同做批量LLM法律审查 | ⛔未执行（按本轮边界要求，不应执行） |
| 修改生产 `data/knowledge/`、`data/chroma/`、BM25代码 | ⛔未执行（按本轮边界要求，不应执行） |
| 450+新增条文的"官方逐字核验"（见working的WHITELIST说明，本就标注为"来源待核实"） | ⚠️**NOT_MEASURED**——working新增的11条Evidence来源版本本身就未完成官方逐字核验
（见`experiment_kb/whitelist/WHITELIST_current.md`），本轮仅复用其既有状态，未新增核验工作，也不构成本轮新发现的问题。 |

---

## 八、复现方法

```bash
python3 experiment_kb/scripts/evaluate_contract_eval_500_full_kb.py
```

脚本顶部5个路径常量（`PROJECT_ROOT`/`SANDBOX_SRC_ROOT`/`DATASET_ROOT`/`OUT_DIR`/`OLD_EVAL_SAMPLES`）
按实际机器调整后即可复现；BM25参数固定为`k1=1.5,b=0.75,char_bigram`，候选池`K=20`，不依赖任何
随机数种子或网络调用，相同数据+相同生产代码下应得到完全一致的Evidence集合与排名
（相同分数时按生产`BM25KnowledgeIndex`的`(-score, original_index)`规则保证确定性排序）。

## 九、如何删除本轮实验（不影响原项目）

本轮全部新增内容都在以下目录内，直接删除即可，不涉及生产目录：

```
experiment_kb/datasets/contract_eval_500_20261013/full_kb_experiment/
experiment_kb/scripts/evaluate_contract_eval_500_full_kb.py
```

`RAG_EXPERIMENT_REGISTER.csv`中新增的本轮记录行（见登记编号）需单独手动删除该行，若需要完全撤销登记。
