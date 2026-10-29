"""ModificationValidator：对 Modification Agent 生成的候选结果做程序化校验。

独立于 Agent 之外的原因：LLM 能生成看起来合理的修改文本，不代表这段文本
可以直接进入 Human-in-the-loop 给律师看——越界修改、截断、占位符、条款
编号被破坏，都是真实会出现的问题（不是假设）。这些问题用固定规则就能
可靠检测，不需要、也不应该再调用一次 LLM 来"自己判断自己改得对不对"
（Validator 不调用 LLM，是本模块的硬约束）。

范围校验的实现方式（重要）：
    不通过"对比修改前后的合同全文有什么变化"来判断范围，那需要一次完整的
    文档级 diff，而且天然依赖"其他条款有没有被改动"这种全局信息。
    本模块改用更直接、只依赖目标条款自身信息的方式：
        1. clause_id 必须和目标条款一致（tool.py 已经查过一次，这里是第二道防线）；
        2. 目标条款自己的"条款编号"（clause.metadata['article_no']，例如"第三条"）
           如果存在，修改后的文本里除了这一个编号，只允许出现原条款文本里
           本来就有的、指向其他条款的交叉引用编号（见第 4 点），不允许出现
           任何"原文里没有、新冒出来"的其他条款编号；
        3. 调用方可以传入 sibling_article_numbers（合同里其他条款的编号列表，
           只是一份字符串列表，不是全文），用来加强第 2 点里"新冒出来的编号"
           的检测；
        4. 原条款文本里出现过的、指向【其他条款】的交叉引用（例如"依照本合同
           第五条"），修改后必须仍然原样保留，不能被无意义删除——这类编号
           在第 2 点里不算越界，因为它本来就属于这个条款自身的合法内容。
    这四点都只依赖目标条款自身的文本和 metadata，不需要拿到"修改前后的
    完整合同"再做一次全文比较。

三类校验：范围、完整性、结构。都是同步的纯函数逻辑。
"""

import re

from core import Clause, ModificationResult, ValidationResult

_ARTICLE_RE = re.compile(r"第[一二三四五六七八九十百千零〇两\d]+条")

_PLACEHOLDER_PATTERNS = [
    re.compile(r"TODO", re.IGNORECASE),
    re.compile(r"TBD", re.IGNORECASE),
    re.compile(r"待补充"),
    re.compile(r"待定"),
    re.compile(r"省略(?:若干|部分|此处)?"),
    re.compile(r"\.\.\.|……"),
    re.compile(r"\[.*?\]"),
    re.compile(r"【(?:待补充|待定|此处省略|填写|填空).*?】"),
]


def _find_article_numbers(text: str) -> set[str]:
    return set(_ARTICLE_RE.findall(text))


def validate(
    clause: Clause,
    candidate: ModificationResult,
    sibling_article_numbers: list[str] | None = None,
) -> ValidationResult:
    """校验一次 Modification Agent 的候选结果。返回 ValidationResult。"""
    errors: list[str] = []
    sibling_article_numbers = sibling_article_numbers or []
    text = candidate.modified_text

    # ---------------- 1. 范围校验 ----------------
    if candidate.clause_id != clause.clause_id:
        errors.append(f"候选结果的 clause_id（{candidate.clause_id}）与目标条款（{clause.clause_id}）不一致")

    own_article_no = clause.metadata.get("article_no") if isinstance(clause.metadata, dict) else None
    found_numbers = _find_article_numbers(text)

    if own_article_no:
        other_numbers_in_text = found_numbers - {own_article_no}
    else:
        other_numbers_in_text = found_numbers

    # 原文里本来就存在、指向其他条款的交叉引用——修改后继续出现是"保留"，
    # 不是"越界"，必须先算出来，从下面的越界判断里排除，否则一个合法的
    # 交叉引用会同时被当成"必须保留"和"不允许出现"，自相矛盾。
    if own_article_no:
        original_cross_refs = _find_article_numbers(clause.original_text) - {own_article_no}
    else:
        original_cross_refs = _find_article_numbers(clause.original_text)

    # 明确出现了"本条编号之外、且原文中不存在的"条款编号——很可能是越界引用/
    # 混入了其他条款的内容，而不是对原有交叉引用的合理保留。
    newly_introduced = other_numbers_in_text - original_cross_refs
    conflicting = newly_introduced & set(sibling_article_numbers) if sibling_article_numbers else newly_introduced
    if conflicting:
        errors.append(f"修改后的文本中出现了其他条款的编号，疑似越界修改：{sorted(conflicting)}")

    # 原文里对其他条款的交叉引用，修改后必须原样保留，不能被无意义删除
    missing_cross_refs = [ref for ref in original_cross_refs if ref not in text]
    if missing_cross_refs:
        errors.append(f"原条款中的交叉引用在修改后丢失：{sorted(missing_cross_refs)}")

    # ---------------- 2. 完整性校验 ----------------
    if not text.strip():
        errors.append("修改后的条款文本为空")
    else:
        for pattern in _PLACEHOLDER_PATTERNS:
            if pattern.search(text):
                errors.append(f"修改后的文本中包含疑似占位符或未完成内容：{pattern.pattern!r} 命中")
                break

    # ---------------- 3. 结构校验 ----------------
    # 只有"条"本身（hierarchy_level == 0，即原文以"第X条"开头）才要求修改后
    # 仍然保留这个编号；款/项级别的子条款不强制要求（它们本来就不一定带编号）。
    if clause.hierarchy_level == 0 and own_article_no:
        if own_article_no not in found_numbers:
            errors.append(f"修改后的文本丢失了条款编号“{own_article_no}”")

    return ValidationResult(passed=len(errors) == 0, errors=errors)
