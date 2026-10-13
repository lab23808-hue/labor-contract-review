/**
 * V2TextView："V2 原文"标签页。
 *
 * 职责严格限定在"展示指定 V2 的完整原文"本身：不做合同版本管理、不做
 * 审查、不做 Diff——这些已经分别是"版本"标签页和"审查结果"标签页的职责。
 * 数据来源是 GET /contracts/{linked_contract_id}/text（阶段 1 新增的通用
 * 原文读取接口），本组件不自己发请求、不自己管理 loading/error/竞态——
 * 这些都在 App.jsx 里用阶段 02 已经建立的 openRequestRef 机制统一处理，
 * 本组件只是把 App 传下来的 text/loading/error 原样渲染出来，并在用户点击
 * "重试"时调用 onRetry。
 */
export default function V2TextView({ version, text, loading, error, onRetry }) {
  return (
    <section className="card">
      <h2>V2 原文</h2>

      {version && (
        <p className="hint-text">
          当前查看：版本 {version.version_number}（版本 ID：{version.version_id}，
          生成时间：{new Date(version.created_at).toLocaleString()}）
        </p>
      )}

      {loading && <p className="hint-text">正在加载 V2 原文...</p>}

      {!loading && error && (
        <div className="failed-clauses-warning">
          <p>加载 V2 原文失败：{error}</p>
          <button type="button" className="secondary-button" onClick={onRetry}>
            重试
          </button>
        </div>
      )}

      {!loading && !error && text != null && (
        <pre className="v2-text-view-content">{text}</pre>
      )}

      {!loading && !error && text == null && (
        <div className="version-generate-box">
          <p className="hint-text">还没有加载 V2 原文。</p>
          <button type="button" onClick={onRetry}>
            加载 V2 原文
          </button>
        </div>
      )}
    </section>
  );
}
