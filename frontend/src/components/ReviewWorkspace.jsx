import { useState } from "react";
import { RISK_LEVEL_LABELS_ZH } from "../constants.js";
import ModificationTaskForm from "./ModificationTaskForm.jsx";

function riskClassName(riskLevel) {
  return `risk-badge risk-${riskLevel}`;
}

function findClauseById(clauses, clauseId) {
  return clauses.find((c) => c.clause_id === clauseId) || null;
}

function findClauseIndex(clauses, clauseId) {
  return clauses.findIndex((c) => c.clause_id === clauseId);
}

/** 一条 ReviewResult 关联到的候选条款 id 列表——兼容 clause_id / related_clause_ids 两种方式。 */
function candidateClauseIds(result) {
  if (result.clause_id) return [result.clause_id];
  if (result.related_clause_ids && result.related_clause_ids.length > 0) return result.related_clause_ids;
  return [];
}

function resultListLabel(result, clauses) {
  if (result.clause_id) {
    const index = findClauseIndex(clauses, result.clause_id);
    return index >= 0 ? `第${index + 1}条` : result.clause_id;
  }
  if (result.related_clause_ids && result.related_clause_ids.length > 0) {
    return `跨条款规则（${result.related_clause_ids.length} 条）`;
  }
  return "未关联具体条款";
}

/**
 * RelatedClauses：展示某条 ReviewResult 关联的条款原文。
 * 硬约束：不能假设每条 ReviewResult 都有 clause_id——必须同时兼容
 * clause_id（单条款）和 related_clause_ids（跨条款规则）两种关联方式，
 * 两者都没有时展示"未关联具体条款"，绝不能因为 clause_id 为空而崩溃。
 */
function RelatedClauses({ result, clauses }) {
  const ids = candidateClauseIds(result);

  if (ids.length === 0) {
    return <p className="hint-text">未关联具体条款</p>;
  }

  return (
    <div className="related-clauses">
      <div className="related-clauses-title">相关条款：</div>
      {ids.map((clauseId) => {
        const clause = findClauseById(clauses, clauseId);
        return (
          <div className="related-clause-block" key={clauseId}>
            <div className="clause-heading">{clauseId}</div>
            <p className="clause-text">
              {clause ? clause.original_text : "（未能在当前条款列表中找到该条款）"}
            </p>
          </div>
        );
      })}
    </div>
  );
}

export default function ReviewWorkspace({
  reviewRecord,
  clauses,
  reviewLoading,
  onReview,
  onLocateClause,
  onCreateModificationTask,
  taskSubmitting,
  currentBatch,
}) {
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [taskFormClauseId, setTaskFormClauseId] = useState(null);

  const hasClauses = clauses && clauses.length > 0;
  const report = reviewRecord ? reviewRecord.report : null;

  if (!hasClauses) {
    return (
      <section className="card">
        <h2>审查结果</h2>
        <p className="hint-text empty-state">这份合同还没有解析出条款，请先在“概览”标签页解析合同。</p>
      </section>
    );
  }

  async function handleSubmitTask(clauseId, instruction) {
    await onCreateModificationTask({
      clauseId,
      lawyerInstruction: instruction,
    });
    setTaskFormClauseId(null);
  }

  if (!report) {
    return (
      <section className="card">
        <h2>审查结果</h2>
        <p className="hint-text empty-state">这份合同还没有审查结果。</p>
        <button type="button" onClick={onReview} disabled={reviewLoading}>
          {reviewLoading ? "审查中..." : "开始审查"}
        </button>
      </section>
    );
  }

  const { summary, overall_risk_level: overallRiskLevel, results, failed_clauses: failedClauses } = report;
  const selectedResult = results[selectedIndex] || null;
  const candidates = selectedResult ? candidateClauseIds(selectedResult) : [];

  return (
    <section className="card">
      <h2>审查结果</h2>

      <div className="overall-risk">
        <span>总体风险等级：</span>
        <span className={riskClassName(overallRiskLevel)}>
          {RISK_LEVEL_LABELS_ZH[overallRiskLevel] || overallRiskLevel}
        </span>
        <span className="hint-text review-record-meta">
          （第 {reviewRecord.review_id} 次记录 · {new Date(reviewRecord.created_at).toLocaleString()}）
        </span>
      </div>

      <div className="summary-grid">
        <div className="summary-item risk-high">高风险：{summary.high}</div>
        <div className="summary-item risk-medium">中风险：{summary.medium}</div>
        <div className="summary-item risk-low">低风险：{summary.low}</div>
        <div className="summary-item risk-none">无风险：{summary.none}</div>
      </div>

      {failedClauses && failedClauses.length > 0 && (
        <div className="failed-clauses-warning">
          <p>部分条款审查失败，整体审查结果可能不完整。以下条款未完成风险判断：</p>
          <ul>
            {failedClauses.map((failed) => (
              <li key={failed.clause_id}>
                {failed.clause_id}：{failed.error}
              </li>
            ))}
          </ul>
        </div>
      )}

      <button type="button" onClick={onReview} disabled={reviewLoading}>
        {reviewLoading ? "审查中..." : "重新审查"}
      </button>

      {results.length === 0 ? (
        <p className="hint-text">暂无审查结果</p>
      ) : (
        <div className="review-workspace-body">
          <ul className="review-result-directory">
            {results.map((result, index) => (
              <li key={index}>
                <button
                  type="button"
                  className={`review-result-directory-item${index === selectedIndex ? " active" : ""}`}
                  onClick={() => {
                    setSelectedIndex(index);
                    setTaskFormClauseId(null);
                  }}
                >
                  <span className={riskClassName(result.risk_level)}>
                    {RISK_LEVEL_LABELS_ZH[result.risk_level] || result.risk_level}
                  </span>
                  <span className="review-result-directory-label">{resultListLabel(result, clauses)}</span>
                </button>
              </li>
            ))}
          </ul>

          {selectedResult && (
            <div className="review-result-detail">
              <div className={riskClassName(selectedResult.risk_level)}>
                {RISK_LEVEL_LABELS_ZH[selectedResult.risk_level] || selectedResult.risk_level}
              </div>

              <p className="review-field">
                <span className="review-field-label">原因：</span>
                {selectedResult.reason}
              </p>

              {selectedResult.legal_basis && selectedResult.legal_basis.length > 0 && (
                <p className="review-field">
                  <span className="review-field-label">法律依据：</span>
                  {selectedResult.legal_basis.join("；")}
                </p>
              )}

              {selectedResult.suggestion && (
                <p className="review-field">
                  <span className="review-field-label">修改建议：</span>
                  {selectedResult.suggestion}
                </p>
              )}

              <p className="review-field review-source">
                <span className="review-field-label">来源：</span>
                {selectedResult.source}
              </p>

              <RelatedClauses result={selectedResult} clauses={clauses} />

              {candidates.length > 0 && (
                <div className="review-result-actions">
                  {candidates.length === 1 ? (
                    <button type="button" className="secondary-button" onClick={() => onLocateClause(candidates[0])}>
                      在条款中查看
                    </button>
                  ) : (
                    candidates.map((clauseId) => (
                      <button
                        type="button"
                        className="secondary-button"
                        key={clauseId}
                        onClick={() => onLocateClause(clauseId)}
                      >
                        查看 {clauseId}
                      </button>
                    ))
                  )}

                  {taskFormClauseId === null ? (
                    <button type="button" onClick={() => setTaskFormClauseId(candidates[0])}>
                      提出修改意见
                    </button>
                  ) : null}
                </div>
              )}

              {taskFormClauseId && (
                <ModificationTaskForm
                  clauseId={taskFormClauseId}
                  originalText={
                    findClauseById(clauses, taskFormClauseId)?.original_text || "（未能找到该条款原文）"
                  }
                  submitting={taskSubmitting}
                  disabled={!currentBatch}
                  disabledHint={
                    !currentBatch
                      ? "还没有开启一轮修改，请先在“修改任务”标签页点击“开始一轮修改”。"
                      : null
                  }
                  onCancel={() => setTaskFormClauseId(null)}
                  onSubmit={(instruction) => handleSubmitTask(taskFormClauseId, instruction)}
                />
              )}
            </div>
          )}
        </div>
      )}
    </section>
  );
}
