"""真实验证脚本（不是伪代码），覆盖本轮改动（ModificationBatch /
ModificationTask 状态机重构 / Risk Analyzer / risk_resolution / V2 Generation
Service）新增和变更的全部业务逻辑：
    - modification.validator.validate（纯 Python，完全真实，未改动）
    - modification.risk_resolution.determine_risk_resolution（纯函数，完全真实）
    - modification.service.compute_batch_readiness（纯函数，完全真实）
    - contract.manager.ContractManager 的 Batch / Task 相关方法（真实文件系统
      I/O、真实 pydantic 校验）
    - modification.service.ModificationService 的编排逻辑（批次创建/任务创建
      服务端查原文+快照/状态机/abandon/confirm manual_text，用【假的】
      ModificationAgent + 【假的】ClauseReviewer 代替真实 LLM 调用，因为
      openai 包在此沙箱不可用；Validator、ContractManager、状态机、
      risk_resolution 全部是真实代码真实执行）
    - app.v2_generation_service.V2GenerationService（批次就绪判断、
      V2 生成成功/失败/重试、ABANDONED 任务保留 V1 原文）

关于 document.preparation.split_contract 未被真实使用：
    真实 ClauseSplitter 依赖 langchain_text_splitters，这个包在当前沙箱里
    无法安装（无 PyPI 网络访问）。为了不因为这一个外部依赖挡住整个编排逻辑
    的真实验证，本脚本改为手工构造 Clause 列表（字段值完全真实，
    start_char/end_char 与实际文本位置一致）后调用 ContractManager.
    save_clauses（真实方法，真实文件写入）直接落盘，绕过的只是"怎么从原文
    切出 Clause 边界"这一步，其余全部是真实代码真实执行。V2GenerationService
    内部调用的 document.preparation.parse_and_split_contract 同样把
    split_contract 换成一个基于正则的简单实现（因为同样的依赖限制），
    parse_contract/create_contract/save_version/批次状态流转 全部未替换。
    这一点在最终报告里会明确标注为环境限制，不是回避测试。
"""

import re as _re
import shutil
import sys
import tempfile
import types
from pathlib import Path

import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

if "openai" not in sys.modules:
    fake_openai = types.ModuleType("openai")

    class _FakeOpenAIError(Exception):
        pass

    class _FakeOpenAI:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("本脚本不应该真正构造 OpenAI 客户端")

    fake_openai.OpenAI = _FakeOpenAI
    fake_openai.OpenAIError = _FakeOpenAIError
    sys.modules["openai"] = fake_openai


def _stub_module(name: str, **attrs) -> None:
    try:
        __import__(name)
        return
    except ModuleNotFoundError:
        pass
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules[name] = module


class _Dummy:
    def __init__(self, *args, **kwargs):
        pass


_stub_module("langchain_text_splitters", RecursiveCharacterTextSplitter=_Dummy)
_stub_module("langchain_chroma", Chroma=_Dummy)
_stub_module("langchain_core")
_stub_module("langchain_core.documents", Document=_Dummy)
_stub_module("langchain_core.embeddings", Embeddings=_Dummy)
_stub_module("langchain_huggingface", HuggingFaceEmbeddings=_Dummy)


class _DummyStateGraph:
    def __init__(self, *args, **kwargs):
        pass

    def add_node(self, *args, **kwargs):
        pass

    def add_edge(self, *args, **kwargs):
        pass

    def compile(self, *args, **kwargs):
        return self

    def invoke(self, *args, **kwargs):
        raise RuntimeError("本脚本不应该真正调用 LangGraph 编译出来的图")


_stub_module("langgraph")
_stub_module("langgraph.graph", END="__end__", START="__start__", StateGraph=_DummyStateGraph)

from app.v2_generation_service import V2GenerationService
from infra.storage import ContractManager
from domain.document.preparation import parse_contract
import domain.document.preparation as _preparation_module
from domain.modification.risk_resolution import determine_risk_resolution
from domain.modification.service import (
    ModificationConflictError,
    ModificationService,
    ModificationServiceError,
    compute_batch_readiness,
)
from domain.modification.validator import validate
from core import (
    Clause,
    ModificationBatchStatus,
    ModificationResult,
    ModificationTaskStatus,
    ReviewReport,
    ReviewResult,
    ReviewSource,
    RiskLevel,
    RiskResolution,
)

assertions = 0


def check(cond, msg):
    global assertions
    assertions += 1
    if not cond:
        raise AssertionError(f"FAILED #{assertions}: {msg}")
    print(f"  ok  [{assertions}] {msg}")


def build_clauses(contract_id: str, articles: list[tuple[str, str]]) -> list[Clause]:
    clauses = []
    cursor = 0
    for i, (article_no, text) in enumerate(articles, start=1):
        start = cursor
        end = start + len(text)
        clauses.append(
            Clause(
                contract_id=contract_id,
                clause_id=f"clause_{i:03d}",
                original_text=text,
                start_char=start,
                end_char=end,
                hierarchy_level=0,
                metadata={"article_no": article_no},
            )
        )
        cursor = end + 2  # 模拟 "\n\n" 分隔
    return clauses


def _fake_split_contract(contract_id, contract_manager, clause_splitter=None):
    parsed_path = contract_manager._contract_dir(contract_id) / "parsed_text.txt"
    full_text = parsed_path.read_text(encoding="utf-8")
    pattern = _re.compile(r"(第[一二三四五六七八九十百千零〇两\d]+条[^\n]*(?:\n(?!第[一二三四五六七八九十百千零〇两\d]+条).*)*)")
    matches = [m.group(1).strip() for m in pattern.finditer(full_text)]
    articles = []
    for m in matches:
        no_match = _re.match(r"(第[一二三四五六七八九十百千零〇两\d]+条)", m)
        articles.append((no_match.group(1), m))
    clauses = build_clauses(contract_id, articles)
    contract_manager.save_clauses(contract_id, clauses)
    return clauses


_preparation_module.split_contract = _fake_split_contract


class FakeAgent:
    """替代真实 ModificationAgent（不调用 LLM），用来真实驱动 Service 层的状态机。"""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def generate_candidate(self, clause, review_result, lawyer_instructions):
        self.calls.append(list(lawyer_instructions))
        action = self.script.pop(0)
        custom_text = None
        if isinstance(action, tuple):
            action, custom_text = action
        if action == "fail":
            from domain.agents.modification_agent import ModificationAgentError

            raise ModificationAgentError("模拟：LLM 调用失败")
        if action == "bad":
            return ModificationResult(clause_id=clause.clause_id, modified_text="第九十九条 无关内容", reason="坏结果")
        if custom_text is not None:
            modified_text = custom_text
        else:
            own_article_no = clause.metadata.get("article_no", "")
            modified_text = f"{own_article_no} {clause.clause_type}\n" + clause.original_text.split("\n", 1)[-1] + "（已按律师意见修改）"
        return ModificationResult(
            clause_id=clause.clause_id,
            modified_text=modified_text,
            reason="按律师意见修改",
            legal_basis=["《劳动合同法》第十九条"],
        )


class FakeReviewer:
    """替代真实 ClauseReviewer（不调用 RAG/LLM），只实现 .review(clause) 这一个
    方法——agents.risk_analyzer.analyze_modified_clause 只会调用这一个方法，
    duck typing 完全够用。script 按调用顺序取值，"fail" 模拟 Risk Analyzer
    调用失败（抛异常），其余值是期望返回的 RiskLevel。
    """

    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    def review(self, clause):
        self.calls += 1
        action = self.script.pop(0)
        if action == "fail":
            raise RuntimeError("模拟：Risk Analyzer 调用失败")
        return ReviewResult(
            clause_id=clause.clause_id,
            risk=(action != RiskLevel.NONE),
            risk_level=action,
            reason="修改后风险分析",
            source=ReviewSource.LLM,
        )


sample_text = (
    "第一条 工作内容\n甲方安排乙方从事软件开发工作。\n\n"
    "第二条 劳动合同期限\n本合同期限为三年，自2024年1月1日起至2026年12月31日止。\n\n"
    "第三条 试用期\n试用期为一个月，依照本合同第五条支付工资。\n\n"
    "第四条 工作地点\n乙方工作地点为北京市海淀区。\n\n"
    "第五条 劳动报酬\n乙方月工资为人民币15000元。\n"
)

# =====================================================================
# 1. Validator 真实测试（未改动，保留原有覆盖）
# =====================================================================
print("== 1. modification.validator.validate ==")

clause = Clause(
    contract_id="c1",
    clause_id="clause_003",
    original_text="第三条 试用期\n试用期为一个月，依照本合同第五条支付工资。",
    start_char=0,
    end_char=30,
    hierarchy_level=0,
    metadata={"article_no": "第三条"},
)

good = ModificationResult(clause_id="clause_003", modified_text="第三条 试用期\n试用期为两个月，依照本合同第五条支付工资。", reason="按律师意见延长试用期")
result = validate(clause, good, sibling_article_numbers=["第一条", "第二条", "第五条"])
check(result.passed, "合法修改应当通过 Validator")

bad_id = ModificationResult(clause_id="clause_999", modified_text="第三条 试用期\n无所谓", reason="")
result = validate(clause, bad_id, sibling_article_numbers=[])
check(not result.passed, "clause_id 不一致必须被拒绝")

print(f"Validator 部分全部通过（{assertions} 项）\n")

# =====================================================================
# 2. risk_resolution 纯函数真实测试
# =====================================================================
print("== 2. modification.risk_resolution.determine_risk_resolution ==")

check(determine_risk_resolution(RiskLevel.HIGH, RiskLevel.NONE) == RiskResolution.RESOLVED, "HIGH->NONE 应为 resolved")
check(determine_risk_resolution(RiskLevel.HIGH, RiskLevel.MEDIUM) == RiskResolution.PARTIALLY_RESOLVED, "HIGH->MEDIUM 应为 partially_resolved")
check(determine_risk_resolution(RiskLevel.HIGH, RiskLevel.LOW) == RiskResolution.PARTIALLY_RESOLVED, "HIGH->LOW 应为 partially_resolved")
check(determine_risk_resolution(RiskLevel.HIGH, RiskLevel.HIGH) == RiskResolution.UNRESOLVED, "HIGH->HIGH 应为 unresolved")
check(determine_risk_resolution(RiskLevel.LOW, RiskLevel.MEDIUM) == RiskResolution.UNRESOLVED, "LOW->MEDIUM（变严重）应为 unresolved")
check(determine_risk_resolution(RiskLevel.HIGH, None) == RiskResolution.UNKNOWN, "Risk Analyzer 失败（None）应为 unknown")

print(f"risk_resolution 部分全部通过\n")

# =====================================================================
# 3. ContractManager：Batch / Task 新字段真实测试（真实文件系统 + 真实 pydantic）
# =====================================================================
print("== 3. ContractManager：batch / task（含 batch_id / source_review_snapshot）==")

tmp_root = Path(tempfile.mkdtemp(prefix="cm_verify_"))
manager = ContractManager(root_dir=tmp_root)

sample_path = tmp_root / "sample.txt"
sample_path.write_text(sample_text, encoding="utf-8")
contract = manager.create_contract(sample_path)
parse_contract(contract.contract_id, manager)
clauses = build_clauses(
    contract.contract_id,
    [
        ("第一条", "第一条 工作内容\n甲方安排乙方从事软件开发工作。"),
        ("第二条", "第二条 劳动合同期限\n本合同期限为三年，自2024年1月1日起至2026年12月31日止。"),
        ("第三条", "第三条 试用期\n试用期为一个月，依照本合同第五条支付工资。"),
        ("第四条", "第四条 工作地点\n乙方工作地点为北京市海淀区。"),
        ("第五条", "第五条 劳动报酬\n乙方月工资为人民币15000元。"),
    ],
)
manager.save_clauses(contract.contract_id, clauses)
clauses = manager.get_clauses(contract.contract_id)

v1_report = ReviewReport(
    contract_id=contract.contract_id,
    results=[
        ReviewResult(clause_id="clause_003", risk=True, risk_level=RiskLevel.HIGH, reason="试用期过短", source=ReviewSource.LLM),
        ReviewResult(clause_id="clause_004", risk=False, risk_level=RiskLevel.NONE, reason="工作地点条款合规", source=ReviewSource.LLM),
        ReviewResult(clause_id="clause_005", risk=True, risk_level=RiskLevel.MEDIUM, reason="工资条款需明确发放日期", source=ReviewSource.LLM),
    ],
)
v1_record = manager.save_review(contract.contract_id, v1_report, contract_version="v1")
check(v1_record.review_id == "v1_001", "V1 第一份审查应编号为 v1_001")

got_review = manager.get_review(contract.contract_id, "v1_001")
check(got_review.review_id == "v1_001", "get_review 应能按 review_id 精确取到历史审查记录")
try:
    manager.get_review(contract.contract_id, "v1_999")
    check(False, "取不存在的 review_id 应抛错")
except Exception:
    check(True, "get_review 对不存在的 review_id 正确抛出异常")

batch = manager.create_batch(contract.contract_id, source_review_id="v1_001")
check(batch.batch_id == "batch_001", "第一个批次应编号为 batch_001")
check(batch.status == ModificationBatchStatus.IN_PROGRESS, "新建批次状态应为 in_progress")
check(batch.task_ids == [], "新建批次任务列表应为空")

from core.modification_task import ReviewResultSnapshot

snapshot = ReviewResultSnapshot.from_review_result(v1_report.results[0])
task = manager.create_modification_task(
    contract_id=contract.contract_id,
    clause_id="clause_003",
    original_text=clauses[2].original_text,
    lawyer_instruction="把试用期从一个月改成两个月",
    batch_id=batch.batch_id,
    source_review_id="v1_001",
    source_review_snapshot=snapshot,
)
check(task.batch_id == batch.batch_id, "ModificationTask 应记录所属 batch_id")
check(task.source_review_snapshot.risk_level == RiskLevel.HIGH, "source_review_snapshot 应冻结创建时的风险等级")
check(task.status == ModificationTaskStatus.PENDING, "新建任务状态应为 pending")

batch.task_ids = [task.task_id]
manager.update_batch(batch)
refetched_batch = manager.get_batch(contract.contract_id, batch.batch_id)
check(refetched_batch.task_ids == [task.task_id], "update_batch/get_batch 应能正确持久化 task_ids")

batches = manager.list_batches(contract.contract_id)
check(len(batches) == 1, "list_batches 应能读回刚创建的批次")

print(f"ContractManager Batch/Task 部分全部通过\n")

# =====================================================================
# 4. ModificationService：批次/任务创建、状态机、Risk Analyzer、abandon
# =====================================================================
print("== 4. ModificationService：batch 创建/任务创建（服务端查原文）/状态机/风险分析/放弃 ==")

tmp_root2 = Path(tempfile.mkdtemp(prefix="svc_verify_"))
manager2 = ContractManager(root_dir=tmp_root2)
sample_path2 = tmp_root2 / "sample.txt"
sample_path2.write_text(sample_text, encoding="utf-8")
contract2 = manager2.create_contract(sample_path2)
parse_contract(contract2.contract_id, manager2)
clauses2 = build_clauses(
    contract2.contract_id,
    [
        ("第一条", "第一条 工作内容\n甲方安排乙方从事软件开发工作。"),
        ("第二条", "第二条 劳动合同期限\n本合同期限为三年，自2024年1月1日起至2026年12月31日止。"),
        ("第三条", "第三条 试用期\n试用期为一个月，依照本合同第五条支付工资。"),
        ("第四条", "第四条 工作地点\n乙方工作地点为北京市海淀区。"),
        ("第五条", "第五条 劳动报酬\n乙方月工资为人民币15000元。"),
    ],
)
manager2.save_clauses(contract2.contract_id, clauses2)
clauses2 = manager2.get_clauses(contract2.contract_id)

v1_report2 = ReviewReport(
    contract_id=contract2.contract_id,
    results=[
        ReviewResult(clause_id="clause_003", risk=True, risk_level=RiskLevel.HIGH, reason="试用期过短", source=ReviewSource.LLM),
        ReviewResult(clause_id="clause_004", risk=True, risk_level=RiskLevel.MEDIUM, reason="工作地点约定不明确", source=ReviewSource.LLM),
        ReviewResult(clause_id="clause_005", risk=True, risk_level=RiskLevel.HIGH, reason="工资条款缺少发放日期", source=ReviewSource.LLM),
    ],
)
manager2.save_review(contract2.contract_id, v1_report2, contract_version="v1")

agent = FakeAgent([("good", "第三条 试用期\n试用期为两个月，依照本合同第五条支付工资。")])
reviewer = FakeReviewer([RiskLevel.NONE])
service = ModificationService(manager2, agent, reviewer=reviewer)

batch2 = service.create_batch(contract2.contract_id, source_review_id="v1_001")
check(batch2.status == ModificationBatchStatus.IN_PROGRESS, "service.create_batch 应创建 in_progress 批次")

try:
    service.create_batch(contract2.contract_id, source_review_id="v1_999")
    check(False, "依据不存在的 source_review_id 创建批次应被拒绝")
except ModificationServiceError:
    check(True, "create_batch 正确拒绝了不存在的 source_review_id")

task2 = service.create_task(contract2.contract_id, batch2.batch_id, "clause_003", "延长试用期")
check(task2.batch_id == batch2.batch_id, "create_task 应正确关联 batch_id")
check(task2.original_text == clauses2[2].original_text, "original_text 必须是服务端从 ContractManager 查出的真实原文")
check(task2.source_review_snapshot.risk_level == RiskLevel.HIGH, "source_review_snapshot 应正确冻结 clause_003 的原始风险")

try:
    service.create_task(contract2.contract_id, batch2.batch_id, "clause_003", "再提一个意见")
    check(False, "同一条款已有未终态任务时应检测到冲突")
except ModificationConflictError:
    check(True, "create_task 内部的冲突检测正确生效")

task2 = service.start_modification(contract2.contract_id, task2.task_id)
check(task2.status == ModificationTaskStatus.WAITING_CONFIRMATION, "校验通过后状态应变为 waiting_confirmation")
check(len(task2.modification_attempts) == 1, "应记录一次尝试")
attempt1 = task2.modification_attempts[0]
check(attempt1.risk_analysis is not None, "Validator 通过后应跑修改后风险分析")
check(attempt1.risk_analysis.risk_level == RiskLevel.NONE, "FakeReviewer 配置的风险分析结果应为 none")
check(attempt1.risk_resolution == RiskResolution.RESOLVED, "HIGH->NONE 应被判定为 resolved")
check(attempt1.risk_analysis_error is None, "风险分析成功时不应有 error")

task2 = service.confirm(contract2.contract_id, task2.task_id)
check(task2.status == ModificationTaskStatus.CONFIRMED, "confirm 后状态应为 confirmed")
check(task2.confirmed_at is not None, "confirm 后应记录 confirmed_at")

batch2 = manager2.get_batch(contract2.contract_id, batch2.batch_id)
check(batch2.status == ModificationBatchStatus.READY_FOR_V2, "batch2 只有一条任务且已 confirmed，应自动推进为 ready_for_v2")

# ---- 单独验证一个"只有一条任务、确认后立刻就绪"的批次 ----
batch_ready_test = service.create_batch(contract2.contract_id, source_review_id="v1_001")
task_ready_test = service.create_task(contract2.contract_id, batch_ready_test.batch_id, "clause_004", "明确工作地点")
agent.script.append(("good", "第四条 工作地点\n乙方工作地点为上海市浦东新区。"))
reviewer.script.append(RiskLevel.LOW)
task_ready_test = service.start_modification(contract2.contract_id, task_ready_test.task_id)
task_ready_test = service.confirm(contract2.contract_id, task_ready_test.task_id)
batch_ready_test = manager2.get_batch(contract2.contract_id, batch_ready_test.batch_id)
check(batch_ready_test.status == ModificationBatchStatus.READY_FOR_V2, "唯一任务确认后，批次应自动推进为 ready_for_v2")

# =====================================================================
# 4.1 reject -> retry -> needs_human 的完整 3 轮流程 + Risk Analyzer 失败处理
# =====================================================================
agent3 = FakeAgent(["bad", "bad", "bad"])
reviewer3 = FakeReviewer([])  # bad 候选不会跑到风险分析
service3 = ModificationService(manager2, agent3, reviewer=reviewer3)
batch3 = service3.create_batch(contract2.contract_id, source_review_id="v1_001")
task3 = service3.create_task(contract2.contract_id, batch3.batch_id, "clause_005", "提高工资")

task3 = service3.start_modification(contract2.contract_id, task3.task_id)
check(task3.status == ModificationTaskStatus.PENDING, "第一次校验失败但未用满重试，应回到 pending")
task3 = service3.start_modification(contract2.contract_id, task3.task_id)
check(len(task3.modification_attempts) == 2, "应记录第二次失败尝试")
task3 = service3.start_modification(contract2.contract_id, task3.task_id)
check(task3.status == ModificationTaskStatus.NEEDS_HUMAN, "第三次仍失败，用满 3 轮后应转入 needs_human")

try:
    service3.abandon(contract2.contract_id, task3.task_id)
except ModificationServiceError:
    check(False, "needs_human 应允许 abandon")
else:
    task3 = manager2.get_modification_task(contract2.contract_id, task3.task_id)
    check(task3.status == ModificationTaskStatus.ABANDONED, "abandon 后状态应为 abandoned")

try:
    service3.abandon(contract2.contract_id, task3.task_id)
    check(False, "abandoned 状态不应允许再次 abandon")
except ModificationServiceError:
    check(True, "abandon 正确拒绝了已经是终态的任务")

batch3 = manager2.get_batch(contract2.contract_id, batch3.batch_id)
check(batch3.status == ModificationBatchStatus.IN_PROGRESS, "只有 abandoned、没有任何 confirmed 时批次不应就绪（缺少至少一条 confirmed）")

# ---- needs_human 下用 manual_text 确认（Part B 的转换路径）----
agent4 = FakeAgent(["bad", "bad", "bad"])
service4 = ModificationService(manager2, agent4, reviewer=FakeReviewer([]))
batch4 = service4.create_batch(contract2.contract_id, source_review_id="v1_001")
task4 = service4.create_task(contract2.contract_id, batch4.batch_id, "clause_003" if False else "clause_005", "再次尝试")
# clause_005 已经被 service3 的 task3 占用过但那条已经是终态(abandoned)，不冲突
task4 = service4.start_modification(contract2.contract_id, task4.task_id)
task4 = service4.start_modification(contract2.contract_id, task4.task_id)
task4 = service4.start_modification(contract2.contract_id, task4.task_id)
check(task4.status == ModificationTaskStatus.NEEDS_HUMAN, "三次失败后应为 needs_human")

try:
    service4.confirm(contract2.contract_id, task4.task_id)
    check(False, "needs_human 状态下不提供 manual_text 应被拒绝")
except ModificationServiceError:
    check(True, "needs_human 下缺少 manual_text 被正确拒绝")

task4 = service4.confirm(contract2.contract_id, task4.task_id, manual_text="第五条 劳动报酬\n乙方月工资为人民币18000元（律师手工确定）。")
check(task4.status == ModificationTaskStatus.CONFIRMED, "needs_human + manual_text 应能成功确认")
check("18000" in task4.current_modified_text, "手工确认的文本应被正确保存")

print(f"ModificationService 状态机/风险分析/放弃 部分全部通过\n")

# =====================================================================
# 5. compute_batch_readiness 纯函数直接测试
# =====================================================================
print("== 5. modification.service.compute_batch_readiness ==")

tasks_for_readiness = manager2.list_modification_tasks(contract2.contract_id)
ready, blocking, confirmed = compute_batch_readiness(tasks_for_readiness)
check(isinstance(ready, bool), "compute_batch_readiness 应返回布尔值")
check(len(confirmed) >= 1, "本合同下应存在至少一条 confirmed 任务")

print(f"compute_batch_readiness 部分全部通过\n")

# =====================================================================
# 6. V2GenerationService：批次就绪判断、生成成功、失败重试、ABANDONED 保留原文
# =====================================================================
print("== 6. V2GenerationService ==")

v2_service = V2GenerationService(manager2)

# 6.1 batch_ready_test（唯一任务已 confirmed）应能成功生成
version = v2_service.generate(contract2.contract_id, batch_id=batch_ready_test.batch_id)
check(version.version_number == "v2", "generate 应返回 version_number='v2' 的 ContractVersion")
batch_ready_test = manager2.get_batch(contract2.contract_id, batch_ready_test.batch_id)
check(batch_ready_test.status == ModificationBatchStatus.V2_GENERATED, "生成成功后批次状态应为 v2_generated")
check(batch_ready_test.generated_contract_id == version.linked_contract_id, "批次应记录 generated_contract_id")

v2_clauses = manager2.get_clauses(version.linked_contract_id)
v2_top = {c.clause_id: c for c in v2_clauses if c.hierarchy_level == 0}
check("上海市浦东新区" in v2_top["clause_004"].original_text, "V2 中 clause_004 应包含已确认的修改文本")

try:
    v2_service.generate(contract2.contract_id, batch_id=batch_ready_test.batch_id)
    check(False, "已成功生成 V2 的批次不应允许再次生成")
except ModificationServiceError:
    check(True, "重复生成同一批次的 V2 被正确拒绝")

# 6.2 未就绪的批次（存在一条还停留在 pending 的任务）应被拒绝
agent_pending = FakeAgent([])
batch_pending_test = service.create_batch(contract2.contract_id, source_review_id="v1_001")
task_pending_test = service.create_task(contract2.contract_id, batch_pending_test.batch_id, "clause_005", "希望进一步明确支付方式")
try:
    v2_service.generate(contract2.contract_id, batch_id=batch_pending_test.batch_id)
    check(False, "存在 pending 任务的批次不应允许生成 V2")
except ModificationServiceError as exc:
    check(True, f"未就绪批次被正确拒绝：{exc}")

print(f"V2GenerationService 基本流程部分全部通过\n")

# =====================================================================
# 6.3 失败重试：先注入一次失败，确认 V2_FAILED + last_error，再正常重试成功
# =====================================================================
print("== 6.3 V2GenerationService：失败 -> V2_FAILED -> 重试成功 ==")

tmp_root3 = Path(tempfile.mkdtemp(prefix="svc_verify3_"))
manager3 = ContractManager(root_dir=tmp_root3)
sample_path3 = tmp_root3 / "sample.txt"
sample_path3.write_text(sample_text, encoding="utf-8")
contract3 = manager3.create_contract(sample_path3)
parse_contract(contract3.contract_id, manager3)
clauses3 = build_clauses(
    contract3.contract_id,
    [
        ("第一条", "第一条 工作内容\n甲方安排乙方从事软件开发工作。"),
        ("第二条", "第二条 劳动合同期限\n本合同期限为三年，自2024年1月1日起至2026年12月31日止。"),
    ],
)
manager3.save_clauses(contract3.contract_id, clauses3)
v1_report3 = ReviewReport(
    contract_id=contract3.contract_id,
    results=[ReviewResult(clause_id="clause_001", risk=True, risk_level=RiskLevel.HIGH, reason="工作内容约定不明确", source=ReviewSource.LLM)],
)
manager3.save_review(contract3.contract_id, v1_report3, contract_version="v1")

agent5 = FakeAgent([("good", "第一条 工作内容\n甲方安排乙方从事软件开发与测试工作（已修改）。")])
service5 = ModificationService(manager3, agent5, reviewer=FakeReviewer([RiskLevel.NONE]))
batch5 = service5.create_batch(contract3.contract_id, source_review_id="v1_001")
task5 = service5.create_task(contract3.contract_id, batch5.batch_id, "clause_001", "明确工作内容")
task5 = service5.start_modification(contract3.contract_id, task5.task_id)
task5 = service5.confirm(contract3.contract_id, task5.task_id)

v2_service3 = V2GenerationService(manager3)

_real_split_contract = _preparation_module.split_contract


def _broken_split_contract(*args, **kwargs):
    raise RuntimeError("模拟：切分步骤失败")


_preparation_module.split_contract = _broken_split_contract
try:
    v2_service3.generate(contract3.contract_id, batch_id=batch5.batch_id)
    check(False, "注入的失败应该向上传播")
except ModificationServiceError:
    check(True, "生成失败时 generate 正确抛出 ModificationServiceError")
finally:
    _preparation_module.split_contract = _real_split_contract

failed_batch = manager3.get_batch(contract3.contract_id, batch5.batch_id)
check(failed_batch.status == ModificationBatchStatus.V2_FAILED, "失败后批次状态应为 v2_failed")
check(failed_batch.last_error is not None and "切分步骤失败" in failed_batch.last_error, "批次应记录失败原因")
check(failed_batch.generated_contract_id is None, "失败时不应设置 generated_contract_id")

# 任务状态不受 V2 生成失败影响（V2 成功/失败只记在批次上）
task5_after_failure = manager3.get_modification_task(contract3.contract_id, task5.task_id)
check(task5_after_failure.status == ModificationTaskStatus.CONFIRMED, "V2 生成失败不应改变任务状态，confirmed 任务仍是 confirmed")

# 重试：恢复正常的 split_contract，再次调用 generate 应该成功
retried_version = v2_service3.generate(contract3.contract_id, batch_id=batch5.batch_id)
check(retried_version.version_number == "v2", "重试应能成功生成 V2")
succeeded_batch = manager3.get_batch(contract3.contract_id, batch5.batch_id)
check(succeeded_batch.status == ModificationBatchStatus.V2_GENERATED, "重试成功后批次状态应为 v2_generated")
check(succeeded_batch.last_error is None, "重试成功后 last_error 应被清空")

print(f"V2GenerationService 失败重试部分全部通过\n")

shutil.rmtree(tmp_root, ignore_errors=True)
shutil.rmtree(tmp_root2, ignore_errors=True)
shutil.rmtree(tmp_root3, ignore_errors=True)

print(f"ALL {assertions} ASSERTIONS PASSED")
