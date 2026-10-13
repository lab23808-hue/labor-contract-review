import { useState } from "react";

/**
 * ModificationTaskForm：律师针对某个条款提出修改意见的输入区域。
 * 本阶段只负责"提交一条修改任务"，不做任何生成、不调用任何 LLM、
 * 不修改合同正文——提交成功后只是新增一条 status=pending 的 ModificationTask。
 */
export default function ModificationTaskForm({ clauseId, originalText, onSubmit, onCancel, submitting, disabled, disabledHint }) {
  const [instruction, setInstruction] = useState("");

  function handleSubmit() {
    const trimmed = instruction.trim();
    if (!trimmed || submitting || disabled) return; // 防止空提交、防止重复提交、没有批次时禁止提交
    onSubmit(trimmed);
  }

  return (
    <div className="modification-task-form">
      <div className="modification-task-form-title">对 {clauseId} 提出修改意见</div>

      <div className="modification-task-form-original">
        <div className="hint-text">原条款：</div>
        <p className="clause-text">{originalText}</p>
      </div>

      {disabled && disabledHint && <p className="hint-text">{disabledHint}</p>}

      <textarea
        className="modification-task-textarea"
        placeholder="请输入修改意见，例如：将试用期调整为两个月。"
        value={instruction}
        onChange={(e) => setInstruction(e.target.value)}
        disabled={submitting}
        rows={3}
      />

      <div className="modification-task-form-actions">
        <button type="button" onClick={handleSubmit} disabled={!instruction.trim() || submitting || disabled}>
          {submitting ? "提交中..." : "提交修改任务"}
        </button>
        <button type="button" className="secondary-button" onClick={onCancel} disabled={submitting}>
          取消
        </button>
      </div>
    </div>
  );
}
