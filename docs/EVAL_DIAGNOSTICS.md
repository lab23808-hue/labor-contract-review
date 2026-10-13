# 端到端质量评估的诊断体系

本文档说明：(1) 诊断分层方法，(2) 哪些实验在本沙箱真实跑过、哪些只有脚本和
本地命令，(3) 本次真实运行**已经发现**的具体问题及根因，(4) 每个未跑实验的
本地运行方式。

## 1. 诊断分层（A-G）

每一处"标准答案 vs 系统实际结果"的差异，归到下面某一层，归不清楚就标记
`unknown`，不强行归因：

| 层 | 名称 | 本沙箱可独立诊断？ |
|---|---|---|
| A | 文档解析错误 | ❌ 需要 `document/parser.py`，未阻断依赖，但未在本次范围内测（本次 50 份样本直接从标准答案构造 `Clause`，没有经过 `document.parser` 的 PDF/docx 解析这一步） |
| B | 条款切分错误 | ❌ 需要 `document/splitter.py`（依赖 `langchain_text_splitters`） |
| C | RAG 检索错误 | ❌ 需要 `rag/database.py`（依赖 `langchain_chroma` + BGE-M3） |
| D | LLM 判断错误 | ❌ 需要 `llm/client.py`（依赖 `openai` + API Key） |
| E | 规则校验错误 | ✅ 本次真实跑通，见第3节——**已发现3处真实问题** |
| F | 结果合并或报告错误 | 部分✅：`workflows/review_workflow.py::report_assembly` 里 `ReviewVersions` 赋值问题已修复并测试（见下方第2节结尾），但合并逻辑本身（LLM结果+规则结果去重/冲突处理）依赖完整 workflow，本沙箱未跑 |
| G | 其他/无法确定 | 实验2-5/7 和实验6的LLM部分，本沙箱完全没跑，所有相关差异都应标记 G/unknown，不能归到任何具体层 |

## 2. 本沙箱真实执行的部分（层 E + 层 F 的一部分）

### 2.1 实验1：知识库覆盖检查（纯文本比对）

- 实现：`evaluation/diagnostics.py::experiment1_knowledge_coverage()`
- 方法：独立重新扫描 `data/knowledge/*.txt`，用和
  `scripts/validate_knowledge_base.py` 相同的"第X条"切分正则，收集真实存在
  的条号集合；再扫描全部 50 份标准答案里的 `legal_basis` 字段，逐条检查
  对应条号是否在知识库里存在。
- **不信任**标准答案自己标注的 `legal_basis_verified_in_sources` 字段
  （那是标注时的自我声明，这里要的是独立验证）。
- 真实结果：15/15（100%）能找到对应条号——见
  `tests/test_eval_rules_diagnostics.py::test_experiment1_on_real_generated_answers_and_knowledge_base`
  （真实执行，非 mock）。

### 2.2 实验6（规则部分）：规则层独立召回/精确率 + 已知缺口统计

- 实现：`evaluation/diagnostics.py::experiment6_rule_layer_check()`
- 方法：绕开需要 `langchain_text_splitters` 的 `ClauseSplitter`，直接用
  标准答案里的 `clause_id`/`original_text`/`start_char`/`end_char` 构造
  真实的 `schemas.Clause` 对象，喂给**真实生产代码** `rules.RuleChecker`，
  用它真实跑出来的 `ReviewResult` 和 `rule_expectations.json` 里记录的
  预期逐条款比对。
- 三类结果严格区分（这是本次修复的关键设计）：
  - `missed`：`rule_expectation.expected_hit=True`（这条规则**设计上就该**
    命中）但实际没命中——真正的回归/bug。
  - `false_positive`：预期不命中但实际命中了——真正的误报。
  - `known_limitation_gap`：标准答案里 `ClauseAnswer.risk=True`（法律上
    真的有风险）但 `rule_expectation.expected_hit=False`（我们在设计
    `clause_bank.py` 条款原型时就已经知道、并主动标注"这条规则目前的
    实现能力够不到这种写法"），且实际确实没命中——**这不是本次运行发现
    的新问题**，是"规则从设计上就没打算覆盖"的已知边界，必须和上面两类
    分开统计，否则"规则能力边界在哪"会被完全隐藏在 recall 数字背后。
- 真实结果：recall=0.8235，precision=0.875，3 个真实漏检，2 个真实误报，
  28 个已知缺口（主要是：日期区间表达的合同期限、依赖《劳动法》而非
  《劳动合同法》的加班费条款等——这些是知识库/规则能力边界，不是bug）。

### 2.3 真实发现的 3 个问题（有证据，不是猜测）

**问题1（已修复，见下方"问题1/2 修复记录"）：`rules/probation_salary.py` 的百分比正则不认识"零"**

```python
_PERCENT_RE = re.compile(
    r"试用期工资[^。\n]{0,20}?(?:百分之(?P<cn>[一二三四五六七八九十百]{1,3})|(?P<num>\d{1,3})\s*%)"
)
```

字符类 `[一二三四五六七八九十百]` 里没有"零"。`clear_risk_06` 的条款原文是
"试用期工资为正式工资标准的**百分之零**"（0%，比任何法定下限都低，理应是
最明显的风险），但这个正则匹配不到"零"，`_extract_percent()` 返回 `None`，
`check_probation_salary()` 直接跳过这条——造成**漏检**（见
`experiment6_rule_layer_check()` 真实运行结果里的
`{"sample_id": "clear_risk_06", "clause_id": "clear_risk_06_c02"}`）。

**问题2（已修复，见下方"问题1/2 修复记录"）：`rules/probation_duration.py` 跨条款取值用"第一次出现"而不是"配对的那一条"**

`check_probation_duration()` 的逐条款循环对"合同期限"和"试用期月数"分别
独立地取**第一次成功提取到的值**，不管它们是否来自同一条款、是否逻辑上
应该配对：

```python
for clause in clauses:
    if duration is None:
        found = _extract_duration(clause.original_text)
        if found is not None:
            duration = found
            duration_clause_id = clause.clause_id
    if probation_months is None:
        months = _extract_probation_months(clause.original_text)
        if months is not None:
            probation_months = months
            probation_clause_id = clause.clause_id
```

`boundary_01` 合同里有两处提到"试用期"：第三条"试用期工资"条款原文恰好
也写了"乙方试用期为**3个月**"（这是为测试 `probation_salary` 规则而设计的
上下文句，不是真正的合同期限条款），第四条"合同期限及试用期"才是真正描述
合同期限（一年）和试用期（**2个月**）的条款。规则按条款顺序扫描，先在
第三条拿到 `probation_months=3`（来自一句不相关的上下文），后在第四条
拿到 `duration=12个月`，于是把两个不该配对的数字凑成一对——`3个月 > 12
个月合同允许的上限2个月`，误判为违规。真实情况（第四条本身：一年期+2个月
试用期）是完全合规的边界值。造成**误报**（见真实运行结果里的
`boundary_01_c02`/`boundary_01_c03`）。

这暴露的是规则设计上的一个真实限制：当前实现假设"合同里只有一处会提到
试用期月数"，当测试样本（或真实合同）里有多处提及试用期相关数字时，
配对逻辑是不可靠的。

### 问题1/2 修复记录（2026-10-10，第二轮任务）

两个问题均已按最小改动原则修复，完整的"问题现象/根因/方案/为什么这样
选择/验证结果"记录在 `docs/PITFALLS.md` 的 **P-27**（问题1）和
**P-28**（问题2），这里只摘录和评估基准直接相关的部分：

- **修复方式**：
  - 问题1：`_PERCENT_RE` 的中文数字字符类加入"零"，百分号同时接受半角
    `%` 和全角 `％`。不改动 `_cn_percent_to_int()`（它已经原生支持
    "零"→0）和比较逻辑。
  - 问题2：`check_probation_duration()` 改为两步——优先寻找**同一条款
    内**同时能提取出期限和试用期月数的情况并直接采用；只有当没有任何
    一条条款同时具备两者时，才退回原来的逐条款独立扫描（保证现有全部
    测试用例的行为不变）。
- **回归测试**：先在不改动源码的情况下写好测试，确认旧实现下按预期
  失败（问题1：3个新测试失败；问题2：2个新测试失败），再应用修复，
  确认全部通过，且额外补充的边界测试（防止"加了零就误判正常比例"、
  "没有同条款配对时退回原逻辑不变"、"修复不能把真实违规一起隐藏"）
  也全部通过。详见 `tests/test_rules_probation_salary.py`（16个，+7）
  和 `tests/test_rules_probation_duration.py`（16个，+4）。
- **修复前后指标对比**（`scripts/run_eval_samples.py` 同一套50份样本，
  规则层诊断实验6）：

  | 指标 | 修复前 | 修复后 | 变化 |
  |---|---|---|---|
  | missed_count（真实漏检） | 3 | 2 | −1（`clear_risk_06` 不再漏检，问题1贡献） |
  | false_positive_count（真实误报） | 2 | 0 | −2（`boundary_01` 两条误报清零，问题2贡献） |
  | known_limitation_gap_count | 28 | 28 | 不变（符合预期——这两个修复不改变"已知能力缺口"的范围） |
  | recall | 0.8235 | 0.8824 | +0.0589 |
  | precision | 0.875 | 1.0 | +0.125 |
  | 全部规则层测试（含新增回归测试） | 44 passed（修复前） | 60 passed（+16个新测试） | 0 failed |

  剩余的 2 个 `missed`（`clear_risk_10_c02`、`mixed_08_c05`）就是下面
  "问题3"的 task_based 场景——**本次修复没有、也不应该覆盖它**，详见
  问题3的调查结论。

**问题3（已完成调查，本次明确不修改规则或样本）：`_TASK_BASED_RE` 要求字面出现"工作任务"**

```python
_TASK_BASED_RE = re.compile(r"以完成一定[的]?工作任务为期限")
```

`clear_risk_10`/`mixed_08` 的条款原文是"本合同**以完成软件开发项目为期限**"
——这是 `clause_bank.py` 里 `task_based` 合同类型条款原型自己写的措辞，
不是法律条文的标准表述（标准表述应为"以完成一定的工作任务为期限"）。因为
缺少字面"工作任务"，`_extract_duration()` 判断不出这是"任务式合同"，也
提取不到固定期限，于是 `duration` 全程为 `None`，`check_probation_duration()`
直接返回空列表——造成漏检（`clear_risk_10_c02`、`mixed_08_c05`）。

**调查结论（排除法逐一核实，非猜测）**：

- **排除"条款切分导致上下文缺失"**：本次评估直接用标准答案里的
  `clause_id`/`start_char`/`end_char`/`original_text` 构造 `schemas.Clause`
  对象喂给 `RuleChecker`，完全没有经过 `document.splitter.ClauseSplitter`
  这一步（它在本沙箱也无法 import），规则拿到的就是完整条款原文，不存在
  "切分把期限信息和试用期信息拆散到了不同 clause"的可能性——用
  `_extract_duration()`/`_extract_probation_months()` 直接对这条完整原文
  手动调用验证过：`_extract_duration()` 确实返回 `None`，不是切分或
  传参环节丢失了文本。
- **排除"标准答案的风险判断本身错误"**：`risk=True`（任务式合同不得约定
  试用期）这个判断依据《劳动合同法》第十九条是对的——无论合同期限怎么
  措辞，只要本质上是"以完成一定工作任务为期限"的合同，都不得约定试用期，
  这和条款具体用"软件开发项目"还是"工作任务"描述任务内容无关。标准答案
  的风险结论没有问题。
- **确认是"规则正则范围"和"样本措辞"的组合**：`_TASK_BASED_RE` 的文档
  本身就声明这是刻意的窄范围设计（只覆盖能直接正则匹配的几种表述），
  只认字面"工作任务"这个法律术语，不认"软件开发项目"这类具体化的任务
  描述；而 `clause_bank.py` 为了让生成的合同读起来更像真实合同、更具体，
  换了说法，恰好落在了这个刻意收窄的范围之外。两者都不能单独定性为
  "bug"——规则按自己文档声明的范围工作是预期行为，样本用更具体的措辞也
  是合理的生成选择——但两者叠加导致了这条规则对这类具体化措辞的任务式
  合同系统性漏检。
- **本次明确不修改**：按任务要求，"除非发现原因明确且有充分测试支持，
  否则不修改这条规则"——这里原因虽然已经明确，但"该不该修"是一个产品
  范围决策（要不要让正则认识更多同义表述？要不要反过来把样本措辞改成
  法定术语？），不是单纯的 bug 修复，本次不擅自做这个决策，只记录结论，
  留给下一步明确指示后再处理。
- **未验证的内容**：真实合同里"任务式合同"用非标准措辞描述任务内容的
  比例有多高（如果很低，这个问题的实际影响有限；如果很高，放宽正则的
  优先级应该提高）——这需要更多真实样本或业务方反馈，本次没有数据支持
  这个判断，不做推测。

**问题3（归因存疑，标记为待确认）：`_TASK_BASED_RE` 要求字面出现"工作任务"**

```python
_TASK_BASED_RE = re.compile(r"以完成一定[的]?工作任务为期限")
```

`clear_risk_10`/`mixed_08` 的条款原文是"本合同**以完成软件开发项目为期限**"
——这是 `clause_bank.py` 里 `task_based` 合同类型条款原型自己写的措辞，
不是法律条文的标准表述（标准表述应为"以完成一定的工作任务为期限"）。因为
缺少字面"工作任务"，`_extract_duration()` 判断不出这是"任务式合同"，也
提取不到固定期限，于是 `duration` 全程为 `None`，`check_probation_duration()`
直接返回空列表——造成漏检（`clear_risk_10_c02`、`mixed_08_c05`）。

这一处**不确定该归为层 E（规则正则确实偏窄，不认识同义表述）还是归为
"评估样本措辞不够贴近法律标准表述"**（更接近生成器/标注问题，而非生产
代码问题）——按本文件开头的原则，归不清楚就不强行归因，这里明确标记为
`unknown`，留给下一步决定：要么把 `clause_bank.py` 里这个条款原型的措辞
改成法律标准表述重新生成，要么把 `_TASK_BASED_RE` 放宽覆盖更多同义说法。

### 2.4 `ReviewVersions` 修复（层 F 的一部分）

`workflows/review_workflow.py::report_assembly` 原来构造
`ReviewVersions()` 时四个字段都没有传值，导致最终报告里模型名/prompt
版本/规则集版本/知识库版本全部是默认空值——哪怕真的跑了评审，也无法从
报告反查当时用的是哪个版本的规则/知识库/prompt，复盘和回归对比都无从下手。
已修复为从 `reviewer.llm_client.model`、`prompts.review.PROMPT_VERSION`、
`rule_checker.ruleset_version`、`data/knowledge/VERSION` 四处实际读取，
测试见 `tests/test_review_versions.py`（6 passed，但受限于本沙箱无法
import `workflows.review_workflow`，测试只验证了独立可测的部分，完整
`report_assembly()` 的集成测试需要本地环境）。

## 3. 本地运行实验2/3/4/5/7的方式

以下命令假设已完成 `docs/EVAL_BASELINE.md` 第5节的步骤1-4（装依赖、配置
`.env`、构建知识库）。

### 实验2：条款切分检查

目标：标准答案里的条款边界/原文/顺序 vs `document.splitter.ClauseSplitter`
真实切分结果，逐条对比文本和边界，不能只看"切出了多少条"。

```bash
python -c "
from document.splitter import ClauseSplitter
from evaluation.generate_contracts import build_all_contracts
splitter = ClauseSplitter()
for contract in build_all_contracts():
    got = splitter.split(contract.full_text)
    print(contract.sample_id, '标准答案条款数=', len(contract.clauses), '实际切分条款数=', len(got))
    # TODO: 逐条比较 got[i].original_text 和 contract.clauses[i].original_text，
    # 以及边界 start_char/end_char 是否一致，不是只比数量
"
```

### 实验3：RAG 独立检索检查

目标：Recall@K、MRR、不相关证据占比；用不同 K 值；区分"知识库里没有"
和"知识库里有但没检索到"。**必须先有一份人工标注的"条款->应检索到的
法条"对照表**，不能只用系统自己的检索结果当 ground truth。

```bash
python scripts/build_knowledge_base.py  # 先用真实 BGE-M3 构建向量库
python -c "
from rag.database import ChromaKnowledgeBase
from rag import build_embedder
kb = ChromaKnowledgeBase(build_embedder())
# TODO: 对每条标准答案的 clause.original_text 发起检索，
# 和人工标注的相关法条集合算 Recall@K / MRR
"
```

### 实验4：区分切分问题与检索问题

目标：用标准条款文本做 query，和用实际切分出来的文本做 query，分别检索，
对比两组结果的差异——如果用标准文本检索效果明显更好，说明问题主要在切分
（层B），不在检索本身（层C）。依赖实验2+实验3的结果。

### 实验5：区分检索问题与LLM判断问题

目标：三组对照（原始系统结果 / 用标准条款文本重新走检索+LLM / 直接把
标准法律依据喂给LLM），控制输入差异，判断问题出在检索召回不到证据
（层C）还是LLM拿到对的证据还是判断错了（层D）。需要固定
`temperature`/模型版本并重复跑几次处理非确定性。

```bash
# 需要 DEEPSEEK_API_KEY
python -c "
from llm.client import build_deepseek_client
# TODO: 对同一批条款分别用三种输入组合调用 LLM，比较风险判断结果
"
```

### 实验6（LLM部分）：规则/LLM/合并三者独立对比

规则部分已在本沙箱真实跑通（见第2.2节）。LLM部分需要：

```bash
python scripts/run_eval_samples.py --mode online --stage 6
# TODO: 分别保存 LLM 原始结果、规则原始结果、合并后结果，
# 统计规则独立发现的风险数、LLM独立发现的风险数、合并时丢失的结果数、
# 两者冲突（同一条款规则说有风险LLM说没有，或反之）的数量
```

### 实验7：端到端质量评估

```bash
python scripts/run_eval_samples.py --mode online --stage 7 \
  --output data/eval_samples/results/e2e_$(date +%Y%m%d_%H%M).json
# TODO: 对全部50份合同跑完整 workflows.review_workflow，
# 按风险类别/级别/法律依据分别统计 Precision/Recall/F1（不要合成一个总准确率），
# 记录平均耗时、P95耗时、API调用次数、token用量（如果 llm/client.py 暴露了用量字段）
```

> 以上标了 `TODO` 的地方是本地需要你补充的对比/统计逻辑——本沙箱从未
> 执行过这些代码路径，所以这里只给出能跑通"调用到真实依赖"这一步的骨架
> 命令，不假装已经验证过具体的对比逻辑。

## 4. 未解决问题与后续优化建议（优先级从高到低）

> **2026-10-10 更新**：下面第 1、2 项在这份清单写下时还是"待办"，
> 现在已经完成（见本文件上方"修复记录"小节和 `docs/EVAL_BASELINE.md`
> 第4节"修复前后对比"）——保留原文字不是疏漏，是为了留住"当时为什么
> 认为这两项优先级最高"的记录，紧跟着补充完成状态，不删除历史描述。

1. ~~**修复 `rules/probation_duration.py` 的跨条款配对逻辑**（问题2）——
   这是当前唯一一个会产生"误报"的已知规则 bug，且逻辑本身有代表性
   （任何"合同里出现多处相似数字"的场景都可能触发），值得先修。~~
   **已完成**（P-28，见 `docs/PITFALLS.md`）。
2. ~~**修复 `rules/probation_salary.py` 的百分比正则**，把"零"加入字符类
   （问题1）——改动极小，风险极低，能直接修掉一个漏检。~~
   **已完成**（P-27，见 `docs/PITFALLS.md`）。
3. **把实验3/4/5/7 在有真实网络/API Key 的环境里跑一遍**，拿到 RAG 和
   LLM 层面的真实数据——目前端到端质量的大头（RAG 检索是否准、LLM
   判断是否对）完全没有数据支撑，规则层只是整个系统的一小部分。
   **仍未完成**，优先级不变，是当前最大的待办。
4.（次优先级）判定问题3（task_based 正则 vs 条款原型措辞不一致）到底
   改哪一边，并相应修复。**仍未完成**——2026-10-10 任务二核验过这两个
   样本的标准答案本身（`risk=True` 的法律依据准确），确认了"不该为了
   让规则命中就反过来改标准答案"，但规则和样本措辞之间该怎么取舍这个
   产品决策本身仍未做出。
5.（次优先级）组织真正的人工法律复核，把至少一部分 `candidate` 标准
   答案升级为有独立复核依据的状态——当前整套评估基准的可信度上限
   取决于这一步有没有做。**部分进展，仍未完成**：2026-10-10 完成了知识库
   条文文本的逐字核验，并把 315 条标准答案里 184 条升级为
   `verification_status=verified_against_source`（见
   `docs/EVAL_BASELINE.md` 第2节、`data/knowledge/SOURCES.md`）——但这
   仍然是开发者自己核对官方原文完成的，**不等于**这里说的"真正的人工
   法律复核"；`expert_reviewed` 这一档截至目前仍然是 0，这一项建议
   本身没有过时，优先级依然最高（评估基准可信度的上限仍然取决于它）。
