/**
 * API Client：唯一负责和后端 FastAPI 通信的地方。
 *
 * 职责边界（硬约束）：
 *   - 只做 HTTP 请求/响应处理，不包含任何业务判断（不猜测 status、
 *     不重新计算风险等级、不解析文件内容）。
 *   - 所有组件都不直接调用 fetch，只通过这里导出的函数。
 *   - API 地址只在这一个文件里拼，不散落到各个组件里。
 */

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

/**
 * 把后端的错误响应统一转换成一条可以直接展示的字符串。
 *
 * FastAPI 的错误响应通常是 { detail: "具体错误信息" }（字符串），
 * 但 FastAPI 自带的 422 请求校验错误是
 *   { detail: [ { loc: [...], msg: "Field required", type: "missing" }, ... ] }
 * （数组）。这里必须分别处理，不能直接 String(detail)，
 * 否则数组会被渲染成 "[object Object]"。
 */
function normalizeErrorDetail(detail) {
  if (typeof detail === "string" && detail.length > 0) {
    return detail;
  }
  if (Array.isArray(detail)) {
    if (detail.length > 0 && detail[0] && typeof detail[0].msg === "string") {
      return detail[0].msg;
    }
    return "请求参数有误";
  }
  return "未知错误";
}

/**
 * 统一处理 fetch 的 Response：
 *   - 成功（2xx）：返回解析后的 JSON。
 *   - 失败：尽量读出 { detail } 并转换成统一格式的 Error，
 *     Error.message 已经是 "操作失败：xxxx" 这种可以直接展示的文本。
 */
async function handleResponse(response) {
  if (response.ok) {
    // 204 等无内容响应，避免 JSON 解析报错
    if (response.status === 204) {
      return null;
    }
    return response.json();
  }

  let detailText = "未知错误";
  try {
    const body = await response.json();
    detailText = normalizeErrorDetail(body?.detail);
  } catch {
    // 响应体不是合法 JSON（例如网关错误页面），保留默认文案
  }

  throw new Error(`操作失败：${detailText}`);
}

/** 网络本身失败（连不上后端、CORS 被拒绝等）时，统一转换成同样格式的 Error。 */
function wrapNetworkError(error) {
  if (error instanceof Error && error.message.startsWith("操作失败：")) {
    return error;
  }
  return new Error("操作失败：无法连接后端服务，请确认后端已启动");
}

/** POST /contracts —— 上传合同文件，创建一份新的合同记录。 */
export async function createContract(file) {
  const formData = new FormData();
  formData.append("file", file);

  try {
    // 注意：不要手动设置 Content-Type，交给浏览器自动带上 multipart 的 boundary。
    const response = await fetch(`${API_BASE_URL}/contracts`, {
      method: "POST",
      body: formData,
    });
    return await handleResponse(response);
  } catch (error) {
    throw wrapNetworkError(error);
  }
}

/** GET /contracts/{contract_id} —— 查询合同当前的元数据（状态以后端为准）。 */
export async function getContract(contractId) {
  try {
    const response = await fetch(`${API_BASE_URL}/contracts/${contractId}`);
    return await handleResponse(response);
  } catch (error) {
    throw wrapNetworkError(error);
  }
}

/** POST /contracts/{contract_id}/parse —— 解析并切分合同，返回 Clause 列表。 */
export async function parseContract(contractId) {
  try {
    const response = await fetch(`${API_BASE_URL}/contracts/${contractId}/parse`, {
      method: "POST",
    });
    return await handleResponse(response);
  } catch (error) {
    throw wrapNetworkError(error);
  }
}

/** GET /contracts/{contract_id}/clauses —— 读取已保存的 Clause 列表。 */
export async function getClauses(contractId) {
  try {
    const response = await fetch(`${API_BASE_URL}/contracts/${contractId}/clauses`);
    return await handleResponse(response);
  } catch (error) {
    throw wrapNetworkError(error);
  }
}

/** POST /contracts/{contract_id}/review —— 发起一次完整审查，返回 ReviewReport（后端已持久化）。 */
export async function reviewContract(contractId) {
  try {
    const response = await fetch(`${API_BASE_URL}/contracts/${contractId}/review`, {
      method: "POST",
    });
    return await handleResponse(response);
  } catch (error) {
    throw wrapNetworkError(error);
  }
}

/** GET /contracts —— 合同库列表。 */
export async function listContracts() {
  try {
    const response = await fetch(`${API_BASE_URL}/contracts`);
    return await handleResponse(response);
  } catch (error) {
    throw wrapNetworkError(error);
  }
}

/**
 * GET /contracts/{contract_id}/review —— 最近一次审查记录（ReviewRecord）。
 *
 * 合同从未审查过时后端返回 404，这是正常状态（"还没审查过"），不是错误，
 * 所以这里不复用 handleResponse 的"非 2xx 一律抛错"逻辑，而是把 404
 * 翻译成 null，交给调用方决定怎么展示"尚未审查"这个状态。
 */
export async function getLatestReviewOrNull(contractId) {
  try {
    const response = await fetch(`${API_BASE_URL}/contracts/${contractId}/review`);
    if (response.status === 404) {
      return null;
    }
    return await handleResponse(response);
  } catch (error) {
    throw wrapNetworkError(error);
  }
}

/** GET /contracts/{contract_id}/reviews —— 全部历史审查记录（按时间顺序）。 */
export async function listReviews(contractId) {
  try {
    const response = await fetch(`${API_BASE_URL}/contracts/${contractId}/reviews`);
    return await handleResponse(response);
  } catch (error) {
    throw wrapNetworkError(error);
  }
}

/**
 * GET /contracts/{contract_id}/text —— 读取某份合同已保存的完整解析文本。
 *
 * 通用接口，不区分 V1/V2：调用方传谁的 contract_id，就读谁的原文——
 * "V2 原文"标签页会传 version.linked_contract_id，不是家族 contractId。
 * 返回体是 { contract_id, text }，这里按字段名取 text，不假设后端直接
 * 返回裸字符串。
 */
export async function getParsedText(contractId) {
  try {
    const response = await fetch(`${API_BASE_URL}/contracts/${contractId}/text`);
    const data = await handleResponse(response);
    return data.text;
  } catch (error) {
    throw wrapNetworkError(error);
  }
}

/**
 * GET /contracts/{contract_id}/clauses —— 读取已保存的 Clause 列表。
 *
 * 合同还没解析过时后端返回 404，这同样是正常状态，不是错误——打开一份
 * "已上传但未解析"的合同时，条款列表本来就应该是空的，不需要给用户看
 * 一条错误提示。
 */
export async function getClausesOrNull(contractId) {
  try {
    const response = await fetch(`${API_BASE_URL}/contracts/${contractId}/clauses`);
    if (response.status === 404) {
      return null;
    }
    return await handleResponse(response);
  } catch (error) {
    throw wrapNetworkError(error);
  }
}

/**
 * POST /contracts/{contract_id}/modification-batches —— 律师显式"开始一轮
 * 修改"，依据某一次审查记录（sourceReviewId）创建一个新批次，返回 batch_id。
 */
export async function createModificationBatch(contractId, sourceReviewId) {
  try {
    const response = await fetch(`${API_BASE_URL}/contracts/${contractId}/modification-batches`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source_review_id: sourceReviewId }),
    });
    return await handleResponse(response);
  } catch (error) {
    throw wrapNetworkError(error);
  }
}

/** GET /contracts/{contract_id}/modification-batches —— 当前合同的全部修改批次。 */
export async function listModificationBatches(contractId) {
  try {
    const response = await fetch(`${API_BASE_URL}/contracts/${contractId}/modification-batches`);
    return await handleResponse(response);
  } catch (error) {
    throw wrapNetworkError(error);
  }
}

/** GET /contracts/{contract_id}/modification-batches/{batch_id} —— 单个批次的最新状态。 */
export async function getModificationBatch(contractId, batchId) {
  try {
    const response = await fetch(`${API_BASE_URL}/contracts/${contractId}/modification-batches/${batchId}`);
    return await handleResponse(response);
  } catch (error) {
    throw wrapNetworkError(error);
  }
}

/**
 * POST /contracts/{contract_id}/modification-tasks —— 创建一条修改任务（律师意见）。
 * batchId 是必填字段：任务必须显式归属一个已经创建好的批次。original_text
 * 不再由前端提交——后端会从 ContractManager 用 contract_id + clause_id
 * 服务端查出真实原文，前端传了也会被忽略。
 */
export async function createModificationTask(contractId, { batchId, clauseId, lawyerInstruction }) {
  try {
    const response = await fetch(`${API_BASE_URL}/contracts/${contractId}/modification-tasks`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        batch_id: batchId,
        clause_id: clauseId,
        lawyer_instruction: lawyerInstruction,
      }),
    });
    return await handleResponse(response);
  } catch (error) {
    throw wrapNetworkError(error);
  }
}

/** GET /contracts/{contract_id}/modification-tasks —— 当前合同的全部修改任务。 */
export async function listModificationTasks(contractId) {
  try {
    const response = await fetch(`${API_BASE_URL}/contracts/${contractId}/modification-tasks`);
    return await handleResponse(response);
  } catch (error) {
    throw wrapNetworkError(error);
  }
}

/**
 * POST /contracts/{contract_id}/modification-tasks/{task_id}/start
 * 发起（或重新发起）一轮 Modification Agent 调用，返回更新后的 ModificationTask。
 */
export async function startModificationTask(contractId, taskId) {
  try {
    const response = await fetch(
      `${API_BASE_URL}/contracts/${contractId}/modification-tasks/${taskId}/start`,
      { method: "POST" },
    );
    return await handleResponse(response);
  } catch (error) {
    throw wrapNetworkError(error);
  }
}

/**
 * POST .../modification-tasks/{task_id}/confirm —— 律师确认结果。
 * waiting_confirmation 状态下确认当前候选（manualText 留空/undefined）；
 * needs_human 状态下必须传入 manualText（律师手工确定的最终文本）。
 */
export async function confirmModificationTask(contractId, taskId, manualText) {
  try {
    const response = await fetch(
      `${API_BASE_URL}/contracts/${contractId}/modification-tasks/${taskId}/confirm`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ manual_text: manualText ?? null }),
      },
    );
    return await handleResponse(response);
  } catch (error) {
    throw wrapNetworkError(error);
  }
}

/** POST .../modification-tasks/{task_id}/abandon —— 律师明确放弃这条修改任务（不再重试）。 */
export async function abandonModificationTask(contractId, taskId) {
  try {
    const response = await fetch(
      `${API_BASE_URL}/contracts/${contractId}/modification-tasks/${taskId}/abandon`,
      { method: "POST" },
    );
    return await handleResponse(response);
  } catch (error) {
    throw wrapNetworkError(error);
  }
}

/** POST .../modification-tasks/{task_id}/reject —— 律师拒绝当前候选，附带新的修改意见。 */
export async function rejectModificationTask(contractId, taskId, newInstruction) {
  try {
    const response = await fetch(
      `${API_BASE_URL}/contracts/${contractId}/modification-tasks/${taskId}/reject`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ new_instruction: newInstruction }),
      },
    );
    return await handleResponse(response);
  } catch (error) {
    throw wrapNetworkError(error);
  }
}

/** POST /contracts/{contract_id}/versions —— 生成 V2（以 batchId 指定的批次为单位）。 */
export async function generateVersion(contractId, batchId) {
  try {
    const response = await fetch(`${API_BASE_URL}/contracts/${contractId}/versions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ batch_id: batchId }),
    });
    return await handleResponse(response);
  } catch (error) {
    throw wrapNetworkError(error);
  }
}

/**
 * GET /contracts/{contract_id}/versions —— 列出全部非 V1 版本（本阶段最多一条：v2）。
 * 合同还没有生成过 V2 时后端返回空列表，不是错误。
 */
export async function listVersions(contractId) {
  try {
    const response = await fetch(`${API_BASE_URL}/contracts/${contractId}/versions`);
    return await handleResponse(response);
  } catch (error) {
    throw wrapNetworkError(error);
  }
}

/** GET /contracts/{contract_id}/versions/{version}/diff —— 条款级 V1/V2 Diff。 */
export async function getClauseDiff(contractId, versionNumber = "v2") {
  try {
    const response = await fetch(`${API_BASE_URL}/contracts/${contractId}/versions/${versionNumber}/diff`);
    return await handleResponse(response);
  } catch (error) {
    throw wrapNetworkError(error);
  }
}

/** POST /contracts/{contract_id}/versions/{version}/review —— 对 V2 发起一次完全独立的复审。 */
export async function runVersionReview(contractId, versionNumber = "v2") {
  try {
    const response = await fetch(
      `${API_BASE_URL}/contracts/${contractId}/versions/${versionNumber}/review`,
      { method: "POST" },
    );
    return await handleResponse(response);
  } catch (error) {
    throw wrapNetworkError(error);
  }
}

/**
 * GET /contracts/{contract_id}/versions/{version}/risk-diff —— V1/V2 风险 Diff。
 * V2 还没有复审过时后端返回 404，这是正常状态（"还没点过重新审查"），
 * 所以这里同样把 404 翻译成 null，交给调用方决定怎么展示。
 */
export async function getRiskDiffOrNull(contractId, versionNumber = "v2") {
  try {
    const response = await fetch(`${API_BASE_URL}/contracts/${contractId}/versions/${versionNumber}/risk-diff`);
    if (response.status === 404) {
      return null;
    }
    return await handleResponse(response);
  } catch (error) {
    throw wrapNetworkError(error);
  }
}

/**
 * POST /contracts/{contract_id}/qa —— 最小化自然语言问答：提一个关于这份
 * 合同的问题，返回一段纯文本回答（{ answer: "..." }）。
 */
export async function askQuestion(contractId, question) {
  try {
    const response = await fetch(`${API_BASE_URL}/contracts/${contractId}/qa`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });
    return await handleResponse(response);
  } catch (error) {
    throw wrapNetworkError(error);
  }
}
