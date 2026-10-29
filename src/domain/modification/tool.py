"""modify_clause 工具的执行逻辑。

Agent（modification/agent.py）负责"决定调用这个工具、传什么参数"——那是
LLM 通过 Function Calling 做的事。本文件负责"工具被调用之后，怎么把参数
变成一个受信任的 ModificationResult"，这是纯 Python 逻辑，不调用 LLM。

这里是防止"模型跑题去改别的条款"的第一道防线（第二道是
modification/validator.py 基于条款编号的范围校验）：如果模型传回的
clause_id 和律师本来要修改的目标条款不一致，直接拒绝，不让这种结果进入
后续任何流程。
"""

from pydantic import ValidationError

from core import ModificationResult


class ModificationToolError(Exception):
    """modify_clause 工具的参数不合法，或者引用了非目标条款。"""


def execute_modify_clause(expected_clause_id: str, arguments: dict) -> ModificationResult:
    """把 Function Calling 返回的原始参数转换成 ModificationResult。

    expected_clause_id：这次任务本来要修改的目标条款 id（来自 ModificationTask.
    target_clause_id），不是由模型决定的——模型只是被要求"回填"这个 id，
    这里做强制核对。
    """
    called_clause_id = arguments.get("clause_id")
    if called_clause_id != expected_clause_id:
        raise ModificationToolError(
            f"工具调用的 clause_id 与目标条款不一致（预期 {expected_clause_id!r}，"
            f"实际 {called_clause_id!r}）——拒绝执行，防止越界修改其他条款。"
        )

    try:
        return ModificationResult(
            clause_id=called_clause_id,
            modified_text=arguments.get("modified_text", ""),
            reason=arguments.get("reason", ""),
            legal_basis=arguments.get("legal_basis") or [],
        )
    except ValidationError as exc:
        raise ModificationToolError(f"modify_clause 返回的参数不合法：{exc}") from exc
