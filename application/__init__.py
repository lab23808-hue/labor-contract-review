"""application：API 和 Workflow/Capability 之间的 Application 层。

架构分层：API → Application/Workflow → Capability → Infrastructure/Storage。

本包目前有两个 Application 服务：
    review_service.py   Review Application——调用 Review Workflow，决定要不要
                         持久化，向上同时服务 V1 审查（API 直接调用）和 V2
                         审查（ModificationService 生成 V2 之后，API 用解析
                         出来的 V2 contract_id 调用同一个服务）。
    diff_service.py      Diff Application——用 ContractManager 取出 V1/V2 的
                         Clause / ReviewRecord，调用 diff 包里的纯函数，组装
                         成对外的 Diff 结果。

两者都不做 HTTP、不碰 LangGraph 节点内部、不做 LLM Prompt、不做 RAG、
互相之间也不调用——各自只向下依赖 Workflow/Capability/Storage，不依赖
对方，也不依赖 ModificationService。
"""
