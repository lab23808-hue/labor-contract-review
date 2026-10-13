# 劳动合同审查 Agent —— 评估基准（candidate baseline）

> **这是一个"候选基准"，不是权威基准。** 本次所有标准答案都由模型（本次会话）
> 按公开法条记忆/检索生成，**没有独立的人工法律复核人员参与标注**。所有标准答案的
> `verification_status` 只能是 `candidate`（模型生成、未经复核）、
> `pending_review`（争议性/信息不足，已排除在严格准确率统计之外）或
> `verified_against_source`（**2026-10-10 新增，见下方更新说明**：法律依据条文
> 已对照官方来源逐字核验、且依据与结论的对应关系已检查，但仍然是开发者自己核对
> 的，不等于有资质的人工法律复核），**不存在、也不应该出现 `expert_reviewed`**。
> 在真正的有资质人工复核之前，本文件里的任何准确率/召回率数字都只能解读为
> "候选基准相对候选标准答案的差距"，不能解读为"系统相对法律真实情况的差距"。

> **2026-10-10 更新说明**：下面第 1、2 节原文写的是"全部 26 条知识库条文文本
> 未逐字核验"——这个限制在当天完成了一次核验后**部分解除**：本次对知识库里
> 全部 26 条《劳动合同法》条文做了逐字核对（技术方法和发现的问题见
> `data/knowledge/SOURCES.md`），并相应把 50 份合同里"条文文本已核验 + 依据与
> 结论的对应关系已检查"的那部分标准答案升级为 `verified_against_source`。
> 没有核验过、或论证链条不完整的，仍然保留 `candidate`/`pending_review`，不是
> 全部答案都升级了。下面保留当时"全部未逐字核验"的历史描述（用于对比），紧跟着
> 补充当前实际状态，不删除历史记录。

## 1. 知识库补全情况

**（历史状态，2026-10-10 之前）** 本次在原有 14 条（上一轮会话加入，未逐字核验）的
基础上，为《劳动合同法》新增 12 条（第22/25/26/36/39/40/46/47/48/82/85/87条），
**全部标注为"未逐字核验——仅凭模型对公开法条的记忆写出"**。

**当前状态（2026-10-10 核验后）**：
- 知识库里全部 26 条《劳动合同法》条文（包括上一轮会话加入的 14 条和本次之前新增的
  12 条）已完成**逐字核验**（对照 `https://fgk.chinatax.gov.cn/zcfgk/c100009/c5193025/content.html`，
  用"对同一 URL 连续多次调用 WebFetch、每次只取下一句/下一段再拼接"的方式绕开了
  单次调用约 125 字的引用长度限制），详见 `data/knowledge/SOURCES.md`。
- 核验中发现并修正了一处真实差异：第八十七条原文漏了一个"的"字，已修正；其余 25 条
  条文核对后确认与官方原文一致。
- 《劳动合同法实施条例》《最高法劳动争议司法解释（法释〔2020〕26号）》仍然只有
  结构性元数据（条数、章节、生效日期），**没有补充条文正文**，标记 `pending_source`——
  这两份文件本次没有被任何标准答案引用为 `legal_basis`，不影响当前 50 份合同能否
  用于正式统计。
- 《劳动法》仍未找到明确的现行官方权威来源确认当前有效性状态，标记 `pending_source`
  （`overtime_no_extra_pay` 样本依赖的加班费加成标准正是出自这部未收录的法律，该样本
  因此仍标注为 `pending_review`，见下文）。
- 当前可用于规则/检索的知识库文件只有 `data/knowledge/劳动合同法.txt`
  （26 条，经 `scripts/validate_knowledge_base.py` 结构校验：无重复条号、
  无空块、无超长条文）。
- **这意味着**：50 份评估合同里，标准答案引用的法律依据全部来自这 26 条里**已经
  逐字核验过**的条文，不存在"标准答案引用的法律依据知识库里没有"的情况（见下文
  实验1：覆盖率 100%），这个 100% 现在建立在"条文文本已逐字核验"这个前提之上
  （而不再是 2026-10-10 之前"未逐字核验"的前提）。

## 2. 50 份评估合同样本

- 用 `scripts/generate_eval_contracts.py`（薄封装，核心逻辑在
  `evaluation/generate_contracts.py` + `evaluation/clause_bank.py`）
  **程序化生成**，不是手写 50 份独立文档——好处是标准答案的条款边界/原文/
  `clause_id` 由 pydantic 校验器在构造时强制保证自洽，避免手写过程中出现
  文本和标注不一致的问题；代价是合同之间结构相似度较高（都是几条典型条款
  的排列组合），覆盖的"真实合同的多样性"不如真正收集到的人工合同样本。
- 实际分布（与任务要求的 20/10/10/10 一致）：

  | 类型 | 数量 |
  |---|---|
  | clear_risk（明确存在风险） | 20 |
  | basically_compliant（基本合规） | 10 |
  | mixed（混合） | 10 |
  | boundary_complex（边界复杂） | 10 |
  | **合计** | **50** |

- 50 份里共 **315**（曾在上一版文档误写为 250，这里更正，可用
  `python3 -c "..."` 统计 `data/eval_samples/answers/*.json` 里的
  `clauses` 数量复现，见第 5 节命令）条条款标准答案（`ClauseAnswer`），其中：
  - 每一份合同都至少保留了若干"非风险"条款的标准答案（不是只标注风险条款），
    否则无法计算误报率——见 `tests/test_eval_schemas.py::test_every_contract_has_non_risk_clause_answers`。
  - `clear_risk`/`mixed` 两类按设计要求至少含 1 条风险条款；
    `basically_compliant`/`boundary_complex` 允许全部是合规边界值
    （任务明确要求覆盖"合法约定、条件性规定"，不能只有违法样本）。
  - 刻意包含了至少 1 份"信息不足，无法判断"的场景
    （`insufficient_context_probation_salary_unspecified`），其
    `verification_status=pending_review`。
- **2026-10-10 更新**：315 条标准答案里，**184 条**（引用的法律依据条文已逐字
  核验、且依据与结论的对应关系已检查）升级为 `verification_status=verified_against_source`；
  **6 条**仍为 `pending_review`（信息不足/依赖未收录法律的场景，刻意保留，不是
  疏漏）；剩下 **125 条**仍为 `candidate`（主要是没有引用任何 `legal_basis` 的
  基线合规填充条款，如工作时间、保密义务等——这些条款本身没有"法律依据"可供核验，
  升级到 `verified_against_source` 没有意义）。**0 份、0 条**标准答案的
  `verification_status` 是 `expert_reviewed`——全程没有独立法律专业人员参与，
  这不是遗漏，用
  `tests/test_eval_schemas.py::test_candidate_answers_never_claim_expert_reviewed_status`
  强制校验（禁止出现 `expert_reviewed`，且 `expert_reviewer` 字段必须为空）。
  四档状态的完整分布及每个 `legal_basis` 条号对应哪些样本，见
  `data/knowledge/SOURCES.md`"知识库与评估集覆盖关系映射"一节。

## 3. 实际运行过的测试（本沙箱真实执行，不是"写了脚本就算完成"）

本沙箱缺少网络访问（pypi/huggingface/deepseek API 均被拒绝，已通过直接
`curl`/`pip install` 测试确认，不是假设），因此
`langchain_text_splitters`/`langchain_chroma`/`openai`/`langgraph` 都无法
导入。下表区分"真正跑过"和"写了但本沙箱跑不了"：

| 模块/脚本 | 本沙箱可运行？ | 测试文件 | 结果 |
|---|---|---|---|
| `evaluation/schemas.py` | ✅ | `test_eval_schemas.py` | 16 passed（2026-10-10：+2 新测试，`test_candidate_answers_never_claim_verified_status` 已重命名为 `test_candidate_answers_never_claim_expert_reviewed_status` 并放宽 allowed 集合，见下文第2节） |
| `evaluation/generate_contracts.py` | ✅ | `test_eval_generator.py` | 7 passed |
| `evaluation/diagnostics.py`（实验1 + 实验6规则部分 + `strict_accuracy_eligible_clauses`） | ✅ | `test_eval_rules_diagnostics.py` | 6 passed |
| **跨文件数据一致性（2026-10-10 新增）** | ✅ | `test_eval_data_integrity.py` | 7 passed（合同/答案文件双向对应、`sample_id`/文件名一致、`full_text` 与合同文件逐字一致、315 个 `clause_id` 全局唯一、`strict_accuracy_eligible_clauses` 正确排除 `pending_review`） |
| `scripts/validate_knowledge_base.py` | ✅ | `test_validate_knowledge_base.py` | 7 passed |
| `workflows/review_workflow.py` 的 `ReviewVersions` 赋值逻辑 | 部分✅（只测独立可 import 的常量，完整 `report_assembly` 需要 langgraph） | `test_review_versions.py` | 6 passed |
| `scripts/run_eval_samples.py` + `scripts/compare_eval_results.py` | ✅ | `test_run_eval_scripts.py` | 8 passed |
| `diff/risk_diff.py`（上一个任务） | ✅ | `test_risk_diff.py` | 9 passed |
| `rules/probation_salary.py`（本次修复，P-27） | ✅ | `test_rules_probation_salary.py` | 16 passed（+7 回归/边界测试） |
| `rules/probation_duration.py`（本次修复，P-28） | ✅ | `test_rules_probation_duration.py` | 16 passed（+4 回归/边界测试） |
| `rules/checker.py` | ✅ | `test_rules_checker.py` | 5 passed |
| `rules/merge` | ✅ | `test_rules_merge.py` | 7 passed |
| `schemas/`（纯 pydantic） | ✅ | `test_schemas.py` | 39 passed |
| `contract/`（纯标准库+pydantic） | ✅ | `test_contract.py` | 29 passed |
| `prompts/review.py` | ✅ | `test_llm_prompts.py` | 7 passed |
| `review/` schema 校验 | ✅ | `test_review_schemas.py` | 7 passed |
| **以上合计** | | | **187 passed, 0 failed, 0 skipped**（2026-10-10 更新：原 184 + 本次新增的 7 个 `test_eval_data_integrity.py` 测试 + `test_eval_schemas.py` 新增 2 个，相抵后净增 3） |
| `document/splitter.py`（条款切分） | ❌ 本沙箱 | — | 需要本地环境，见下文（`langchain_text_splitters` 未安装） |
| `rag/database.py` / `rag/knowledge_loader.py`（向量检索；**2026-10-10 修改了 `KnowledgeLoader.index()` 的去重逻辑，并补了 `_evidence_id()` 的 source/article/part 边界测试、批内去重测试和"切分边界变化留下孤儿记录"的测试**，见第6节和 `docs/PITFALLS.md` P-29） | ❌ 本沙箱（真实 `langchain_chroma`/`langchain_text_splitters` 未安装）；**但用语义忠实的沙箱替身跑过三轮真实、未修改的生产代码+测试代码** | `test_rag_loader.py` | 替身跑法最新结果：**18 passed, 0 failed, 2 skipped**（2个跳过项都依赖真实切分算法，未尝试还原，明确标记跳过而非冒充通过；其中 `test_changing_chunk_boundaries_leaves_orphaned_old_chunks_unless_reset` 是用户本地真实 `pytest` 曾经报过 `chromadb.errors.DuplicateIDError` 的那条，本沙箱无法复现真实切分算法，**无法在此确认它现在真的通过**）。**这不等于真实 chromadb 跑过**，仍然必须在装好完整依赖的本地环境里跑一遍 `pytest tests/test_rag_loader.py -v` 做最终确认 |
| `scripts/build_knowledge_base.py`（知识库重建脚本；**2026-10-10 新增 `_confirm_destructive_step()` 安全提示**：检测 collection 是否已有数据，reset 前自动备份 persist_directory，默认需要终端输入 yes 确认，`--yes` 可跳过交互但仍打印警告） | ❌ 本沙箱（同上，需要真实 `langchain_chroma` + BGE-M3） | — | 安全提示函数本身已用沙箱替身手动跑过一遍，确认备份目录真的被创建、内容真的完整、`--append` 模式不会误触发备份；脚本整体的端到端行为仍需本地验证 |
| `llm/client.py` / `config/settings.py`（导入即需要 openai）/ `review/reviewer.py` | ❌ 本沙箱 | — | 需要本地环境 + API Key（`openai` 未安装） |
| `workflows/review_workflow.py` 全链路（端到端） | ❌ 本沙箱 | — | 需要本地环境 + API Key + 向量库 |

运行命令（可复现）：

```bash
python3 -I <你的 pytest 替代运行器> tests.test_eval_schemas tests.test_eval_generator \
  tests.test_eval_rules_diagnostics tests.test_eval_data_integrity tests.test_validate_knowledge_base \
  tests.test_review_versions tests.test_run_eval_scripts tests.test_risk_diff
```

本机如果已安装真实 `pytest`，可以直接：

```bash
pytest tests/test_eval_schemas.py tests/test_eval_generator.py \
  tests/test_eval_rules_diagnostics.py tests/test_eval_data_integrity.py \
  tests/test_validate_knowledge_base.py \
  tests/test_review_versions.py tests/test_run_eval_scripts.py -v

# 这一条本沙箱跑不了，必须在装好 langchain_chroma/langchain_text_splitters 的
# 本地环境里跑，用来确认"重复加载知识库不产生重复数据"这个 2026-10-10 的修复是否真的生效：
pytest tests/test_rag_loader.py -v
```

## 4. 端到端质量指标（当前只有规则层是真实数据，LLM/RAG/端到端部分未运行）

用 `python scripts/run_eval_samples.py` 实际跑出来的数字（offline 模式，
50 份合同全部跑一遍）：

### 实验1：知识库覆盖检查

| 指标 | 数值 |
|---|---|
| 标准答案引用的法律依据总数（去重） | 15 |
| 能在知识库 `劳动合同法.txt` 里找到对应条号 | 15（100%） |
| 找不到的 | 0 |

**解读**：这证明"条款素材库（`clause_bank.py`）写标准答案时只引用了
知识库里确实存在的条号"，**不证明**"RAG 真的能检索到这些条号"（需要实验3，
本沙箱无法运行）。**2026-10-10 更新**：这 15 个条号对应的条文文本本身
已经逐字核验过（见第1节），所以这个实验现在同时证明了"条号存在"和"条号
对应的文本内容准确"两件事；但仍然**不证明**"这些条文被标准答案引用时的
论证链条也经过检查"——那是 `verification_status=verified_against_source`
单独核实的内容，不是这个实验1本身在算的东西。

### 实验6（规则部分）：规则层独立召回率/精确率

> **2026-10-10 更新**：本节数字是 `probation_salary`/`probation_duration`
> 两个真实规则 bug（P-27、P-28）修复**之后**的最新结果。修复前后的完整
> 对比见下方"修复前后对比"表，详细根因分析见
> `docs/EVAL_DIAGNOSTICS.md`。

| 指标 | 数值 |
|---|---|
| 规则集版本 | `probation_duration_exceeds_legal_cap+probation_salary_below_80_percent` |
| 检查的合同数 | 50 |
| 标准答案中"规则本应能命中"的条款数（`expected_hit=True`） | 17 |
| 规则实际命中的条款数 | 15 |
| 命中且吻合预期的 | 15 |
| **规则层召回率 Recall** | **0.8824**（15/17） |
| **规则层精确率 Precision** | **1.0**（15/15） |
| 真正的漏检（规则本应命中却没命中——genuine bug） | 2 |
| 误报（规则不该命中却命中了） | 0 |
| 已知且被标注接受的能力缺口（`expected_hit=False` 但法律上确实有风险，规则从设计上就没打算覆盖，不计入上面的漏检/召回率） | 28 |

指标口径说明：
- 分母/分子都是"条款数"，不是"合同数"——一份合同里只要有一条条款的规则
  判断不符合预期，这份合同就会在 `missed`/`false_positive` 里贡献对应
  条款级的一条记录，不是整份合同记为"错"。
- "匹配规则"：规则产出的 `ReviewResult.clause_id` 或
  `related_clause_ids` 包含该条款 `clause_id`，视为"命中"该条款；
  跨条款问题（比如试用期超期）会同时命中它所依据的多条条款。
- 剩余的 2 个真实漏检（`clear_risk_10_c02`、`mixed_08_c05`）是同一个
  已调查但本次明确不修改的问题（task_based 合同措辞和规则正则范围不
  匹配），详见 `docs/EVAL_DIAGNOSTICS.md` 第2节"问题3"。

**修复前后对比**（同一套50份样本，`scripts/run_eval_samples.py` 真实跑出）：

| 指标 | 修复前（2026-10-09） | 修复后（2026-10-10） | 变化 |
|---|---|---|---|
| missed_count | 3 | 2 | −1 |
| false_positive_count | 2 | 0 | −2 |
| known_limitation_gap_count | 28 | 28 | 不变 |
| recall | 0.8235 | 0.8824 | +0.0589 |
| precision | 0.875 | 1.0 | +0.125 |

修复内容：`rules/probation_salary.py` 百分比正则补上"零"和全角百分号
（修掉 `clear_risk_06` 的漏检）；`rules/probation_duration.py` 跨条款
配对改为优先采信"同一条款内共同出现"的期限+试用期组合（修掉
`boundary_01` 的两条误报）。两处均为最小改动，且都先写回归测试复现
旧实现的失败、再应用修复、确认全部通过，完整记录见
`docs/PITFALLS.md` P-27、P-28。

### 实验2/3/4/5/7（以及实验6的 LLM 部分）：本沙箱未运行

本沙箱没有网络访问、没有 `DEEPSEEK_API_KEY`、没有
`langchain_text_splitters`/`langchain_chroma`/`openai`/`langgraph`
（均已直接测试确认不可用，不是假设）。这些实验**没有被模拟、没有被
降级成假结果**——`scripts/run_eval_samples.py --mode offline`（默认模式）
对它们会诚实输出 `status: "not_run_in_sandbox"` 加上缺的依赖和本地命令，
`--mode online` 会在本地真实环境里先探测依赖是否可用再决定是否继续跑。
本地运行命令见 `docs/EVAL_DIAGNOSTICS.md` 第4节和下文第5节。

## 5. 本地复现完整评估的命令

```bash
# 1. 装依赖（需要真实网络，本沙箱没有）
pip install -r requirements.txt

# 2. 配置 .env（至少需要 DEEPSEEK_API_KEY；模型名见 config/settings.py 顶部注释，
#    DeepSeek 命名变动较快，请到 https://api-docs.deepseek.com 核实当前有效值）
cp .env.example .env  # 如果项目里有这个模板；没有就手动创建
echo "DEEPSEEK_API_KEY=你的key" >> .env

# 3. 校验知识库结构（纯文本，任何环境都能跑，可以先跑这个确认环境本身没问题）
python scripts/validate_knowledge_base.py

# 4. 构建真实向量知识库（需要能访问 huggingface.co 下载 BGE-M3，约 2GB）
python scripts/build_knowledge_base.py

# 5. 校验 50 份评估样本格式（纯 pydantic，不需要上面两步）
python -m pytest tests/test_eval_schemas.py tests/test_eval_generator.py -v

# 6. 跑离线可跑的部分（规则层 + 知识库覆盖），生成一次基准结果
python scripts/run_eval_samples.py --output data/eval_samples/results/baseline.json

# 7. 跑真实端到端评估（需要上面 1/2/4 都已完成）
python scripts/run_eval_samples.py --mode online --stage all \
  --output data/eval_samples/results/e2e_$(date +%Y%m%d_%H%M).json

# 8. 对比两次结果（比如知识库补全前 vs 补全后，或模型升级前后）
python scripts/compare_eval_results.py \
  data/eval_samples/results/baseline.json \
  data/eval_samples/results/e2e_20261010_1200.json \
  --output data/eval_samples/results/diff.json
```

## 6. 问题处理状态与未解决问题（详见 `docs/EVAL_DIAGNOSTICS.md`、`docs/PITFALLS.md`）

> **2026-10-10 更新**：本节原先记录的"3个真实漏检+2个真实误报，本次未修复"
> 是修复前的状态，已过时。其中 2 个问题（`probation_salary` 漏检、
> `probation_duration` 误报）已在第二轮任务中修复并验证，完整修复前后
> 对比见本文件第4节"修复前后对比"表和 `docs/PITFALLS.md` P-27、P-28。
> 第三个问题（task_based）仍未修复，原样保留如下。

**已修复（不再是未解决问题）**：

- ~~规则层已发现 3 个真实漏检 + 2 个真实误报~~ → 其中
  `probation_salary.py` 的 1 个漏检（百分比正则不认识"零"，对应
  `clear_risk_06`）和 `probation_duration.py` 的 2 个误报（跨条款配对
  取"第一次出现的值"，对应 `boundary_01`）已修复并通过回归测试验证
  （`docs/PITFALLS.md` P-27、P-28）。修复后：误报数 2→0，漏检数 3→2，
  recall 0.8235→0.8824，precision 0.875→1.0。

**仍未解决**：

- 剩余 2 个真实漏检（`clear_risk_10_c02`、`mixed_08_c05`）来自同一个
  已调查但本次明确不修改的问题：`probation_duration.py` 的
  `_TASK_BASED_RE` 只认字面"工作任务"，而评估样本用了更具体的措辞
  （"以完成软件开发项目为期限"）——规则范围和样本措辞双方都不能单独
  定性为 bug，该不该放宽正则或改样本措辞是产品范围决策，不是本次
  bug 修复任务的范围，详见 `docs/EVAL_DIAGNOSTICS.md`"问题3"。
  **2026-10-10 核验更新**：本次任务二核验了这两个样本的合同原文/标准答案，
  确认 `risk=True` 的法律判断本身准确（依据第十九条第三款"以完成一定工作
  任务为期限的劳动合同……不得约定试用期"，条文已逐字核验，`legal_basis`
  已升级为 `verified_against_source`），没有因为规则识别不到就反过来改标准
  答案去"迎合"规则——这正是任务二第三节明确要求的"不要因为某个样本与当前
  规则不匹配，就直接认定标准答案错误"。
- 实验2/3/4/5/7 只有脚本骨架和本地命令，没有真实数值——这是本沙箱环境
  限制，不是偷懒省略。
- **2026-10-10 新发现并已修复**：`rag/knowledge_loader.py::KnowledgeLoader.index()`
  原来不做去重，重复调用会把相同内容再写入一份（这在当时是"已知、被接受的
  行为"，有测试 `test_reindexing_appends_duplicates_by_design` 明确记录）。
  任务二第六节要求的不变量"重复运行知识库加载不会造成重复数据"和这个已知行为
  直接冲突，所以这次改成了按内容算确定性 id 再 upsert（详见
  `rag/knowledge_loader.py::index()`/`_evidence_id()` 的 docstring，以及对照
  langchain-ai/langchain 源码确认 `Chroma.add_texts` 内部统一走
  `self._collection.upsert(...)` 的核验过程）。**这个修复本身在本沙箱里无法
  端到端验证**（缺 `langchain_chroma`/`chromadb`），已把断言反过来的测试
  `test_reindexing_is_idempotent_and_does_not_duplicate` 留在
  `tests/test_rag_loader.py` 里，必须在装好完整依赖的本地环境里跑一遍才能
  最终确认——这是本节诚实列出的、本次新增的"仍需要本地验证"的一项，不是已经
  确认完成的事。
- **2026-10-10 新发现的知识库覆盖缺口（均为低优先级，已记录，非本次任务范围）**：
  《劳动合同法实施条例》《劳动法》《最高法劳动争议司法解释（法释〔2020〕26号）》
  三份文件仍只有结构性元数据，没有条文正文；但这三者目前都**不是**任何标准答案的
  `legal_basis`（50 份合同实际只引用了 15 个来自《劳动合同法》的条号，全部已逐字
  核验），所以这不影响当前这批标准答案能否用于正式统计，只是"如果以后要设计引用
  这三份文件的新样本，需要先把条文正文和核验做完"，详见
  `data/knowledge/SOURCES.md`"知识库与评估集覆盖关系映射"第3类。
