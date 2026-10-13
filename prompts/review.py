"""审查 Prompt 模板：只负责把条款和检索到的 Evidence 拼成 messages，
不调用 LLM（那是 llm/client.py 的事），也不做检索（那是 rag 包的事）。
"""

from schemas import Evidence

# Prompt 版本号：每次有意修改 SYSTEM_PROMPT 或 build_review_messages 的拼装方式
# （不是修一个笔误级别的小问题）时手动加一位，供 ReviewReport.versions.prompt_version
# 记录"这份报告是用哪一版 Prompt 跑出来的"，评估基准对比前后版本时据此区分。
PROMPT_VERSION = "review-prompt-v1"

SYSTEM_PROMPT = (
    "你是一名劳动合同审查助手。你只能依据下面提供的法律依据判断条款是否存在风险，"
    "禁止编造或使用未提供的法律条文；如果提供的法律依据不足以支撑判断，"
    "就如实说明依据不足，不要猜测。\n"
    "必须只输出一个 JSON 对象，不要输出任何 JSON 之外的文字、代码块标记或解释。\n"
    "JSON 必须包含以下字段：\n"
    '- risk (boolean)：该条款是否存在法律风险；\n'
    '- risk_level (string)：风险等级，取值只能是 "none" / "low" / "medium" / "high"；'
    'risk 为 false 时必须是 "none"，risk 为 true 时不能是 "none"；\n'
    '- reason (string)：判断理由；\n'
    '- legal_basis (array of string)：引用的具体法律依据（例如 "《劳动合同法》第二十条"），'
    "只能引用下面提供的法律依据，不能编造；没有合适依据时给空数组；\n"
    '- suggestion (string)：修改建议；无风险时可以是空字符串。'
)

_EVIDENCE_BLOCK_TEMPLATE = "[{index}] 《{source}》{article}\n{content}"


def _format_evidence(evidence: list[Evidence]) -> str:
    if not evidence:
        return "（未检索到相关法律依据，请如实说明依据不足）"
    blocks = [
        _EVIDENCE_BLOCK_TEMPLATE.format(index=i, source=e.source, article=e.article or "", content=e.content)
        for i, e in enumerate(evidence, start=1)
    ]
    return "\n\n".join(blocks)


def build_review_messages(clause_text: str, clause_type: str, evidence: list[Evidence]) -> list[dict]:
    """把条款原文、条款类型、检索到的法律依据拼成 OpenAI 兼容的 messages。"""
    user_prompt = (
        f"条款类型：{clause_type}\n\n"
        f"条款原文：\n{clause_text}\n\n"
        f"可用的法律依据：\n{_format_evidence(evidence)}"
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
