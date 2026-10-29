"""条款级 V1/V2 Diff：纯函数，输入 V1/V2 的条款字典，输出逐条的 Diff 结果。

不调用 ContractManager、不 import modification.service——所有需要的数据
（V1/V2 的 Clause）由调用方（modification/service.py）先用 ContractManager
取好，再传进来。
"""

from core import Clause, ClauseDiffEntry


def clause_diff(v1_clauses: dict[str, Clause], v2_clauses: dict[str, Clause]) -> list[ClauseDiffEntry]:
    """逐条对比 V1/V2 的条款（按 clause_id 匹配），返回标记了 未修改/已修改 的列表。

    clause_id 在其中一个版本里缺失时，不猜测对应关系，明确标记 matched=False，
    把“到底对应哪条”留给人看，而不是编一个答案。
    """
    entries: list[ClauseDiffEntry] = []
    seen_ids = set(v1_clauses) | set(v2_clauses)
    for clause_id in sorted(seen_ids):
        v1_clause = v1_clauses.get(clause_id)
        v2_clause = v2_clauses.get(clause_id)
        if v1_clause is None or v2_clause is None:
            base = v1_clause or v2_clause
            entries.append(
                ClauseDiffEntry(
                    clause_id=clause_id,
                    matched=False,
                    changed=True,
                    original_text=base.original_text,
                    modified_text=None,
                )
            )
            continue
        changed = v1_clause.original_text != v2_clause.original_text
        entries.append(
            ClauseDiffEntry(
                clause_id=clause_id,
                matched=True,
                changed=changed,
                original_text=v1_clause.original_text,
                modified_text=v2_clause.original_text if changed else None,
            )
        )
    return entries
