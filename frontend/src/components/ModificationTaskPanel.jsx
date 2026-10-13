import { useState } from "react";
import { MAX_MODIFICATION_ATTEMPTS, RISK_RESOLUTION_LABELS_ZH, TASK_STATUS_LABELS_ZH } from "../constants.js";

/** 一次 ModificationAttempt 里"修改后风险分析"的展示区。 */
function RiskAnalysisBox({ attempt }) {
  if (attempt.risk_analysis_error) {
    return (
      <div className="risk-analysis-box risk-analysis-error">
        <span className="review-field-label">修改后风险分析：</span>
        调用失败（{attempt.risk_analysis_error}），风险化解结论暂无法判断。
      </div>
    );
  }
  if (!attempt.risk_analysis) {
    return null;
  }
  return (
    <div className="risk-analysis-box">
      <span className="review-field-label">修改后风险分析：</span>
      风险等级 = {attempt.risk_analysis.risk_level}；
      风险化解结论 = {RISK_RESOLUTION_LABELS_ZH[attempt.risk_resolution] || attempt.risk_resolution}
      <p className="hint-text">{attempt.risk_analysis.reason}</p>
    </div>
  );
}

/**
 * 单条修改任务的操作区：根据 task.status 决定这一刻能做什么。
 *
 * 状态 -> 可操作动作（和后端 schemas/modification_task.py 的状态机严格对应，
 * 不在前端重新发明规则，只是把当前状态翻译成"这一刻能点哪些按钮"）：
 *   pending / rejected（can_start）  -> [开始修改]（rejected 下还能 [放弃]）
 *   waiting_confirmation              -> 展示最新一轮候选 + 风险分析 + [确认修改] / [不满意，重新修改]
 *   needs_human                        -> [手工确认结果并提交] / [放弃这条任务]
 *   confirmed / abandoned              -> 只展示状态，不提供任何操作（终态）
 */
function TaskActions({ task, onStart, onConfirm, onReject, onAbandon, busy }) {
  const [showRejectForm, setShowRejectForm] = useState(false);
  const [newInstruction, setNewInstruction] = useState("");
  const [manualText, setManualText] = useState("");

  const latestAttempt =
    task.modification_attempts && task.modification_attempts.length > 0
      ? task.modification_attempts[task.modification_attempts.length - 1]
      : null;

  if (task.status === "pending" || task.status === "rejected") {
    return (
      <div className="modification-task-actions">
        {latestAttempt && !latestAttempt.validator_passed && (
          <div className="validator-error-box">
            <div className="hint-text">上一轮候选未通过校验：</div>
            <ul>
              {latestAttempt.validator_errors.map((err, i) => (
                <li key={i}>{err}</li>
              ))}
            </ul>
          </div>
        )}
        <div className="hint-text">
          已尝试 {task.modification_attempts.length} / {MAX_MODIFICATION_ATTEMPTS} 轮
        </div>
        <div className="modification-task-form-actions">
          <button type="button" onClick={() => onStart(task.task_id)} disabled={busy}>
            {busy ? "生成中..." : "开始修改"}
          </button>
          {task.status === "rejected" && (
            <button type="button" className="secondary-button" onClick={() => onAbandon(task.task_id)} disabled={busy}>
              放弃这条任务
            </button>
          )}
        </div>
      </div>
    );
  }

  if (task.status === "waiting_confirmation") {
    return (
      <div className="modification-task-actions">
        <div className="modification-candidate-box">
          <div className="review-field">
            <span className="review-field-label">Agent 生成的修改结果：</span>
            <p className="clause-text">{task.current_modified_text}</p>
          </div>
          {latestAttempt && (
            <>
              <div className="review-field">
                <span className="review-field-label">修改理由：</span>
                {latestAttempt.reason || "（未提供）"}
              </div>
              {latestAttempt.legal_basis.length > 0 && (
                <div className="review-field">
                  <span className="review-field-label">法律依据：</span>
                  {latestAttempt.legal_basis.join("；")}
                </div>
              )}
              <RiskAnalysisBox attempt={latestAttempt} />
            </>
          )}
        </div>

        {!showRejectForm ? (
          <div className="modification-task-form-actions">
            <button type="button" onClick={() => onConfirm(task.task_id)} disabled={busy}>
              {busy ? "处理中..." : "确认修改"}
            </button>
            <button type="button" className="secondary-button" onClick={() => setShowRejectForm(true)} disabled={busy}>
              不满意，重新修改
            </button>
          </div>
        ) : (
          <div className="modification-task-form">
            <textarea
              className="modification-task-textarea"
              placeholder="请说明还需要怎么改，例如：金额调整得还不够，请再提高。"
              value={newInstruction}
              onChange={(e) => setNewInstruction(e.target.value)}
              disabled={busy}
              rows={2}
            />
            <div className="modification-task-form-actions">
              <button
                type="button"
                onClick={() => {
                  const trimmed = newInstruction.trim();
                  if (!trimmed) return;
                  onReject(task.task_id, trimmed);
                  setShowRejectForm(false);
                  setNewInstruction("");
                }}
                disabled={!newInstruction.trim() || busy}
              >
                {busy ? "提交中..." : "提交并重新生成"}
              </button>
              <button type="button" className="secondary-button" onClick={() => setShowRejectForm(false)} disabled={busy}>
                取消
              </button>
            </div>
          </div>
        )}
      </div>
    );
  }

  if (task.status === "needs_human") {
    return (
      <div className="modification-task-actions">
        <p className="hint-text empty-state">
          已尝试 {MAX_MODIFICATION_ATTEMPTS} 轮仍未得到确认的修改结果，需要人工介入处理：可以手工确定最终文本并提交确认，
          也可以直接放弃这条任务（保留 V1 原文）。系统不会再自动重试。
        </p>
        <textarea
          className="modification-task-textarea"
          placeholder="律师手工确定的最终条款文本（确认后将作为这条任务的最终结果）"
          value={manualText}
          onChange={(e) => setManualText(e.target.value)}
          disabled={busy}
          rows={3}
        />
        <div className="modification-task-form-actions">
          <button
            type="button"
            onClick={() => onConfirm(task.task_id, manualText.trim())}
            disabled={!manualText.trim() || busy}
          >
            {busy ? "处理中..." : "手工确认结果并提交"}
          </button>
          <button type="button" className="secondary-button" onClick={() => onAbandon(task.task_id)} disabled={busy}>
            放弃这条任务
          </button>
        </div>
      </div>
    );
  }

  if (task.status === "confirmed") {
    return <p className="hint-text">已确认，等待批次就绪后生成 V2（V2 生成成功与否都不会改变这条任务的状态）。</p>;
  }

  // abandoned
  return <p className="hint-text">已放弃，V2 中这条条款将保留 V1 原文。</p>;
}

/**
 * ModificationTaskPanel："修改任务" 标签页：展示当前合同的修改任务列表，
 * 并驱动每条任务的 开始修改/确认/拒绝/放弃 操作（Human-in-the-loop 的落地
 * 位置——本组件只发起动作、展示后端返回的状态，不在前端自己判断"这次修改
 * 算不算通过"，那永远由后端 Validator 决定）。
 */
export default function ModificationTaskPanel({ tasks, onStart, onConfirm, onReject, onAbandon, busyTaskId }) {
  if (!tasks || tasks.length === 0) {
    return (
      <section className="card">
        <h2>修改任务</h2>
        <p className="hint-text empty-state">
          还没有修改任务。先在"版本"标签页开始一轮修改，再在"审查结果"或"条款"标签页里针对具体条款提出修改意见。
        </p>
      </section>
    );
  }

  return (
    <section className="card">
      <h2>修改任务</h2>
      <ul className="modification-task-list">
        {tasks.map((task) => (
          <li key={task.task_id} className="modification-task-item">
            <div className="modification-task-header">
              <span className="modification-task-id">修改任务 #{task.task_id.replace("task_", "")}</span>
              <span className={`task-status-tag task-status-${task.status}`}>
                {TASK_STATUS_LABELS_ZH[task.status] || task.status}
              </span>
            </div>
            <div className="review-field">
              <span className="review-field-label">所属批次：</span>
              {task.batch_id}
            </div>
            <div className="review-field">
              <span className="review-field-label">条款：</span>
              {task.target_clause_id}
            </div>
            <div className="review-field">
              <span className="review-field-label">原内容：</span>
              <p className="clause-text">{task.original_text}</p>
            </div>
            <div className="review-field">
              <span className="review-field-label">当时审查发现的风险：</span>
              {task.source_review_snapshot.risk_level}：{task.source_review_snapshot.reason}
            </div>
            <div className="review-field">
              <span className="review-field-label">律师意见（按时间顺序）：</span>
              <ol className="lawyer-instruction-list">
                {task.lawyer_instructions.map((text, i) => (
                  <li key={i}>{text}</li>
                ))}
              </ol>
            </div>
            <div className="hint-text">创建时间：{new Date(task.created_at).toLocaleString()}</div>

            <TaskActions
              task={task}
              onStart={onStart}
              onConfirm={onConfirm}
              onReject={onReject}
              onAbandon={onAbandon}
              busy={busyTaskId === task.task_id}
            />
          </li>
        ))}
      </ul>
    </section>
  );
}
