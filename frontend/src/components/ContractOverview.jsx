import { STATUS_LABELS_ZH } from "../constants.js";

/**
 * ContractOverview："概览" 标签页。展示合同元数据，并在状态允许时提供
 * "解析合同" 入口。所有展示字段直接取自后端返回的 Contract，不在这里
 * 猜测或重新计算 status。
 */
export default function ContractOverview({ contract, onParse, parseLoading }) {
  const statusLabel = STATUS_LABELS_ZH[contract.status] || contract.status;
  const canParse = contract.status === "uploaded";

  return (
    <section className="card">
      <h2>合同概览</h2>
      <dl className="info-grid">
        <dt>合同名称</dt>
        <dd>{contract.filename}</dd>

        <dt>文件格式</dt>
        <dd>{contract.file_format}</dd>

        <dt>文件大小</dt>
        <dd>{contract.size_bytes} 字节</dd>

        <dt>SHA256</dt>
        <dd className="mono-text">{contract.sha256}</dd>

        <dt>合同 ID</dt>
        <dd className="mono-text">{contract.contract_id}</dd>

        <dt>当前状态</dt>
        <dd>
          <span className={`status-tag status-${contract.status}`}>{statusLabel}</span>
        </dd>

        <dt>当前版本</dt>
        <dd>V1（原始合同）</dd>

        <dt>创建时间</dt>
        <dd>{new Date(contract.created_at).toLocaleString()}</dd>

        <dt>更新时间</dt>
        <dd>{new Date(contract.updated_at).toLocaleString()}</dd>
      </dl>

      {contract.error && <p className="error-text">失败原因：{contract.error}</p>}

      {canParse && (
        <button type="button" onClick={onParse} disabled={parseLoading}>
          {parseLoading ? "解析中..." : "解析合同"}
        </button>
      )}
      {!canParse && (
        <p className="hint-text">
          {contract.status === "failed" ? "该合同处理失败，暂无法继续。" : "该合同已完成解析，可在“条款”标签页查看。"}
        </p>
      )}
    </section>
  );
}
