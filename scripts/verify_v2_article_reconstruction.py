"""真实执行验证：document/reconstructor.py 的 group_clauses_by_article /
reconstruct_article_text / build_v2_text（原 modification/service.py 的
_group_clauses_by_article / _reconstruct_article_text / _build_v2_text，
Stage 1 架构重构后已抽成 document.reconstructor 的纯函数）行为。

用真实的 ClauseSplitter（langchain_text_splitters 只在超长条款时才被调用，
这里样例都很短，用不会被调用到的假实现打桩，不影响真实性），构造一份
同时包含"无款条""可识别单层编号款""不可识别子编号（1.1/1.2）"的合同文本，
覆盖设计分析里列的 8 个测试点：无修改 / 改条级 / 改一个款 / 改多个款 /
一条部分改部分不改 / 有款无款混合 / 重新切分结构正确 / 不允许内容丢失。
"""
import sys, types
sys.path.insert(0, "/mnt/user-data/outputs/labor_contract_review")

def stub(name, **attrs):
    try:
        __import__(name); return
    except ModuleNotFoundError:
        pass
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod

class _Dummy:
    def __init__(self, *a, **k): pass
    def split_text(self, text):
        raise AssertionError("不应被调用——示例条款都远小于 chunk_size")

class _OpenAIError(Exception): pass
stub("openai", OpenAI=_Dummy, OpenAIError=_OpenAIError)
stub("dotenv", load_dotenv=lambda *a, **k: None)
stub("langchain_text_splitters", RecursiveCharacterTextSplitter=_Dummy)
stub("langchain_chroma", Chroma=_Dummy)
stub("langchain_core")
stub("langchain_core.documents", Document=_Dummy)
stub("langchain_core.embeddings", Embeddings=_Dummy)
stub("langchain_huggingface", HuggingFaceEmbeddings=_Dummy)
stub("langgraph")
stub("langgraph.graph", END="__end__", START="__start__", StateGraph=_Dummy)

from document.reconstructor import build_v2_text, group_clauses_by_article
from document.splitter import ClauseSplitter

assertions = 0
def check(cond, msg):
    global assertions
    assertions += 1
    if not cond:
        raise AssertionError(f"FAILED #{assertions}: {msg}")
    print(f"  ok  [{assertions}] {msg}")


# 混合结构：clause_001 不可识别子编号（整条一个节点）；clause_002 无款；
# clause_003 可识别单层编号（2 款）；clause_004 可识别单层编号（3 款）。
v1_text = (
    "第一条 合同期限\n"
    "1.1 本合同期限为三年，自2024年1月1日起至2026年12月31日止。\n"
    "1.2 试用期为三个月，自2024年1月1日起至2024年3月31日止。\n"
    "第二条 工作内容\n"
    "甲方安排乙方从事软件开发工作，具体岗位为后端工程师。\n"
    "第三条 劳动报酬\n"
    "1. 乙方月工资为人民币20000元，税前发放。\n"
    "2. 甲方应于每月10日前足额支付上月工资。\n"
    "第四条 工作时间\n"
    "1. 标准工时制度，每周工作五天。\n"
    "2. 甲方应保证乙方每周至少休息一日。\n"
    "3. 因工作需要延长工作时间的，应按国家规定支付加班费。\n"
)

splitter = ClauseSplitter()


def split_and_group(text, cid):
    clauses = splitter.split(text, cid)
    return clauses, group_clauses_by_article(clauses)


v1_clauses, v1_groups = split_and_group(v1_text, "v1")
print("=== V1 切分结果 ===")
for c in sorted(v1_clauses, key=lambda c: c.start_char):
    print(f"  {c.clause_id:16s} level={c.hierarchy_level} parent={c.parent_clause!r}  {c.original_text!r}")

v1_by_id = {c.clause_id: c for c in v1_clauses}

print("\n== 测试 1：无修改条款 ==")
v2_text = build_v2_text(v1_text, v1_groups, {})
v2_clauses = splitter.split(v2_text, "v2_none")
v2_by_id = {c.clause_id: c for c in v2_clauses}
check(set(v1_by_id) == set(v2_by_id), f"clause_id 集合应完全一致：V1={sorted(v1_by_id)} V2={sorted(v2_by_id)}")
for cid, c in v1_by_id.items():
    check(v2_by_id[cid].original_text == c.original_text, f"{cid} 未修改时应逐字节不变")
    check(v2_by_id[cid].hierarchy_level == c.hierarchy_level, f"{cid} 层级应不变")
    check(v2_by_id[cid].parent_clause == c.parent_clause, f"{cid} 父子关系应不变")

print("\n== 测试 2：修改 level=0 条（clause_002，无款）==")
confirmed = {"clause_002": "第二条 工作内容\n甲方安排乙方从事测试开发工作，具体岗位为测试工程师。"}
v2_text = build_v2_text(v1_text, v1_groups, confirmed)
v2_clauses = splitter.split(v2_text, "v2_t2")
v2_by_id = {c.clause_id: c for c in v2_clauses}
check(v2_by_id["clause_002"].original_text == confirmed["clause_002"], "clause_002 应替换成确认文本")
for cid in ("clause_001", "clause_003", "clause_003_1", "clause_003_2", "clause_004", "clause_004_1", "clause_004_2", "clause_004_3"):
    check(v2_by_id[cid].original_text == v1_by_id[cid].original_text, f"{cid} 不应受 clause_002 的修改影响")

print("\n== 测试 3：修改一个 level=1 款（clause_003_2）==")
confirmed = {"clause_003_2": "2. 甲方应于每月5日前足额支付上月工资。"}
v2_text = build_v2_text(v1_text, v1_groups, confirmed)
v2_clauses = splitter.split(v2_text, "v2_t3")
v2_by_id = {c.clause_id: c for c in v2_clauses}
check(v2_by_id["clause_003_2"].original_text == confirmed["clause_003_2"], "clause_003_2 应替换成确认文本")
check(v2_by_id["clause_003"].original_text == v1_by_id["clause_003"].original_text, "同条标题 clause_003 应不变")
check(v2_by_id["clause_003_1"].original_text == v1_by_id["clause_003_1"].original_text, "同条兄弟款 clause_003_1 应不变（这正是本次修复要保证的点）")

print("\n== 测试 4：修改同一条中的多个款（clause_004_1 和 clause_004_3）==")
confirmed = {
    "clause_004_1": "1. 标准工时制度，每周工作四十小时。",
    "clause_004_3": "3. 因工作需要延长工作时间的，应按国家规定支付不低于150%的加班费。",
}
v2_text = build_v2_text(v1_text, v1_groups, confirmed)
v2_clauses = splitter.split(v2_text, "v2_t4")
v2_by_id = {c.clause_id: c for c in v2_clauses}
check(v2_by_id["clause_004_1"].original_text == confirmed["clause_004_1"], "clause_004_1 应替换")
check(v2_by_id["clause_004_3"].original_text == confirmed["clause_004_3"], "clause_004_3 应替换")

print("\n== 测试 5：一条部分修改、部分不修改（复用测试4的场景，重点断言未改的 clause_004_2）==")
check(v2_by_id["clause_004_2"].original_text == v1_by_id["clause_004_2"].original_text, "clause_004_2（未改）必须逐字节等于 V1")
check(v2_by_id["clause_004"].original_text == v1_by_id["clause_004"].original_text, "clause_004 标题（未改）必须逐字节等于 V1")

print("\n== 测试 6：有款/无款条款混合于同一份文档（clause_001 无款单节点 + clause_002 无款 + clause_003/004 有款）==")
check("clause_001" in v2_by_id and v2_by_id["clause_001"].hierarchy_level == 0, "clause_001（1.1/1.2 子编号，不可识别，整条一个节点）结构应保持")
check(v2_by_id["clause_001"].original_text == v1_by_id["clause_001"].original_text, "clause_001 未改，应逐字节不变（包含内部 1.1/1.2 全部正文）")

print("\n== 测试 7：V1 -> V2 -> 重新切分后，父子结构必须正确重建（这是本次修复要解决的核心回归点）==")
v2_text = build_v2_text(v1_text, v1_groups, {})
v2_clauses = splitter.split(v2_text, "v2_t7")
v2_by_id = {c.clause_id: c for c in v2_clauses}
for cid in ("clause_003_1", "clause_003_2", "clause_004_1", "clause_004_2", "clause_004_3"):
    check(cid in v2_by_id, f"{cid} 修复前会完全消失，修复后必须重新出现")
    check(v2_by_id[cid].hierarchy_level == 1, f"{cid} 层级必须是 1（款）")
check(v2_by_id["clause_003_1"].parent_clause == "clause_003", "clause_003_1 的 parent_clause 必须正确指向 clause_003")
check(v2_by_id["clause_004_2"].parent_clause == "clause_004", "clause_004_2 的 parent_clause 必须正确指向 clause_004")

print("\n== 测试 8：不允许出现任何原文内容丢失（全局不变量：未确认修改的 clause 内容必须作为子串存在于 V2 全文）==")
confirmed = {"clause_004_1": "1. 标准工时制度（已修改）。"}
v2_text = build_v2_text(v1_text, v1_groups, confirmed)
for cid, c in v1_by_id.items():
    if cid in confirmed:
        continue
    check(c.original_text in v2_text, f"{cid} 的原文内容必须作为子串完整出现在 V2 全文里（未被丢弃）")
check(confirmed["clause_004_1"] in v2_text, "被修改的 clause_004_1 应该是确认后的文本，而不是原文")
check(v1_by_id["clause_004_1"].original_text not in v2_text, "clause_004_1 的旧原文不应该残留在 V2 里（确认替换应该是真替换，不是追加）")

print(f"\nALL {assertions} ASSERTIONS PASSED（真实执行 ClauseSplitter + document.reconstructor.build_v2_text，非手写假数据模拟结构）")
