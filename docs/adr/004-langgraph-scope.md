# ADR 004：LangGraph 只负责审查流程

## 决策

- 合同审查使用 LangGraph：`contract_loading → retrieve → llm_review`，`contract_loading → rule_check`，汇合到 `merge → report_assembly`。
- 修改闭环使用 `ModificationService` 的显式状态机，不放进 LangGraph。
- V2 生成、Diff 由 application service 负责。

## 理由

审查是固定 DAG，需要分支汇合和独立节点观测；修改闭环是长时间、人工确认驱动的状态机，LangGraph 的图执行不是它的合适抽象。
