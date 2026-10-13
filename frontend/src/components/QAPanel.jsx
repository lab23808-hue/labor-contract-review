import { useState } from "react";

/**
 * QAPanel："问答" 标签页：对这份合同提一个自然语言问题，展示后端
 * QAApplicationService 返回的纯文本回答。
 *
 * 本组件不做任何本地的"猜答案"逻辑——问题原样提交给后端，回答原样展示，
 * 和后端"收集数据 -> 拼 Prompt -> 一次 LLM 调用 -> 返回纯文本"的最小化
 * 实现保持一致，前端不额外加工。
 */
export default function QAPanel({ onAsk, asking, lastAnswer, lastQuestion }) {
  const [question, setQuestion] = useState("");

  function handleAsk() {
    const trimmed = question.trim();
    if (!trimmed || asking) return;
    onAsk(trimmed);
  }

  return (
    <section className="card">
      <h2>问答</h2>
      <p className="hint-text">
        就这份合同向助手提问，例如"这份合同现在还有哪些高风险？""clause_003 改了什么？""V2 复审结果怎么样？"。
        回答只依据这份合同已经产生的数据（条款、审查结果、修改任务、V2 等），不会编造数据之外的信息。
      </p>
      <textarea
        className="modification-task-textarea"
        placeholder="请输入你的问题"
        value={question}
        onChange={(e) => setQuestion(e.target.value)}
        disabled={asking}
        rows={3}
      />
      <div className="modification-task-form-actions">
        <button type="button" onClick={handleAsk} disabled={!question.trim() || asking}>
          {asking ? "思考中..." : "提问"}
        </button>
      </div>

      {lastAnswer && (
        <div className="qa-answer-box">
          <div className="review-field">
            <span className="review-field-label">问题：</span>
            {lastQuestion}
          </div>
          <div className="review-field">
            <span className="review-field-label">回答：</span>
            <p className="clause-text">{lastAnswer}</p>
          </div>
        </div>
      )}
    </section>
  );
}
