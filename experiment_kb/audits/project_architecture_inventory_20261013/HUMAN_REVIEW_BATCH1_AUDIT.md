# RAG_HUMAN_REVIEW_BATCH1.xlsx 核实报告（补查轮，2026-10-14）

标签说明同前几轮：CONFIRMED=本轮用 `openpyxl` 真实打开文件逐单元格读取确认；REPORTED=来自表内"说明"工作表的自述文字；INFERRED=基于以上证据推理；UNKNOWN=证据不足。

隐私声明：以下仅给出字段名、数量统计、状态分布与必要的脱敏示例片段（条款文字为合成测试合同文本，不含真实姓名/身份证号/电话号码），不输出任何完整合同正文或个人信息。

## 1. 文件能否正常打开 / 工作表结构（CONFIRMED）

文件可正常打开，共 **2 个工作表**：

| 工作表名 | 维度 | 数据行数（不含表头） | 列数 |
|---|---|---|---|
| `首批人工核验` | A1:Q12 | 11 | 17 |
| `说明` | A1:B5 | 4 | 2 |

`首批人工核验` 的 17 个列名（字段类型均为文本/字符串，Excel 层面无强类型约束）：

```
sample_id, contract_id, clause_id, query, original_text, candidate_law_name,
candidate_article, candidate_legal_text, official_source_url,
source_effective_status, candidate_evidence_id, ai_confidence,
uncertainty_reason, other_possible_articles, human_review_status,
human_confirmed_evidence_ids, review_notes
```

## 2. 实际记录数 / 空值 / 重复（CONFIRMED）

- 实际数据行数：**11 行**（与"说明"工作表里声明的"共11行"完全一致）。
- 无重复 `sample_id`（11个值互不相同）。
- 逐行空值计数：11行中每行有 1-3 个空单元格（主要集中在 `human_confirmed_evidence_ids` 列——**全部11行此列均为空**——以及部分行的 `candidate_article`/`other_possible_articles`），无"整行全空"的异常空行。
- 11行中有 **6 行**的 `sample_id`/`contract_id` 不是真实ID，而是描述性占位文字（例如"（社保放弃场景，具体sample_id见retrieval_eval_samples.json）"），这6行是"说明"工作表提到的"5个历史已知检索失败案例"+部分场景代表，**本轮未逐一交叉查找它们在 `retrieval_eval_samples.json` 里对应的真实 sample_id**（UNKNOWN，见第6节）。

## 3. 字段覆盖情况（CONFIRMED，按实际内容判断，不假定存在）

| 要核实的字段 | 是否存在 | 说明 |
|---|---|---|
| `contract_id` | 存在 | 列名就是 `contract_id`，5行为真实值（如`clear_risk_02`），6行为占位描述文字 |
| `clause_id` | 存在 | 如 `c04`/`c01`/`c06`，仅在5行真实ID的行里有意义 |
| query | 存在 | 列名 `query`，内容是条款文字摘要 |
| 相关法条 | 存在 | 拆成 `candidate_law_name`+`candidate_article`+`candidate_legal_text`三列，其中 `candidate_legal_text` **刻意不填写法条原文**（见第5节） |
| 人工核验状态 | 存在 | `human_review_status` 列 |
| 复核人员 | **不存在** | 17列中没有任何"复核人/reviewer"字段 |
| 复核时间 | **不存在** | 没有任何时间戳字段（无 `reviewed_at`/`created_at`等） |

## 4. 核验状态真实分布（CONFIRMED，逐行读取，不是凭列名猜测）

```
human_review_status 分布：pending ×11（100%）
human_confirmed_evidence_ids 非空行数：0 / 11
```

**没有任何一行标记为 confirmed/corrected/rejected/unable_to_determine。全部11行都停留在 pending（待复核）状态**，`human_confirmed_evidence_ids`（人工确认后的证据ID列表）全部为空。"说明"工作表里列出的合法取值是 `confirmed / corrected / rejected / pending / unable_to_determine` 五种，当前实际只出现了其中一种。

**重要澄清（按用户要求明确指出）**：表格标题含"人工核验"字样，**不代表其中标签已通过人工核验**——根据本轮实际读取的字段值，这是一份**尚待开展人工复核工作的工作表**，不是复核已完成的记录。

## 5. 是否可作为可靠标注来源（CONFIRMED结论）

**不可以，当前阶段只是一份待复核工作表（pending review worksheet），不是可靠的 gold standard 标注来源。** 证据：
- 全部11行 `human_review_status=pending`，0行完成人工确认；
- `candidate_legal_text` 列的设计说明（工作表内原文，CONFIRMED）明确写着："本表不抄录法条原文——避免把未逐字核验的模型记忆当作已核验内容；请参照官方来源或知识库现有文本核对"——即当前每行的候选法条本身也还停留在"模型给出的候选"层面，连候选本身的原文都还没有被转录进表格去对照；
- `candidate_evidence_id` 列至少有1行显式标注"本表未填充，见知识库指纹清单"，意味着候选法条与当前 Chroma 实际索引ID之间**尚未建立字段级映射**；
- `ai_confidence` 列的取值本身就是"低/中/中高/高"这种模型自评置信度，部分行还附带不确定性说明（如"知识库完全没有《劳动法》，无法确认具体条号"），这正是**需要人工介入**的信号，而不是已经核验完的结果。

## 6. 与现有50份合同 / 315条款 / 188条候选标签样本的关联（CONFIRMED部分 + UNKNOWN部分）

**本轮实际交叉核实**：取出11行中5个真实 `contract_id`（`boundary_04`、`clear_risk_02`、`clear_risk_05`、`compliant_06`、`compliant_10`），与 `data/eval_samples/manifest.json`（50份合同清单，CONFIRMED本轮已读取）里的 `samples[].sample_id` 字段逐一比对——

**结果：全部5个 contract_id 均能在 manifest.json 中找到完全匹配的 sample_id**，证明这5行确实对应现有50份合同中的真实样本（CONFIRMED，非猜测）。

**未能完成的交叉核实（UNKNOWN，本轮未做）**：
- 另外6行（占位描述文字行）本轮**未**打开 `retrieval_eval_samples.json`（272132B）去定位它们描述的具体场景对应的真实 `sample_id`——这是明确的证据缺口，不是"假定无法关联"。
- 5个真实 contract_id 对应的具体 `clause_id`（如 `c04`）本轮**未**进一步核对是否能在对应合同的 `clauses.json`（运行态数据）或 `data/eval_samples/answers/*.json`（标准答案）中精确定位到同一条款——只核实了 contract_id 层级的存在性，没有核实到 clause 层级的字节级一致。

**缺少的主键/映射信息（如果要做成系统化关联）**：
- 需要一份"占位描述文字 → 真实 sample_id"的显式映射表，当前这6行只能靠人工阅读描述文字去 `retrieval_eval_samples.json` 里查找，不是机器可解析的关联；
- 没有 `candidate_evidence_id` 到当前 Chroma 实际文档ID的映射（表内已自陈此空缺）。

## 7. 本轮读取范围声明

本轮通过 `device_stage_files` + 本地 `openpyxl` 脚本完整读取了该文件的全部2个工作表、全部17列、全部15个数据行（11+4），是**全量读取**，不是抽样。未执行的检查：未打开 `retrieval_eval_samples.json`/`clauses.json`/`answers/*.json` 做6行占位数据的精确定位（见上文UNKNOWN项）。
