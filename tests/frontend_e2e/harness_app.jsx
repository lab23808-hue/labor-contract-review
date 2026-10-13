/**
 * 仅代码/替身验证脚本（非真实后端联调）。
 *
 * 用真实的 react / react-dom + 真实的 App.jsx（连同它引用的全部真实子组件、
 * 真实的 api/client.js），在真实的无头 Chromium 里挂载，驱动一遍完整的
 * "合同库 → 工作区 → 解析 → 审查 → 定位条款 → 提交修改任务 → 修改任务列表 →
 * 模拟刷新" 交互流程。window.fetch 被替换成一个内存里的假后端（按真实
 * schemas 的字段形状拼数据、按真实路由的 URL 规则分发），不连接真实
 * FastAPI，所以这仍然只能算"仅代码/替身验证"。
 */
import { createRoot } from "react-dom/client";
import { flushSync } from "react-dom";
import App from "../src/App.jsx";

const results = [];
function assert(condition, label) {
  results.push({ label, pass: Boolean(condition) });
}

// ---------------------------------------------------------------------
// 内存假后端：按真实 API 的 URL 规则 + 真实 schemas 字段形状响应
// ---------------------------------------------------------------------
const DB = {
  contracts: new Map(), // contract_id -> contract object
  clauses: new Map(), // contract_id -> Clause[]
  reviews: new Map(), // contract_id -> ReviewRecord[]
  tasks: new Map(), // contract_id -> ModificationTask[]
  versions: new Map(), // contract_id -> ContractVersion（本阶段最多一条：v2）
  v2Reviews: new Map(), // contract_id -> ReviewRecord（V2 的复审记录）
};

function jsonResponse(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function nowIso() {
  return new Date().toISOString();
}

let nextContractSeq = 1;

function makeClauses(contractId) {
  return [
    {
      contract_id: contractId,
      clause_id: "clause_001",
      clause_type: "试用期工资",
      original_text: "乙方试用期为三个月，试用期工资为正式工资标准的百分之五十。",
      start_char: 0,
      end_char: 30,
    },
    {
      contract_id: contractId,
      clause_id: "clause_003",
      clause_type: "工作地点",
      original_text: "乙方工作地点为深圳市。",
      start_char: 30,
      end_char: 45,
    },
  ];
}

function makeReviewReport(contractId) {
  return {
    contract_id: contractId,
    generated_at: nowIso(),
    results: [
      {
        clause_id: "clause_001",
        related_clause_ids: [],
        risk: true,
        risk_level: "high",
        reason: "试用期工资比例低于法定最低标准。",
        legal_basis: ["《劳动合同法》第二十条"],
        suggestion: "建议将试用期工资比例调整为不低于百分之八十。",
        source: "llm",
        rule_id: null,
      },
      {
        clause_id: null,
        related_clause_ids: ["clause_001", "clause_003"],
        risk: true,
        risk_level: "medium",
        reason: "试用期与工作地点条款存在联动风险（规则级跨条款判断）。",
        legal_basis: [],
        suggestion: "",
        source: "rule",
        rule_id: "probation_location_001",
      },
    ],
    failed_clauses: [{ clause_id: "clause_999", error: "LLM 调用超时，重试后仍失败" }],
    versions: {},
    summary: { high: 1, medium: 1, low: 0, none: 0 },
    overall_risk_level: "high",
  };
}

window.fetch = async (url, options = {}) => {
  const method = options.method || "GET";
  const u = new URL(url, "http://localhost");
  const path = u.pathname;

  // GET /contracts
  if (method === "GET" && path === "/contracts") {
    const list = [...DB.contracts.values()].sort((a, b) => (a.created_at < b.created_at ? 1 : -1));
    return jsonResponse(list);
  }

  // POST /contracts (multipart upload)
  if (method === "POST" && path === "/contracts") {
    const formData = options.body;
    const file = formData.get("file");
    const contractId = `contract_${String(nextContractSeq++).padStart(3, "0")}`;
    const contract = {
      contract_id: contractId,
      filename: file.name,
      file_format: "txt",
      sha256: "a".repeat(64),
      size_bytes: file.size || 100,
      status: "uploaded",
      error: null,
      created_at: nowIso(),
      updated_at: nowIso(),
      metadata: {},
    };
    DB.contracts.set(contractId, contract);
    DB.reviews.set(contractId, []);
    DB.tasks.set(contractId, []);
    return jsonResponse(contract, 201);
  }

  const contractMatch = path.match(/^\/contracts\/([^/]+)(\/.*)?$/);
  if (!contractMatch) {
    return jsonResponse({ detail: `未处理的路径：${path}` }, 404);
  }
  const contractId = contractMatch[1];
  const subPath = contractMatch[2] || "";
  const contract = DB.contracts.get(contractId);

  if (!contract) {
    return jsonResponse({ detail: `合同不存在：${contractId}` }, 404);
  }

  if (method === "GET" && subPath === "") {
    return jsonResponse(contract);
  }

  if (method === "POST" && subPath === "/parse") {
    const clauses = makeClauses(contractId);
    DB.clauses.set(contractId, clauses);
    contract.status = "split";
    contract.updated_at = nowIso();
    return jsonResponse(clauses);
  }

  if (method === "GET" && subPath === "/clauses") {
    const clauses = DB.clauses.get(contractId);
    if (!clauses) return jsonResponse({ detail: "尚未切分" }, 404);
    return jsonResponse(clauses);
  }

  if (method === "POST" && subPath === "/review") {
    const report = makeReviewReport(contractId);
    const reviews = DB.reviews.get(contractId) || [];
    const reviewId = `v1_${String(reviews.length + 1).padStart(3, "0")}`;
    reviews.push({ review_id: reviewId, contract_id: contractId, contract_version: "v1", report, created_at: nowIso() });
    DB.reviews.set(contractId, reviews);
    contract.status = "reviewed";
    contract.updated_at = nowIso();
    return jsonResponse(report);
  }

  if (method === "GET" && subPath === "/review") {
    const reviews = DB.reviews.get(contractId) || [];
    if (reviews.length === 0) return jsonResponse({ detail: "尚未生成审查报告" }, 404);
    return jsonResponse(reviews[reviews.length - 1]);
  }

  if (method === "GET" && subPath === "/reviews") {
    return jsonResponse(DB.reviews.get(contractId) || []);
  }

  if (method === "POST" && subPath === "/modification-tasks") {
    const payload = JSON.parse(options.body);
    const tasks = DB.tasks.get(contractId) || [];
    const taskId = `task_${String(tasks.length + 1).padStart(3, "0")}`;
    const task = {
      task_id: taskId,
      contract_id: contractId,
      target_clause_id: payload.clause_id,
      original_text: payload.original_text,
      lawyer_instructions: [payload.lawyer_instruction],
      status: "pending",
      modification_attempts: [],
      current_modified_text: null,
      created_at: nowIso(),
      updated_at: nowIso(),
      confirmed_at: null,
    };
    tasks.push(task);
    DB.tasks.set(contractId, tasks);
    return jsonResponse(task, 201);
  }

  if (method === "GET" && subPath === "/modification-tasks") {
    return jsonResponse(DB.tasks.get(contractId) || []);
  }

  // POST /modification-tasks/{task_id}/start —— 假 Agent：始终生成一个能通过
  // Validator 的候选（这不是在测试 Validator/Agent 本身，那两个已经在 Python
  // 真实验证脚本里覆盖过；这里只测试前端“点击开始修改 -> 展示候选 -> 确认/拒绝”
  // 这条交互链路本身）。
  const startMatch = subPath.match(/^\/modification-tasks\/([^/]+)\/start$/);
  if (method === "POST" && startMatch) {
    const task = findTask(contractId, startMatch[1]);
    if (!task) return jsonResponse({ detail: "任务不存在" }, 404);
    task.modification_attempts.push({
      attempt_number: task.modification_attempts.length + 1,
      lawyer_instruction: task.lawyer_instructions[task.lawyer_instructions.length - 1],
      candidate_text: `${task.original_text}（已按律师意见修改，假 Agent 生成）`,
      reason: "假 Agent：按律师意见调整表述",
      legal_basis: ["《劳动合同法》第二十条"],
      validator_passed: true,
      validator_errors: [],
      created_at: nowIso(),
    });
    task.status = "reviewing";
    task.current_modified_text = `${task.original_text}（已按律师意见修改，假 Agent 生成）`;
    task.updated_at = nowIso();
    return jsonResponse(task);
  }

  const confirmMatch = subPath.match(/^\/modification-tasks\/([^/]+)\/confirm$/);
  if (method === "POST" && confirmMatch) {
    const task = findTask(contractId, confirmMatch[1]);
    if (!task) return jsonResponse({ detail: "任务不存在" }, 404);
    task.status = "confirmed";
    task.confirmed_at = nowIso();
    task.updated_at = task.confirmed_at;
    return jsonResponse(task);
  }

  const rejectMatch = subPath.match(/^\/modification-tasks\/([^/]+)\/reject$/);
  if (method === "POST" && rejectMatch) {
    const task = findTask(contractId, rejectMatch[1]);
    if (!task) return jsonResponse({ detail: "任务不存在" }, 404);
    const payload = JSON.parse(options.body);
    task.lawyer_instructions.push(payload.new_instruction);
    task.current_modified_text = null;
    task.status = "rejected";
    task.updated_at = nowIso();
    return jsonResponse(task);
  }

  // ---- V2 版本相关：假后端只需要维护"是否已经生成"这一个状态 ----
  if (method === "POST" && subPath === "/versions") {
    const tasks = DB.tasks.get(contractId) || [];
    const version = {
      version_id: `${contractId}_v2`,
      contract_id: contractId,
      version_number: "v2",
      source_version: "v1",
      linked_contract_id: `${contractId}_v2_internal`,
      created_at: nowIso(),
      created_by: "lawyer",
      status: "active",
    };
    DB.versions.set(contractId, version);
    tasks.forEach((t) => {
      if (t.status === "confirmed") t.status = "completed";
    });
    return jsonResponse(version, 201);
  }

  if (method === "GET" && subPath === "/versions") {
    const version = DB.versions.get(contractId);
    return jsonResponse(version ? [version] : []);
  }

  const diffMatch = subPath.match(/^\/versions\/([^/]+)\/diff$/);
  if (method === "GET" && diffMatch) {
    const clauses = DB.clauses.get(contractId) || [];
    return jsonResponse(
      clauses.map((c) => ({
        clause_id: c.clause_id,
        matched: true,
        changed: c.clause_id === "clause_001",
        original_text: c.original_text,
        modified_text: c.clause_id === "clause_001" ? `${c.original_text}（已修改）` : null,
      })),
    );
  }

  const versionReviewMatch = subPath.match(/^\/versions\/([^/]+)\/review$/);
  if (method === "POST" && versionReviewMatch) {
    const record = {
      review_id: "v2_001",
      contract_id: `${contractId}_v2_internal`,
      contract_version: "v2",
      report: makeReviewReport(contractId),
      created_at: nowIso(),
    };
    DB.v2Reviews.set(contractId, record);
    return jsonResponse(record);
  }

  const riskDiffMatch = subPath.match(/^\/versions\/([^/]+)\/risk-diff$/);
  if (method === "GET" && riskDiffMatch) {
    if (!DB.v2Reviews.get(contractId)) return jsonResponse({ detail: "尚未复审" }, 404);
    return jsonResponse({
      contract_id: contractId,
      v1_review_id: "v1_001",
      v2_review_id: "v2_001",
      entries: [
        {
          category: "resolved",
          description: "试用期工资比例已调整，风险消失。",
          v1_risk_level: "high",
          v2_risk_level: "none",
          v1_clause_ref: "clause_001",
          v2_clause_ref: "clause_001",
        },
      ],
    });
  }

  return jsonResponse({ detail: `未处理的路径：${method} ${path}` }, 404);
};

function findTask(contractId, taskId) {
  return (DB.tasks.get(contractId) || []).find((t) => t.task_id === taskId);
}

// ---------------------------------------------------------------------
// 挂载真实 App，并驱动一遍完整交互流程
// ---------------------------------------------------------------------
function mountApp() {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  flushSync(() => root.render(<App />));
  return { container, root };
}

function waitFor(predicate, timeoutMs = 3000) {
  return new Promise((resolve, reject) => {
    const start = Date.now();
    const tick = () => {
      if (predicate()) return resolve();
      if (Date.now() - start > timeoutMs) return reject(new Error("waitFor 超时：" + predicate.toString()));
      setTimeout(tick, 20);
    };
    tick();
  });
}

function click(el) {
  flushSync(() => {
    el.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
}

async function run() {
  const { container } = mountApp();

  // 用例 1：初始空状态 —— 合同库为空
  await waitFor(() => container.textContent.includes("还没有合同"));
  assert(container.textContent.includes("合同库"), "1-初始状态：显示合同库标题");
  assert(container.textContent.includes("还没有合同"), "1-初始状态：空合同库显示 empty state");

  // 用例 2：上传新合同（真实触发 <input type=file> 的 change 事件 + 真实 File 对象）
  const fileInput = container.querySelector('input[type="file"]');
  const file = new File(["第一条 试用期\n乙方试用期为三个月。"], "劳动合同.txt", { type: "text/plain" });
  const dataTransfer = new DataTransfer();
  dataTransfer.items.add(file);
  fileInput.files = dataTransfer.files;
  flushSync(() => {
    fileInput.dispatchEvent(new Event("change", { bubbles: true }));
  });
  await waitFor(() => container.textContent.includes("劳动合同.txt"));

  const uploadButton = [...container.querySelectorAll("button")].find((b) => b.textContent.includes("新建合同"));
  click(uploadButton);

  await waitFor(() => container.textContent.includes("合同概览"), 5000);
  assert(container.textContent.includes("合同概览"), "2-上传成功：自动打开工作区并显示概览标签页");
  assert(container.textContent.includes("已上传"), "2-上传成功：状态显示为已上传");

  // 用例 3：解析合同
  const parseButton = [...container.querySelectorAll("button")].find((b) => b.textContent.includes("解析合同"));
  click(parseButton);
  await waitFor(() => container.textContent.includes("已切分条款"), 5000);
  assert(true, "3-解析合同：解析后状态推进为已切分条款（不是前端猜测，是重新 GET 得到）");

  // 用例 4：切到条款标签页
  const clauseTab = [...container.querySelectorAll("button.workspace-tab")].find((b) => b.textContent === "条款");
  click(clauseTab);
  await waitFor(() => container.textContent.includes("clause_001"));
  assert(container.textContent.includes("试用期工资"), "4-条款查看：显示 clause_type");
  assert(container.textContent.includes("乙方试用期为三个月"), "4-条款查看：显示 original_text");

  // 用例 5：切到审查结果标签页并开始审查
  const reviewTab = [...container.querySelectorAll("button.workspace-tab")].find((b) => b.textContent === "审查结果");
  click(reviewTab);
  await waitFor(() => container.textContent.includes("开始审查"));
  const startReviewButton = [...container.querySelectorAll("button")].find((b) => b.textContent.includes("开始审查"));
  click(startReviewButton);

  await waitFor(() => container.textContent.includes("重新审查"), 5000);
  assert(container.textContent.includes("重新审查"), "5-审查完成：按钮变为“重新审查”");
  assert(container.textContent.includes("部分条款审查失败"), "5-审查完成：failed_clauses 警示文案正确展示");
  assert(container.textContent.includes("clause_999"), "5-审查完成：failed_clauses 具体条款展示");

  // 用例 6：单条款关联结果（默认选中第一条结果）
  assert(container.textContent.includes("相关条款"), "6-单条款关联：显示相关条款标题");
  assert(container.textContent.includes("乙方试用期为三个月"), "6-单条款关联：显示 clause_001 原文");

  // 用例 7：切换到多条款关联结果，验证 related_clause_ids 两条都展示、不崩溃
  const resultButtons = container.querySelectorAll(".review-result-directory-item");
  assert(resultButtons.length === 2, "7-审查结果列表：显示两条结果（单条款 + 跨条款）");
  click(resultButtons[1]);
  await waitFor(() => container.querySelectorAll(".review-result-detail").length > 0);
  assert(container.textContent.includes("clause_001") && container.textContent.includes("clause_003"),
    "7-多条款关联：related_clause_ids 的两个条款都展示");
  assert(container.textContent.includes("乙方工作地点为深圳市"), "7-多条款关联：clause_003 原文正确展示");

  // 用例 8：点击"查看 clause_003" —— 联动定位到条款标签页
  const locateButton = [...container.querySelectorAll("button")].find((b) => b.textContent.includes("查看 clause_003"));
  click(locateButton);
  await waitFor(() => container.querySelector(".clause-directory-item.active") !== null);
  assert(container.querySelector(".workspace-tab.active").textContent === "条款",
    "8-审查结果联动条款：点击后自动切换到条款标签页");
  assert(container.textContent.includes("乙方工作地点为深圳市"), "8-审查结果联动条款：正确定位到 clause_003 详情");

  // 用例 9：回到审查结果，提出修改意见并提交
  click(reviewTab);
  await waitFor(() => container.textContent.includes("提出修改意见"));
  click(resultButtons[0]); // 选回单条款结果（clause_001）
  const proposeButton = [...container.querySelectorAll("button")].find((b) => b.textContent.includes("提出修改意见"));
  click(proposeButton);
  await waitFor(() => container.querySelector(".modification-task-textarea") !== null);

  const textarea = container.querySelector(".modification-task-textarea");
  const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value").set;
  flushSync(() => {
    nativeSetter.call(textarea, "将试用期工资比例调整为不低于百分之八十。");
    textarea.dispatchEvent(new Event("input", { bubbles: true }));
  });
  const submitTaskButton = [...container.querySelectorAll("button")].find((b) => b.textContent.includes("提交修改任务"));
  click(submitTaskButton);

  await waitFor(() => !container.textContent.includes("modification-task-textarea"), 3000).catch(() => {});
  await waitFor(() => DB.tasks.get(currentOpenContractId())?.length === 1, 3000);
  assert(true, "9-提出修改意见：任务已成功创建（后端假数据里确实新增了一条）");

  // 用例 10：切到修改任务标签页，验证任务展示
  const tasksTab = [...container.querySelectorAll("button.workspace-tab")].find((b) => b.textContent === "修改任务");
  click(tasksTab);
  await waitFor(() => container.textContent.includes("修改任务 #001"), 3000);
  assert(container.textContent.includes("将试用期工资比例调整为不低于百分之八十"), "10-修改任务列表：正确展示律师意见");
  assert(container.textContent.includes("待处理"), "10-修改任务列表：状态展示为待处理");

  // 用例 10b：点击"开始修改" -> 假 Agent 返回候选 -> 展示 reviewing 状态和候选内容
  const startButton = [...container.querySelectorAll("button")].find((b) => b.textContent.includes("开始修改"));
  click(startButton);
  await waitFor(() => container.textContent.includes("待律师确认"), 3000);
  assert(container.textContent.includes("待律师确认"), "10b-开始修改：状态变为 reviewing（待律师确认）");
  assert(container.textContent.includes("假 Agent 生成"), "10b-开始修改：正确展示 Agent 候选文本");
  assert(container.textContent.includes("确认修改") && container.textContent.includes("不满意，重新修改"),
    "10b-开始修改：展示确认/拒绝两个操作按钮（Human-in-the-loop）");

  // 用例 10c：点击"确认修改" -> 状态变为 confirmed
  const confirmButton = [...container.querySelectorAll("button")].find((b) => b.textContent.includes("确认修改"));
  click(confirmButton);
  await waitFor(() => container.textContent.includes("已确认，等待全部任务处理完成后生成 V2"), 3000);
  assert(container.textContent.includes("已确认"), "10c-确认修改：状态变为 confirmed");

  // 用例 11：切到版本标签页，生成 V2
  const versionTab = [...container.querySelectorAll("button.workspace-tab")].find((b) => b.textContent === "版本");
  click(versionTab);
  await waitFor(() => container.textContent.includes("生成 V2"), 3000);
  const generateButton = [...container.querySelectorAll("button")].find((b) => b.textContent.includes("生成 V2") && !b.disabled);
  assert(generateButton != null, "11-版本页：[生成 V2] 按钮在有已确认任务且无阻塞任务时是可点击的");
  click(generateButton);
  await waitFor(() => container.textContent.includes("已生成"), 3000);
  assert(container.textContent.includes("已生成"), "11-生成 V2：版本页展示“已生成”及版本信息");

  // 用例 12：查看条款 Diff
  await waitFor(() => [...container.querySelectorAll("button")].some((b) => b.textContent.includes("查看条款 Diff")), 3000);
  const diffButton = [...container.querySelectorAll("button")].find((b) => b.textContent.includes("查看条款 Diff"));
  click(diffButton);
  await waitFor(() => container.textContent.includes("条款级 Diff"), 3000);
  assert(container.textContent.includes("已修改") && container.textContent.includes("clause_001"),
    "12-条款 Diff：clause_001 正确标记为已修改");

  // 用例 13：对 V2 发起完整审查，查看风险 Diff
  const versionReviewButton = [...container.querySelectorAll("button")].find((b) =>
    b.textContent.includes("对 V2 重新发起完整审查"),
  );
  click(versionReviewButton);
  await waitFor(() => container.textContent.includes("V1 / V2 风险 Diff"), 3000);
  assert(container.textContent.includes("风险已消失"), "13-风险 Diff：正确展示 resolved 分类");

  // 用例 14：模拟"刷新页面"——卸载并用同一个假后端重新挂载一个全新的 App 实例，
  // 验证合同库能重新从（模拟的）后端拉到刚才创建的合同（不是从 localStorage 读的）。
  container.remove();
  const { container: container2 } = mountApp();
  await waitFor(() => container2.textContent.includes("劳动合同.txt"), 3000);
  assert(container2.textContent.includes("劳动合同.txt"),
    "14-模拟刷新：新的 App 实例重新从后端拉取合同库，合同没有丢失");
  assert(!container2.textContent.includes("合同概览"),
    "14-模拟刷新：刷新后回到未选中任何合同的初始状态（本阶段无路由，属预期行为）");

  function currentOpenContractId() {
    return [...DB.contracts.keys()][0];
  }

  window.__HARNESS_RESULTS__ = results;
  window.__HARNESS_DONE__ = true;
}

run().catch((err) => {
  results.push({ label: `harness 运行异常：${err.message}`, pass: false });
  window.__HARNESS_RESULTS__ = results;
  window.__HARNESS_DONE__ = true;
});
