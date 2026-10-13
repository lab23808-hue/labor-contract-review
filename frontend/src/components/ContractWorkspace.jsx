import { STATUS_LABELS_ZH } from "../constants.js";
import ContractOverview from "./ContractOverview.jsx";
import ClauseViewer from "./ClauseViewer.jsx";
import ReviewWorkspace from "./ReviewWorkspace.jsx";
import ModificationTaskPanel from "./ModificationTaskPanel.jsx";
import VersionPanel from "./VersionPanel.jsx";
import QAPanel from "./QAPanel.jsx";
import V2TextView from "./V2TextView.jsx";

const TABS = [
  { key: "overview", label: "概览" },
  { key: "clauses", label: "条款" },
  { key: "review", label: "审查结果" },
  { key: "tasks", label: "修改任务" },
  { key: "version", label: "版本" },
  // "V2 原文"只在确实已经生成 V2 时才出现（见下方 visibleTabs 的过滤），
  // 不在这个静态列表里直接判断——这个数组本身不知道"当前合同"是谁。
  { key: "v2text", label: "V2 原文" },
  { key: "qa", label: "问答" },
];

/**
 * ContractWorkspace：右侧主工作区。拥有"当前合同"这一层的导航（顶部信息条 +
 * 标签页），具体每个标签页的内容委托给对应的子组件；本组件不直接调用任何
 * API，只把 App 传下来的数据和回调转发给子组件。
 */
export default function ContractWorkspace({
  contract,
  clauses,
  reviewRecord,
  reviewHistoryCount,
  modificationTasks,
  activeView,
  onChangeView,
  selectedClauseId,
  onSelectClause,
  onParse,
  parseLoading,
  onReview,
  reviewLoading,
  onLocateClause,
  onCreateModificationTask,
  taskSubmitting,
  workspaceLoading,
  onStartModification,
  onConfirmModification,
  onRejectModification,
  onAbandonModification,
  busyTaskId,
  currentBatch,
  onStartBatch,
  startBatchLoading,
  latestReviewId,
  version,
  versionsLoading,
  onGenerateVersion,
  generateVersionLoading,
  diffEntries,
  diffLoading,
  onLoadDiff,
  riskDiff,
  riskDiffLoading,
  onRunVersionReview,
  versionReviewLoading,
  v2ReviewRecord,
  v2ReviewError,
  v2Text,
  v2TextLoading,
  v2TextError,
  onLoadV2Text,
  onAsk,
  asking,
  lastAnswer,
  lastQuestion,
}) {
  if (workspaceLoading) {
    return (
      <main className="contract-workspace">
        <p className="hint-text">加载合同工作区中...</p>
      </main>
    );
  }

  if (!contract) {
    return (
      <main className="contract-workspace">
        <div className="empty-state workspace-empty-state">
          <p>从左侧合同库选择一份合同，或新建一份合同开始。</p>
        </div>
      </main>
    );
  }

  // "V2 原文"标签只在这份合同确实已经生成 V2 时才展示——version 来自
  // App.jsx 用 GET /contracts/{id}/versions 查到的真实数据，不是前端猜测
  // 出来的，version 为 null 就是"这份合同还没有 V2"的权威答案。
  const visibleTabs = TABS.filter((tab) => tab.key !== "v2text" || Boolean(version));

  return (
    <main className="contract-workspace">
      <div className="workspace-header">
        <h1 className="workspace-title">{contract.filename}</h1>
        <div className="workspace-meta">
          <span className={`status-tag status-${contract.status}`}>
            {STATUS_LABELS_ZH[contract.status] || contract.status}
          </span>
          <span>当前版本：V1</span>
          <span>更新时间：{new Date(contract.updated_at).toLocaleString()}</span>
        </div>
      </div>

      <nav className="workspace-tabs">
        {visibleTabs.map((tab) => (
          <button
            key={tab.key}
            type="button"
            className={`workspace-tab${activeView === tab.key ? " active" : ""}`}
            onClick={() => onChangeView(tab.key)}
          >
            {tab.label}
          </button>
        ))}
      </nav>

      <div className="workspace-content">
        {activeView === "overview" && (
          <ContractOverview contract={contract} onParse={onParse} parseLoading={parseLoading} />
        )}
        {activeView === "clauses" && (
          <ClauseViewer clauses={clauses} selectedClauseId={selectedClauseId} onSelectClause={onSelectClause} />
        )}
        {activeView === "review" && (
          <ReviewWorkspace
            reviewRecord={reviewRecord}
            clauses={clauses || []}
            reviewLoading={reviewLoading}
            onReview={onReview}
            onLocateClause={onLocateClause}
            onCreateModificationTask={onCreateModificationTask}
            taskSubmitting={taskSubmitting}
            currentBatch={currentBatch}
          />
        )}
        {activeView === "tasks" && (
          <ModificationTaskPanel
            tasks={modificationTasks}
            onStart={onStartModification}
            onConfirm={onConfirmModification}
            onReject={onRejectModification}
            onAbandon={onAbandonModification}
            busyTaskId={busyTaskId}
          />
        )}
        {activeView === "version" && (
          <VersionPanel
            contract={contract}
            reviewCount={reviewHistoryCount}
            latestReviewId={latestReviewId}
            modificationTasks={modificationTasks}
            currentBatch={currentBatch}
            onStartBatch={onStartBatch}
            startBatchLoading={startBatchLoading}
            version={version}
            versionsLoading={versionsLoading}
            onGenerateVersion={onGenerateVersion}
            generateVersionLoading={generateVersionLoading}
            diffEntries={diffEntries}
            diffLoading={diffLoading}
            onLoadDiff={onLoadDiff}
            riskDiff={riskDiff}
            riskDiffLoading={riskDiffLoading}
            onRunVersionReview={onRunVersionReview}
            versionReviewLoading={versionReviewLoading}
            v2ReviewRecord={v2ReviewRecord}
            v2ReviewError={v2ReviewError}
          />
        )}
        {activeView === "v2text" && (
          <V2TextView version={version} text={v2Text} loading={v2TextLoading} error={v2TextError} onRetry={onLoadV2Text} />
        )}
        {activeView === "qa" && (
          <QAPanel onAsk={onAsk} asking={asking} lastAnswer={lastAnswer} lastQuestion={lastQuestion} />
        )}
      </div>
    </main>
  );
}
