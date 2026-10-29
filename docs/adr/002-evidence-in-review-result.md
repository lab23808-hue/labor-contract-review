# ADR 002：Evidence 进入 ReviewResult

## 背景

`ReviewResult` 原先只有 LLM 自报的 `legal_basis: list[str]`，无法追溯模型实际看到了哪些检索证据。

## 决策

- `ReviewResult` 新增 `evidences: list[Evidence] = []`（向后兼容）。
- `ClauseReviewer.review` 把本次检索到的 Evidence 写入结果。
- `ReviewGraphState` 增加 `retrieval_results` / `retrieval_errors`。
- `ReviewVersions` 记录 llm_model、prompt_version、ruleset_version、knowledge_base_version。

## 结果

审查结果可以追溯 Evidence 本体；Prompt 要求 `legal_basis` 只能引用所提供的 `source + article`。
