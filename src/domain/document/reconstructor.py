"""V2 全文重建：纯函数，输入 V1 原文 + 已确认的修改结果，输出 V2 全文。

不触碰 ContractManager，不创建 ModificationTask，不调用 ModificationService，
不跑 V2 Review 或 Diff——这些编排/业务动作全部留在 modification/service.py，
本模块只负责“怎么把 Clause 列表 + 已确认的修改文本拼回一份完整合同原文”
这一个纯文本算法。

算法说明（与原 modification/service.py 中的实现保持一致；2026-09-29 修复过
一次款级内容丢失的 bug，见 docs/PITFALLS.md，下面这段描述的是修复后的行为）：
    以“条”为单位重建原文，而不是简单拼接 Clause 文本：ClauseSplitter 会把
    带款项编号的条拆成 1 个 hierarchy_level=0（条，只含标题/引导文字）+
    N 个 hierarchy_level=1（款，parent_clause 指回这个条）；一条的完整原文
    = 这些节点按 start_char 排序后，节点自身区间 + 节点之间的原文“缝隙”
    （标题与第一款之间、各款之间的空白/换行）依次拼接。重建时对每个节点，
    如果它的 clause_id 命中一个已确认的修改任务，就用
    task.current_modified_text 替换这个节点自己的区间；没有命中就直接从
    V1 的原始全文里按 start_char/end_char 取原样字符——节点之间的“缝隙”
    永远原样保留，不受任何修改影响。这样保证：没有被修改的条/款，
    在 V2 里逐字节等于 V1；被修改的条/款，只有它自己的区间被替换，
    同一条内其它款、以及条与条之间的原文格式都不受影响。
"""

from typing import Any

from core import Clause


def group_clauses_by_article(clauses: list[Clause]) -> list[list[Clause]]:
    """按“条”（含它所有的款级子节点）给 Clause 分组，用于逐条重建原文。

    分组依据：hierarchy_level == 0 的 Clause 是一组的锚点（代表“条”
    本身，可能只是标题/引导文字，也可能是完整正文——取决于这一条有没有
        被 ClauseSplitter 识别出款项编号）；hierarchy_level > 0 的 Clause
    通过它自己的 parent_clause 字段指向所属的锚点 clause_id。这里只是
    复用 ClauseSplitter 已经算好的父子关系，不重新用正则去猜“哪些款
    属于哪条”。

    已知边界情况（不在本次修复范围内，属于 ClauseSplitter 自身早就存在
    的行为）：如果一条的“标题 + 引导文字”部分本身超过 chunk_size 被
    RecursiveCharacterTextSplitter 二次切分成多个 hierarchy_level == 0
    片段（clause_00N_p1 / _p2 ...），这些片段各自的 clause_id 不再等于
    其款级子节点声明的 parent_clause（子节点仍然指向未拆分前的
    clause_00N），会找不到锚点、退化成“孤儿”节点——下面按它自己的
    start_char 单独成组处理，不会丢数据，只是不会和它本来所属的标题
    片段合并成一组。触发条件是“条的标题/引导文字本身超过 500 字”，
    真实合同里基本不会出现。
    """
    anchors: dict[str, list[Clause]] = {}
    for clause in clauses:
        if clause.hierarchy_level == 0:
            anchors.setdefault(clause.clause_id, []).append(clause)

    groups: list[list[Clause]] = list(anchors.values())
    for clause in clauses:
        if clause.hierarchy_level == 0:
            continue
        bucket = anchors.get(clause.parent_clause)
        if bucket is not None:
            bucket.append(clause)
        else:
            groups.append([clause])  # 孤儿节点：见上面的已知边界情况

    groups.sort(key=lambda nodes: min(node.start_char for node in nodes))
    return groups


def reconstruct_article_text(
    full_text: str,
    nodes: list[Clause],
    modified_text_by_clause_id: dict[str, Any],
) -> str:
    """重建“一条”（一组 Clause：条本身 + 它所有的款）的完整原文。

    规则：节点按 start_char 排序后逐个输出；节点自己的区间，如果
    modified_text_by_clause_id 里命中一个非空文本就用它替换这个节点自己的
    区间，否则原样从 full_text 里取对应字符（而不是 clause.original_text——
    两者内容目前相同，但语义上应该明确“取自原文这唯一的事实来源”）。节点
    与节点之间的“缝隙”（比如标题和第一款之间、各款之间的空白/换行）永远
    原样从 full_text 复制，不受任何修改任务影响——这是保证“没被改的部分
    逐字节不变”的关键：只替换被改动节点自己的区间，不重新发明分隔符、
    不用拼接后的字符串去猜测原来的格式。

    modified_text_by_clause_id 是 {clause_id: 修改后文本} 的映射，调用方
    （modification/service.py）负责从 ModificationTask 里取出
    current_modified_text 并组装成这个映射——本函数不知道、也不需要知道
    ModificationTask 这个类型的存在。
    """
    ordered = sorted(nodes, key=lambda c: c.start_char)
    pieces: list[str] = []
    cursor = ordered[0].start_char
    for node in ordered:
        if node.start_char > cursor:
            pieces.append(full_text[cursor:node.start_char])  # 节点之间的原文缝隙，原样保留
        modified_text = modified_text_by_clause_id.get(node.clause_id)
        if modified_text:
            pieces.append(modified_text)
        else:
            pieces.append(full_text[node.start_char:node.end_char])
        cursor = node.end_char
    return "".join(pieces)


def build_v2_text(
    full_text: str,
    article_groups: list[list[Clause]],
    modified_text_by_clause_id: dict[str, Any],
) -> str:
    """逐条重建全文，条与条之间用固定分隔符拼接。

    条内部（标题与各款之间、各款相互之间）的原文格式由
    reconstruct_article_text 逐字节保真还原；条与条之间目前仍然用固定的
    "\\n\\n" 分隔（不是从原文里取“条与条之间的缝隙”），这是一个已知的、
    范围有限的简化——不会丢内容，只可能让“条与条之间”多一个和 V1 不完全
    一致的空行数量，不影响“条内内容不丢失”这个问题。
    """
    return "\n\n".join(
        reconstruct_article_text(full_text, nodes, modified_text_by_clause_id)
        for nodes in article_groups
    )
