import UploadPanel from "./UploadPanel.jsx";
import { STATUS_LABELS_ZH } from "../constants.js";

/**
 * ContractLibrary：左侧合同库。只负责展示合同列表 + 触发"新建合同"/"选择合同"，
 * 不发起除 onUpload 回调之外的任何请求——真正调用 API 的地方都在 App。
 */
export default function ContractLibrary({ contracts, currentContractId, onSelect, onUpload, uploadLoading, listLoading }) {
  return (
    <aside className="contract-library">
      <h2 className="library-title">合同库</h2>

      <UploadPanel onUpload={onUpload} loading={uploadLoading} />

      {listLoading && <p className="hint-text">加载合同列表中...</p>}

      {!listLoading && contracts.length === 0 && (
        <p className="hint-text empty-state">还没有合同，先新建一份吧。</p>
      )}

      <ul className="contract-list">
        {contracts.map((contract) => {
          const isActive = contract.contract_id === currentContractId;
          return (
            <li key={contract.contract_id}>
              <button
                type="button"
                className={`contract-list-item${isActive ? " active" : ""}`}
                onClick={() => onSelect(contract.contract_id)}
              >
                <div className="contract-list-name">{contract.filename}</div>
                <div className="contract-list-meta">
                  <span className={`status-tag status-${contract.status}`}>
                    {STATUS_LABELS_ZH[contract.status] || contract.status}
                  </span>
                  <span className="contract-list-version">V1</span>
                </div>
              </button>
            </li>
          );
        })}
      </ul>
    </aside>
  );
}
