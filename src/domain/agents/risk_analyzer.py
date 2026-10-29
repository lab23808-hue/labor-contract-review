"""Modified Clause Risk Analyzer（Part D）：对 Modification Agent 生成的候选
文本，重新跑一次独立的审查，判断"改完之后这个条款还有没有风险"。

明确不做的事（避免和已有的 ClauseReviewer 产生重复实现）：
    - 不重新实现 RAG 检索 / LLM 调用——这是 agents.review_agent.ClauseReviewer
      已经验证过的完整链路（生成 query → 检索 Evidence → 构造 Prompt →
      调用 LLM → 校验输出），本模块只是换一个输入（候选文本而不是原文）重新
      跑一遍同一条链路，所以直接复用 ClauseReviewer.review，不新建一套。
    - 不调用完整的 Review Graph（workflows.review_workflow）——那是"一份
      合同全部条款"的编排粒度，这里只需要"单条候选文本"的审查结果。
    - 不做"新结果相比原始风险算不算解决"的业务判断——那是
      modification/risk_resolution.py 的职责，本模块只负责产出一个干净的
      ReviewResult。
    - 不做失败兜底（调用方 modification/service.py::ModificationService.
      start_modification 负责捕获异常、记录 risk_analysis_error、把
      risk_resolution 置为 UNKNOWN，本模块只管"正常时返回 ReviewResult，
      异常时原样抛出"）。
"""

from domain.agents.review_agent import ClauseReviewer
from core import Clause, ReviewResult


def analyze_modified_clause(reviewer: ClauseReviewer, clause: Clause, candidate_text: str) -> ReviewResult:
    """对"把 clause.original_text 替换成 candidate_text"之后的条款，重新跑
    一次独立审查，返回这次审查得到的 ReviewResult。

    构造修改后的 Clause 时只替换 original_text 这一个字段（用 model_copy，
    不手写新的 schema），clause_id / clause_type / metadata 等全部保持不变，
    这样 ClauseReviewer.review 内部用到的 generate_query（依赖
    metadata['article_no'] 之类信息）行为完全一致，不需要任何改动。

    任何异常（检索失败、LLM 调用失败、LLM 输出不合法，即
    agents.review_agent.ReviewError，或其他未预期的异常）原样向上抛出，
    由调用方决定如何处理失败——本函数不做任何兜底。
    """
    modified_clause = clause.model_copy(update={"original_text": candidate_text})
    return reviewer.review(modified_clause)
