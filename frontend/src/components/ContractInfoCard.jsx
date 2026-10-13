const STATUS_LABELS_ZH = {
  uploaded: "已上传",
  parsed: "已解析",
  split: "已切分条款",
  reviewed: "已生成审查报告",
  failed: "失败",
};

/**
 * ContractInfoCard：展示合同元数据，并提供"解析合同"按钮。
 * 解析动作（调用 POST /parse，随后 GET /contracts/{id} 刷新状态）
 * 完全由父组件 App 的 onParse 完成，这里只负责触发和展示。
 */
export default function ContractInfoCard({ contract, onParse, loading }) {
  const statusLabel = STATUS_LABELS_ZH[contract.status] || contract.status;

  return (
    <section className="card">
      <h2>合同信息</h2>
      <dl className="info-grid">
        <dt>文件名</dt>
        <dd>{contract.filename}</dd>

        <dt>状态</dt>
        <dd>{statusLabel}</dd>

        <dt>文件大小</dt>
        <dd>{contract.size_bytes} 字节</dd>

        <dt>SHA256</dt>
        <dd className="mono-text">{contract.sha256}</dd>

        <dt>合同 ID</dt>
        <dd className="mono-text">{contract.contract_id}</dd>
      </dl>

      {contract.error && <p className="error-text">失败原因：{contract.error}</p>}

      <button type="button" onClick={onParse} disabled={loading}>
        {loading ? "解析中..." : "解析合同"}
      </button>
    </section>
  );
}
