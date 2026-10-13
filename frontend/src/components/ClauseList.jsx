/**
 * ClauseList：展示条款列表，并提供"开始审查"按钮。
 * 审查动作（调用 POST /review）完全由父组件 App 的 onReview 完成。
 */
export default function ClauseList({ clauses, onReview, loading }) {
  return (
    <section className="card">
      <h2>合同条款</h2>

      <ul className="clause-list">
        {clauses.map((clause, index) => (
          <li key={clause.clause_id} className="clause-item">
            <div className="clause-heading">
              第{index + 1}条 <span className="clause-id-tag">({clause.clause_id})</span>
            </div>
            <div className="clause-type">{clause.clause_type}</div>
            <p className="clause-text">{clause.original_text}</p>
          </li>
        ))}
      </ul>

      <button type="button" onClick={onReview} disabled={loading}>
        {loading ? "审查中..." : "开始审查"}
      </button>
    </section>
  );
}
