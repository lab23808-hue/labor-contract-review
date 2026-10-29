"""Modification Agent 的 Prompt 模板 + modify_clause 工具的 Function Calling schema。

只负责"把条款、审查结果、律师意见拼成 messages + 工具定义"，不调用 LLM
（那是 llm/client.py 的事），不做校验（那是 modification/validator.py 的事）。
和 llm/prompts.py（审查用的 Prompt）是同一种分层方式，但故意分成两个文件：
审查 Prompt 和修改 Prompt 是两类完全不同的任务，写在一起只会让两边都更难改。
"""

from typing import Optional, Union

from core import Clause, ReviewResult, ReviewResultSnapshot

# modify_clause：Modification Agent 第一版唯一拥有的工具。
# Agent 负责决定"要不要调用、传什么参数"（即：读懂条款和律师意见，生成修改
# 方案），工具本身只是一个结构化输出的容器——真正的执行（把参数打包成
# ModificationResult、做越界校验）在 modification/tool.py 里。
MODIFY_CLAUSE_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "modify_clause",
        "description": (
            "根据原始条款文本、审查发现的风险和律师的修改意见，生成这一个条款的修改后文本。"
            "只能修改这一个指定的条款，绝不能包含或涉及合同中其他条款的内容。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "clause_id": {
                    "type": "string",
                    "description": "本次修改针对的条款 id，必须和输入中给出的目标条款 id 完全一致。",
                },
                "modified_text": {
                    "type": "string",
                    "description": (
                        "修改后的完整条款正文，必须是可以直接替换原条款的正式合同条文；"
                        "如果原条款以“第X条”开头，修改后的文本也必须保留同样的条款编号和标题；"
                        "不允许包含占位符、说明性文字或未完成的内容。"
                    ),
                },
                "reason": {
                    "type": "string",
                    "description": "这样修改的理由（结合审查结果和律师意见简要说明）。",
                },
                "legal_basis": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "支持这次修改的法律依据，没有合适依据时给空数组。",
                },
            },
            "required": ["clause_id", "modified_text", "reason"],
        },
    },
}

SYSTEM_PROMPT = (
    "你是一名劳动合同修改助手。你的唯一任务是：针对律师指定的一个条款，"
    "结合审查发现的风险和律师的修改意见，生成这个条款修改后的正式文本。\n"
    "硬性规则（必须遵守）：\n"
    "1. 只能修改用户指定的那一个条款，绝不能输出或涉及合同中其他条款的内容；\n"
    "2. 如果原条款文本以“第X条”开头，修改后的文本必须保留完全相同的条款编号和标题，"
    "不能删除、不能改变编号；\n"
    "3. 修改后的文本必须是完整、可以直接使用的正式合同条文，不能包含"
    "“TODO”“待补充”“……”等占位符或说明性文字，不能有明显的截断；\n"
    "4. 必须且只能通过调用 modify_clause 这一个工具返回结果，不允许直接用文字回复。"
)


def _format_review_result(review_result: Optional[Union[ReviewResult, ReviewResultSnapshot]]) -> str:
    if review_result is None:
        return "（这个条款没有关联的审查结果）"
    lines = [
        f"风险等级：{review_result.risk_level.value}",
        f"审查意见：{review_result.reason}",
    ]
    if review_result.legal_basis:
        lines.append("法律依据：" + "；".join(review_result.legal_basis))
    if review_result.suggestion:
        lines.append(f"审查建议：{review_result.suggestion}")
    return "\n".join(lines)


def _format_lawyer_instructions(lawyer_instructions: list[str]) -> str:
    return "\n".join(f"第{i}次意见：{text}" for i, text in enumerate(lawyer_instructions, start=1))


def build_modification_messages(
    clause: Clause,
    review_result: Optional[Union[ReviewResult, ReviewResultSnapshot]],
    lawyer_instructions: list[str],
) -> list[dict]:
    """把目标条款、审查结果、【累计的】律师意见拼成 messages。

    每次生成候选都必须基于 clause.original_text（原始条款），不是基于上一次
    生成的候选文本——这是"拒绝后不能在错误结果上继续叠加"这条硬约束在
    Prompt 层面的体现：本函数的输入压根不接受"上一轮候选文本"这个参数。
    律师历次的意见全部列出（累计意见），让模型看到完整的修改诉求演变过程，
    而不是只看最后一条、丢失前面的上下文。
    """
    user_prompt = (
        f"目标条款 id：{clause.clause_id}\n"
        f"条款类型：{clause.clause_type}\n\n"
        f"原始条款文本：\n{clause.original_text}\n\n"
        f"审查结果：\n{_format_review_result(review_result)}\n\n"
        f"律师的修改意见（按时间顺序，请综合全部意见）：\n"
        f"{_format_lawyer_instructions(lawyer_instructions)}\n\n"
        f"请调用 modify_clause 工具，生成 {clause.clause_id} 修改后的条款文本。"
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
