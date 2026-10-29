"""app：API 和 Workflow/Capability 之间的用例层。

架构分层：API → App/Workflow → Domain/Retrieval/Infra → Core。

本包目前有三个用例服务：
    review_service.py             Review Application——调用 Review Workflow，
                                  决定是否持久化。
    diff_service.py               Diff Application——取出 V1/V2 数据，调用
                                  domain.diff 的纯函数。
    v2_generation_service.py      V2 Application——批次就绪判断、V2 全文重建、
                                  新 Contract 生成。

三者都不做 HTTP、不碰 LangGraph 节点内部、不做 LLM Prompt、不做检索实现。
"""
