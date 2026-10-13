/**
 * ClauseViewer："条款" 标签页。左侧条款目录，右侧当前选中条款的详情。
 * 合同正文只读，不提供任何编辑能力。
 */
export default function ClauseViewer({ clauses, selectedClauseId, onSelectClause }) {
  if (!clauses || clauses.length === 0) {
    return (
      <section className="card">
        <h2>合同条款</h2>
        <p className="hint-text empty-state">这份合同还没有解析出条款，请先在“概览”标签页解析合同。</p>
      </section>
    );
  }

  const selected = clauses.find((c) => c.clause_id === selectedClauseId) || clauses[0];

  return (
    <section className="card clause-viewer">
      <h2>合同条款</h2>
      <div className="clause-viewer-body">
        <ul className="clause-directory">
          {clauses.map((clause, index) => (
            <li key={clause.clause_id}>
              <button
                type="button"
                className={`clause-directory-item${clause.clause_id === selected.clause_id ? " active" : ""}`}
                onClick={() => onSelectClause(clause.clause_id)}
              >
                第{index + 1}条
                <span className="clause-directory-type">{clause.clause_type}</span>
              </button>
            </li>
          ))}
        </ul>

        <div className="clause-detail">
          <div className="clause-heading">
            {selected.clause_id} <span className="clause-type-tag">{selected.clause_type}</span>
          </div>
          <p className="clause-text">{selected.original_text}</p>

          {selected.parent_clause && <p className="hint-text">所属上级条款：{selected.parent_clause}</p>}
          {typeof selected.page_number === "number" && <p className="hint-text">页码：{selected.page_number}</p>}
        </div>
      </div>
    </section>
  );
}
