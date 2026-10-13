import { RISK_LEVEL_LABELS_ZH } from "../constants.js";

/**
 * ReviewReportView：只读展示一份完整 ReviewReport（总体风险等级 + summary +
 * 逐条结果）。
 *
 * 这是阶段 02（V2 复审结果持久化与页面状态恢复）新增的组件，职责单一：
 * 给定一份 ReviewReport，原样展示它。不关心这份报告是 V1 的还是 V2 的、
 * 是刚跑完的还是从历史记录里恢复的——调用方（VersionPanel）负责决定什么
 * 时候渲染它、报告从哪里来。
 *
 * 和 ReviewWorkspace.jsx 的关系：ReviewWorkspace 是 V1 审查结果的交互式
 * 视图（可以点选某条结果、查看关联条款原文、从某条风险直接发起"提出修改
 * 意见"），这些交互都依赖"当前合同的 clauses 列表"这个前端状态。V2 目前
 * 没有在前端单独维护一份自己的 clauses 状态（这是阶段 03/04 的条款级联动
 * 范畴，不在本次改动范围内），所以这里只抽出"展示报告本身"这一部分最小
 * 公共逻辑，不把 ReviewWorkspace 整个改造成两个版本共用的交互组件——避免
 * 为了复用而牵动 V1 已经跑通的交互逻辑。样式类名（overall-risk、
 * summary-grid、risk-badge、review-field、modification-task-list 等）
 * 直接复用 styles.css 里已有的定义，不新增任何 CSS，保证两处视觉一致。
 */

function riskClassName(riskLevel) {
  return `risk-badge risk-${riskLevel}`;
}

/** 兼容 clause_id（单条款）和 related_clause_ids（跨条款规则）两种关联方式。 */
function candidateClauseIds(result) {
  if (result.clause_id) return [result.clause_id];
  if (result.related_clause_ids && result.related_clause_ids.length > 0) return result.related_clause_ids;
  return [];
}

function resultLabel(result) {
  if (result.clause_id) return result.clause_id;
  if (result.related_clause_ids && result.related_clause_ids.length > 0) {
    return `跨条款规则（${result.related_clause_ids.length} 条：${result.related_clause_ids.join("、")}）`;
  }
  return "未关联具体条款";
}

export default function ReviewReportView({ report, meta }) {
  if (!report) return null;

  const { summary, overall_risk_level: overallRiskLevel, results, failed_clauses: failedClauses } = report;

  return (
    <div className="review-report-view">
      <div className="overall-risk">
        <span>总体风险等级：</span>
        <span className={riskClassName(overallRiskLevel)}>
          {RISK_LEVEL_LABELS_ZH[overallRiskLevel] || overallRiskLevel}
        </span>
        {meta && <span className="hint-text review-record-meta">{meta}</span>}
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

      {results.length === 0 ? (
        <p className="hint-text">暂无审查结果</p>
      ) : (
        <ul className="modification-task-list">
          {results.map((result, index) => {
            const ids = candidateClauseIds(result);
            return (
              <li key={ids.join("-") || index} className="modification-task-item">
                <div className="modification-task-header">
                  <span className={riskClassName(result.risk_level)}>
                    {RISK_LEVEL_LABELS_ZH[result.risk_level] || result.risk_level}
                  </span>
                  <span className="review-result-directory-label">{resultLabel(result)}</span>
                </div>

                <p className="review-field">
                  <span className="review-field-label">原因：</span>
                  {result.reason}
                </p>

                {result.legal_basis && result.legal_basis.length > 0 && (
                  <p className="review-field">
                    <span className="review-field-label">法律依据：</span>
                    {result.legal_basis.join("；")}
                  </p>
                )}

                {result.suggestion && (
                  <p className="review-field">
                    <span className="review-field-label">修改建议：</span>
                    {result.suggestion}
                  </p>
                )}

                <p className="review-field review-source">
                  <span className="review-field-label">来源：</span>
                  {result.source}
                </p>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
