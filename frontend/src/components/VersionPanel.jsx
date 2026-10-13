import { useState } from "react";
import { BATCH_STATUS_LABELS_ZH, RISK_LEVEL_LABELS_ZH } from "../constants.js";
import ReviewReportView from "./ReviewReportView.jsx";

const BLOCKING_STATUSES = new Set(["pending", "waiting_confirmation", "rejected", "needs_human"]);

const RISK_DIFF_CATEGORY_LABELS_ZH = {
  resolved: "风险已消失",
  unchanged: "未变化",
  changed: "风险等级变化",
  new: "新增风险",
  unmatched: "无法可靠匹配",
};

/**
 * VersionPanel："版本" 标签页。
 *
 * V1 永远存在、永远不会被覆盖（本页面本身就是这个事实的体现：不管点了多少次
 * [生成 V2]，展示的 V1 信息都不会变）。V2 是否存在完全由后端 ContractVersion
 * 记录决定，本组件不猜测、不缓存"是否已经生成过"这件事，每次进入合同工作区
 * 都以 App 传下来的 version（来自 GET /contracts/{id}/versions）为准。
 */
export default function VersionPanel({
  contract,
  reviewCount,
  latestReviewId,
  modificationTasks,
  currentBatch,
  onStartBatch,
  startBatchLoading,
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
}) {
  const [showBatchConfirm, setShowBatchConfirm] = useState(false);
  const tasks = modificationTasks || [];
  const batchTasks = currentBatch ? tasks.filter((t) => currentBatch.task_ids.includes(t.task_id)) : [];
  const blockingTasks = batchTasks.filter((t) => BLOCKING_STATUSES.has(t.status));
  const confirmedTasks = batchTasks.filter((t) => t.status === "confirmed");
  // 批次就绪判断只是前端的展示提示，真正的判断永远以后端 ModificationBatch.status
  // （ready_for_v2）为准——这里只是提前给出一个大致提示，避免律师点了按钮才发现不行。
  const canGenerateVersion =
    currentBatch && currentBatch.status === "ready_for_v2" && !version;

  return (
    <section className="card">
      <h2>版本</h2>
      <dl className="info-grid">
        <dt>V1（原始合同）</dt>
        <dd>永久保留，不会被覆盖 · 历史审查次数：{reviewCount}</dd>

        <dt>当前批次</dt>
        <dd>
          {currentBatch
            ? `${currentBatch.batch_id}（${BATCH_STATUS_LABELS_ZH[currentBatch.status] || currentBatch.status}）`
            : "尚未开始一轮修改"}
        </dd>

        <dt>V2（生成新版本）</dt>
        <dd>
          {versionsLoading
            ? "加载中..."
            : version
              ? `已生成（版本 ID：${version.version_id}，生成时间：${new Date(version.created_at).toLocaleString()}）`
              : "尚未生成"}
        </dd>
      </dl>

      {!currentBatch && !version && (
        <div className="version-generate-box">
          {!latestReviewId && <p className="hint-text">请先在"审查结果"标签页完成一次审查，才能以此为依据开始一轮修改。</p>}
          {!showBatchConfirm ? (
            <button type="button" onClick={() => setShowBatchConfirm(true)} disabled={!latestReviewId}>
              开始一轮修改
            </button>
          ) : (
            <div className="modification-task-form-actions">
              <p className="hint-text">将以最近一次审查（{latestReviewId}）为依据开始一轮修改，确认开始？</p>
              <button
                type="button"
                onClick={() => {
                  onStartBatch(latestReviewId);
                  setShowBatchConfirm(false);
                }}
                disabled={startBatchLoading}
              >
                {startBatchLoading ? "创建中..." : "确认开始"}
              </button>
              <button type="button" className="secondary-button" onClick={() => setShowBatchConfirm(false)}>
                取消
              </button>
            </div>
          )}
        </div>
      )}

      {currentBatch && !version && (
        <div className="version-generate-box">
          {currentBatch.status === "v2_failed" && (
            <p className="hint-text">上一次生成 V2 失败：{currentBatch.last_error}。可以重新点击下方按钮重试。</p>
          )}
          {blockingTasks.length > 0 && (
            <p className="hint-text">
              本批次还有 {blockingTasks.length} 条修改任务未落入终态（待处理/待确认/已拒绝待重改/需人工），
              需要先在“修改任务”标签页里处理完（放弃的任务不阻塞，但该条款会保留 V1 原文）。
            </p>
          )}
          {blockingTasks.length === 0 && confirmedTasks.length === 0 && (
            <p className="hint-text">本批次还没有任何已确认的修改任务，没有必要生成 V2。</p>
          )}
          <button
            type="button"
            onClick={() => onGenerateVersion(currentBatch.batch_id)}
            disabled={!canGenerateVersion || generateVersionLoading}
          >
            {generateVersionLoading ? "生成中..." : currentBatch.status === "v2_failed" ? "重试生成 V2" : "生成 V2"}
          </button>
        </div>
      )}

      {version && (
        <div className="version-detail-box">
          <div className="version-detail-actions">
            <button type="button" className="secondary-button" onClick={onLoadDiff} disabled={diffLoading}>
              {diffLoading ? "加载中..." : "查看条款 Diff"}
            </button>
            <button type="button" onClick={onRunVersionReview} disabled={versionReviewLoading}>
              {versionReviewLoading ? "复审中..." : v2ReviewRecord ? "重新发起一次完整审查" : "对 V2 发起完整审查"}
            </button>
          </div>

          {/*
            V2 完整审查结果：严格区分三种状态，不能互相混淆——
              1) 查询失败（v2ReviewError 有值）：网络错误/后端错误，必须给出
                 重试入口，不能当成"还没审查过"安静地吞掉。
              2) 已有记录（v2ReviewRecord 有值）：默认直接展示，不强迫用户
                 重新点一次"完整审查"才能看到——刷新页面、重新进入合同都是
                 走这条路径恢复的，不会再触发一次完整的 LLM 审查工作流。
              3) 尚未审查（两者都为空，且当前也不在"复审中"）：明确提示，
                 保留发起入口。
            versionReviewLoading 为 true 时三种状态都先不展示"尚未审查"的
            提示，避免和正在进行中的请求打架。
          */}
          {v2ReviewError && (
            <div className="failed-clauses-warning">
              <p>查询 V2 审查结果失败：{v2ReviewError}</p>
              <button type="button" className="secondary-button" onClick={onRunVersionReview} disabled={versionReviewLoading}>
                重试
              </button>
            </div>
          )}

          {!v2ReviewError && v2ReviewRecord && (
            <div className="version-review-report">
              <h3>V2 完整审查结果</h3>
              <ReviewReportView
                report={v2ReviewRecord.report}
                meta={`（第 ${v2ReviewRecord.review_id} 次记录 · ${new Date(v2ReviewRecord.created_at).toLocaleString()}）`}
              />
            </div>
          )}

          {!v2ReviewError && !v2ReviewRecord && !versionReviewLoading && (
            <p className="hint-text">还没有对 V2 发起过完整审查，点击上方按钮触发后即可查看完整结果。</p>
          )}

          {diffEntries && (
            <div className="clause-diff-list">
              <h3>条款级 Diff（V1 → V2）</h3>
              {diffEntries.map((entry) => (
                <div key={entry.clause_id} className={`clause-diff-item${entry.changed ? " changed" : ""}`}>
                  <div className="modification-task-header">
                    <span className="modification-task-id">{entry.clause_id}</span>
                    <span className="task-status-tag">
                      {!entry.matched ? "无法匹配" : entry.changed ? "已修改" : "未修改"}
                    </span>
                  </div>
                  <div className="review-field">
                    <span className="review-field-label">V1 原文：</span>
                    <p className="clause-text">{entry.original_text}</p>
                  </div>
                  {entry.changed && entry.modified_text && (
                    <div className="review-field">
                      <span className="review-field-label">V2 文本：</span>
                      <p className="clause-text">{entry.modified_text}</p>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}

          {riskDiffLoading && <p className="hint-text">正在加载风险 Diff...</p>}

          {!riskDiffLoading && riskDiff && (
            <div className="risk-diff-list">
              <h3>V1 / V2 风险 Diff</h3>
              <p className="hint-text">
                对比记录：V1 = {riskDiff.v1_review_id}，V2 = {riskDiff.v2_review_id}
              </p>
              {riskDiff.entries.map((entry, i) => (
                <div key={i} className={`risk-diff-item risk-diff-${entry.category}`}>
                  <div className="modification-task-header">
                    <span className="task-status-tag">{RISK_DIFF_CATEGORY_LABELS_ZH[entry.category] || entry.category}</span>
                    {entry.v1_risk_level && (
                      <span className="hint-text">V1：{RISK_LEVEL_LABELS_ZH[entry.v1_risk_level]}</span>
                    )}
                    {entry.v2_risk_level && (
                      <span className="hint-text">V2：{RISK_LEVEL_LABELS_ZH[entry.v2_risk_level]}</span>
                    )}
                  </div>
                  <p className="clause-text">{entry.description}</p>
                  {entry.category === "unmatched" && (
                    <p className="hint-text">系统无法可靠判断这条结果在另一版本中的对应关系，请人工核实。</p>
                  )}
                </div>
              ))}
            </div>
          )}

          {!riskDiffLoading && !riskDiff && (
            <p className="hint-text">还没有对 V2 发起过完整审查，点击上方按钮触发后即可查看风险 Diff。</p>
          )}
        </div>
      )}
    </section>
  );
}
