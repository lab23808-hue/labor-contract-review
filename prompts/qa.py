"""QA 的 Prompt 模板（Part J）：只负责把"已经组装好的上下文文本"和律师的
问题拼成 messages，不调用 LLM（那是 llm/client.py 的事），不做数据收集
（那是 application/qa_service.py 的事）——和 prompts/review.py、
prompts/modification.py 是同一种分层方式。
"""

SYSTEM_PROMPT = (
    "你是一名劳动合同问答助手，服务对象是正在处理这份合同的律师。\n"
    "你只能依据下面提供的“合同相关数据”回答问题，禁止编造数据中不存在的信息；"
    "如果提供的数据不足以回答问题，必须如实说明数据不足，不要猜测。\n"
    "回答使用简洁、专业的中文，直接给出结论和依据，不需要重复问题本身。"
)


def build_qa_messages(context: str, question: str) -> list[dict]:
    """把已经组装好的上下文文本和问题拼成 OpenAI 兼容的 messages。"""
    user_prompt = f"合同相关数据：\n{context}\n\n律师的问题：\n{question}"
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
