import { useEffect, useRef, useState } from "react";
import ContractLibrary from "./components/ContractLibrary.jsx";
import ContractWorkspace from "./components/ContractWorkspace.jsx";
import {
  abandonModificationTask,
  askQuestion,
  confirmModificationTask,
  createContract,
  createModificationBatch,
  createModificationTask,
  generateVersion,
  getClauseDiff,
  getClausesOrNull,
  getContract,
  getLatestReviewOrNull,
  getParsedText,
  getRiskDiffOrNull,
  listContracts,
  listModificationBatches,
  listModificationTasks,
  listReviews,
  listVersions,
  parseContract,
  rejectModificationTask,
  reviewContract,
  runVersionReview,
  startModificationTask,
} from "./api/client.js";

/**
 * App：拥有整个应用的顶层状态，是唯一调用后端 API 的地方（子组件都只通过
 * props 拿数据、通过回调触发动作，不直接 fetch）。
 *
 * 核心状态：
 *   contracts           —— 合同库列表
 *   currentContract     —— 当前打开的合同（Contract | null）
 *   clauses             —— 当前合同的条款列表（Clause[] | null，null 表示还没解析）
 *   reviewRecord         —— 当前合同最近一次审查记录（ReviewRecord | null）
 *   reviewHistoryCount  —— 当前合同的历史审查次数（"版本"标签页展示用）
 *   modificationTasks   —— 当前合同的修改任务列表
 *   activeView          —— 工作区当前标签页
 *   selectedClauseId    —— "条款"标签页当前选中的条款
 *   loading             —— 各类异步操作的进行中标记
 *   error               —— 全局错误提示（"操作失败：xxxx"）
 *
 * 页面刷新行为：合同库和审查结果现在都已经持久化在后端，所以刷新页面后
 * 会重新从 GET /contracts 拉取合同库；但"当前打开的是哪份合同"这件事
 * 本身没有存到 URL 或 localStorage 里（本阶段不引入路由），所以刷新后
 * 会回到"未选中任何合同"的初始状态，需要重新点击合同——这是本阶段的
 * 正常行为，不是 bug；合同本身和它的审查结果不会丢失。
 */
export default function App() {
  const [contracts, setContracts] = useState([]);
  const [contractsLoading, setContractsLoading] = useState(true);

  const [currentContract, setCurrentContract] = useState(null);
  const [clauses, setClauses] = useState(null);
  const [reviewRecord, setReviewRecord] = useState(null);
  const [reviewHistoryCount, setReviewHistoryCount] = useState(0);
  const [modificationTasks, setModificationTasks] = useState([]);

  // 当前批次（ModificationBatch）：取这份合同最近一次创建的批次（如果有）。
  // 每条新任务都必须显式携带这个 batch_id——本阶段前端只维护"最近一个批次"
  // 这一种最简单的场景，不支持在界面上切换查看历史批次。
  const [currentBatch, setCurrentBatch] = useState(null);
  const [startBatchLoading, setStartBatchLoading] = useState(false);

  // 问答（QA）标签页专用状态：只保留"最近一次问答"，不维护多轮历史。
  const [asking, setAsking] = useState(false);
  const [lastAnswer, setLastAnswer] = useState(null);
  const [lastQuestion, setLastQuestion] = useState(null);

  // V2 相关状态："版本"标签页专用，和 V1 的 reviewRecord/reviewHistoryCount 分开放，
  // 避免把两个版本的数据混在同一组 state 里。
  const [version, setVersion] = useState(null);
  const [versionsLoading, setVersionsLoading] = useState(false);
  const [generateVersionLoading, setGenerateVersionLoading] = useState(false);
  const [diffEntries, setDiffEntries] = useState(null);
  const [diffLoading, setDiffLoading] = useState(false);
  const [riskDiff, setRiskDiff] = useState(null);
  const [riskDiffLoading, setRiskDiffLoading] = useState(false);
  const [versionReviewLoading, setVersionReviewLoading] = useState(false);

  // V2 自己的完整审查结果（阶段 02 新增）：和 riskDiff/diffEntries 是两件不同的
  // 事——riskDiff/diffEntries 是"V1 对比 V2"的派生视图，v2ReviewRecord 才是
  // V2 自己的 ReviewRecord 本身（含完整 ReviewReport）。三者分开存放，互不
  // 覆盖。v2ReviewError 只在"查询这条记录本身失败"（网络错误/非 404 的后端
  // 错误）时才会有值；"V2 还没有被审查过"是 v2ReviewRecord === null 且
  // v2ReviewError === null 的正常状态，两者不能混为一谈。
  const [v2ReviewRecord, setV2ReviewRecord] = useState(null);
  const [v2ReviewError, setV2ReviewError] = useState(null);

  // V2 原文（阶段 1 新增）：只在用户点开"V2 原文"标签时才按需加载（不像
  // v2ReviewRecord 那样跟着 handleOpenContract 一起预先恢复），避免每次
  // 打开合同都去读一遍可能很长的全文。同样和 v2ReviewRecord/riskDiff 等
  // 分开存放，互不覆盖；同样区分"查询失败"（v2TextError）和"还没加载过"
  // （v2Text === null 且 v2TextError === null）。
  const [v2Text, setV2Text] = useState(null);
  const [v2TextLoading, setV2TextLoading] = useState(false);
  const [v2TextError, setV2TextError] = useState(null);

  const [activeView, setActiveView] = useState("overview");
  const [selectedClauseId, setSelectedClauseId] = useState(null);

  const [workspaceLoading, setWorkspaceLoading] = useState(false);
  const [uploadLoading, setUploadLoading] = useState(false);
  const [parseLoading, setParseLoading] = useState(false);
  const [reviewLoading, setReviewLoading] = useState(false);
  const [taskSubmitting, setTaskSubmitting] = useState(false);
  const [busyTaskId, setBusyTaskId] = useState(null);

  const [error, setError] = useState(null);

  // 合同切换时的异步竞态保护：handleOpenContract 每次调用都领一个新的
  // requestId；它发出的所有异步请求回来之后，先检查自己领到的 requestId
  // 是不是还是"最新一次打开合同"的那个——如果用户在请求还没回来之前又点开
  // 了别的合同（甚至同一份合同触发的后续动作，例如"重新发起 V2 复审"），
  // ref 会被新的调用再次递增，旧请求的结果就不再写入任何 state，避免旧
  // 合同的数据覆盖新合同已经显示的内容。
  const openRequestRef = useRef(0);

  async function refreshContractLibrary() {
    setContractsLoading(true);
    try {
      const list = await listContracts();
      setContracts(list);
    } catch (err) {
      setError(err.message);
    } finally {
      setContractsLoading(false);
    }
  }

  useEffect(() => {
    refreshContractLibrary();
    // 只在应用启动时拉取一次；后续的刷新在上传/解析/审查等动作完成后按需触发。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function handleOpenContract(contractId) {
    const requestId = ++openRequestRef.current;
    setError(null);
    setWorkspaceLoading(true);
    setActiveView("overview");
    setSelectedClauseId(null);
    // 切换合同时清空上一份合同的"版本"标签页衍生状态（Diff/风险 Diff/V2 的
    // 完整审查结果都是按需加载或恢复的，不属于"打开合同就立刻确定"的数据，
    // 避免把上一份合同的结果错误地残留展示在新打开的合同下面）。
    setDiffEntries(null);
    setRiskDiff(null);
    setV2ReviewRecord(null);
    setV2ReviewError(null);
    setV2Text(null);
    setV2TextError(null);
    setLastAnswer(null);
    setLastQuestion(null);
    try {
      const [contract, contractClauses, latestReview, reviews, tasks, versions, batches] = await Promise.all([
        getContract(contractId),
        getClausesOrNull(contractId),
        getLatestReviewOrNull(contractId),
        listReviews(contractId),
        listModificationTasks(contractId),
        listVersions(contractId),
        listModificationBatches(contractId),
      ]);
      // 这一批请求回来的时候，用户可能已经点开了别的合同——那次更晚的调用
      // 会把 openRequestRef 再往前推一格，这里发现自己不是最新请求就直接
      // 放弃，不写入任何 state。
      if (openRequestRef.current !== requestId) return;

      const v2Version = versions.find((v) => v.version_number === "v2") || null;

      // V2 的完整审查结果恢复：只有存在 V2 版本时才去查，查询对象是
      // ContractVersion.linked_contract_id（V2 真正的数据宿主），不是这里
      // 的家族 contractId——这是阶段 02 分析阶段确认过的、无需新增后端接口
      // 的复用方式。getLatestReviewOrNull 对 404（“这个 contract_id 还没有
      // 审查记录”）统一转成 null，由于 v2Version.linked_contract_id 本身
      // 必然是一个真实存在的 Contract（V2GenerationService 生成时创建），
      // 这里拿到 null 只会是"V2 还没被复审过"这一种含义，不会被误判为
      // "合同不存在"。其余异常（网络错误、5xx 等）会被抛出，落到下面的
      // catch 分支里单独记录到 v2ReviewError，和"尚未审查"严格区分开，不
      // 会被当成"没有审查记录"展示。
      let v2Review = null;
      let v2Error = null;
      if (v2Version) {
        try {
          v2Review = await getLatestReviewOrNull(v2Version.linked_contract_id);
        } catch (err) {
          v2Error = err.message;
        }
        // 这一次额外请求期间，用户也可能已经切换到了别的合同，同样需要
        // 再检查一次再写 state。
        if (openRequestRef.current !== requestId) return;
      }

      setCurrentContract(contract);
      setClauses(contractClauses);
      setReviewRecord(latestReview);
      setReviewHistoryCount(reviews.length);
      setModificationTasks(tasks);
      setVersion(v2Version);
      // 本阶段只维护"最近一个批次"：取按创建顺序排列的最后一个。
      setCurrentBatch(batches.length > 0 ? batches[batches.length - 1] : null);
      setV2ReviewRecord(v2Review);
      setV2ReviewError(v2Error);
    } catch (err) {
      if (openRequestRef.current === requestId) {
        setError(err.message);
      }
    } finally {
      if (openRequestRef.current === requestId) {
        setWorkspaceLoading(false);
      }
    }
  }

  async function handleUpload(file) {
    setError(null);
    setUploadLoading(true);
    try {
      const created = await createContract(file);
      await refreshContractLibrary();
      await handleOpenContract(created.contract_id);
    } catch (err) {
      setError(err.message);
    } finally {
      setUploadLoading(false);
    }
  }

  async function handleParse() {
    if (!currentContract) return;
    setError(null);
    setParseLoading(true);
    try {
      const contractId = currentContract.contract_id;
      const parsedClauses = await parseContract(contractId);
      setClauses(parsedClauses);
      // 硬约束：不自己猜测 status，重新 GET 一次合同，以后端返回的数据为准。
      const refreshedContract = await getContract(contractId);
      setCurrentContract(refreshedContract);
      await refreshContractLibrary(); // 合同库里的状态标签也要跟着更新
      setActiveView("clauses");
    } catch (err) {
      setError(err.message);
    } finally {
      setParseLoading(false);
    }
  }

  async function handleReview() {
    if (!currentContract) return;
    setError(null);
    setReviewLoading(true);
    try {
      const contractId = currentContract.contract_id;
      await reviewContract(contractId); // 后端已持久化，这里不直接使用返回值
      const [latestReview, reviews, refreshedContract] = await Promise.all([
        getLatestReviewOrNull(contractId),
        listReviews(contractId),
        getContract(contractId),
      ]);
      setReviewRecord(latestReview);
      setReviewHistoryCount(reviews.length);
      setCurrentContract(refreshedContract);
      await refreshContractLibrary();
    } catch (err) {
      setError(err.message);
    } finally {
      setReviewLoading(false);
    }
  }

  function handleLocateClause(clauseId) {
    setSelectedClauseId(clauseId);
    setActiveView("clauses");
  }

  async function handleStartBatch(sourceReviewId) {
    if (!currentContract || !sourceReviewId) return;
    setError(null);
    setStartBatchLoading(true);
    try {
      const batch = await createModificationBatch(currentContract.contract_id, sourceReviewId);
      setCurrentBatch(batch);
    } catch (err) {
      setError(err.message);
    } finally {
      setStartBatchLoading(false);
    }
  }

  async function handleCreateModificationTask({ clauseId, lawyerInstruction }) {
    if (!currentContract) return;
    if (!currentBatch) {
      setError("操作失败：还没有开启一轮修改，请先在“版本”标签页点击“开始一轮修改”。");
      return;
    }
    setError(null);
    setTaskSubmitting(true);
    try {
      const contractId = currentContract.contract_id;
      await createModificationTask(contractId, { batchId: currentBatch.batch_id, clauseId, lawyerInstruction });
      const [tasks, batch] = await Promise.all([
        listModificationTasks(contractId),
        listModificationBatches(contractId),
      ]);
      setModificationTasks(tasks);
      setCurrentBatch(batch.find((b) => b.batch_id === currentBatch.batch_id) || currentBatch);
    } catch (err) {
      setError(err.message);
    } finally {
      setTaskSubmitting(false);
    }
  }

  /**
   * 修改任务的三个推进动作（开始修改/确认/拒绝）共用同一套刷新逻辑：
   * 调用对应的 Service 接口 -> 用返回的最新 ModificationTask 替换列表里的旧值。
   * 不重新拉取整份列表，是因为这三个动作本身已经返回了更新后的单条任务，
   * 没必要为了刷新一条数据再发一次 GET。
   */
  function _replaceTask(updatedTask) {
    setModificationTasks((prev) => prev.map((t) => (t.task_id === updatedTask.task_id ? updatedTask : t)));
  }

  async function handleStartModification(taskId) {
    if (!currentContract) return;
    setError(null);
    setBusyTaskId(taskId);
    try {
      const updated = await startModificationTask(currentContract.contract_id, taskId);
      _replaceTask(updated);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusyTaskId(null);
    }
  }

  async function handleConfirmModification(taskId, manualText) {
    if (!currentContract) return;
    setError(null);
    setBusyTaskId(taskId);
    try {
      const updated = await confirmModificationTask(currentContract.contract_id, taskId, manualText);
      _replaceTask(updated);
      // 确认可能把批次推进到 ready_for_v2，刷新一下批次状态。
      if (currentBatch) {
        const batches = await listModificationBatches(currentContract.contract_id);
        setCurrentBatch(batches.find((b) => b.batch_id === currentBatch.batch_id) || currentBatch);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setBusyTaskId(null);
    }
  }

  async function handleAbandonModification(taskId) {
    if (!currentContract) return;
    setError(null);
    setBusyTaskId(taskId);
    try {
      const updated = await abandonModificationTask(currentContract.contract_id, taskId);
      _replaceTask(updated);
      if (currentBatch) {
        const batches = await listModificationBatches(currentContract.contract_id);
        setCurrentBatch(batches.find((b) => b.batch_id === currentBatch.batch_id) || currentBatch);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setBusyTaskId(null);
    }
  }

  async function handleRejectModification(taskId, newInstruction) {
    if (!currentContract) return;
    setError(null);
    setBusyTaskId(taskId);
    try {
      const updated = await rejectModificationTask(currentContract.contract_id, taskId, newInstruction);
      _replaceTask(updated);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusyTaskId(null);
    }
  }

  async function handleGenerateVersion(batchId) {
    if (!currentContract || !batchId) return;
    setError(null);
    setGenerateVersionLoading(true);
    try {
      const contractId = currentContract.contract_id;
      const newVersion = await generateVersion(contractId, batchId);
      setVersion(newVersion);
      // V2 生成成功/失败都记在批次上，不会改变任务状态（CONFIRMED 的任务
      // 永久保留 CONFIRMED），但批次状态变了，需要刷新。
      const batches = await listModificationBatches(contractId);
      setCurrentBatch(batches.find((b) => b.batch_id === batchId) || null);
    } catch (err) {
      setError(err.message);
      // 生成失败时批次会被标记为 v2_failed，同样需要刷新，让"重试"按钮出现。
      try {
        const batches = await listModificationBatches(currentContract.contract_id);
        setCurrentBatch(batches.find((b) => b.batch_id === batchId) || null);
      } catch {
        // 刷新失败不覆盖上面已经设置的错误信息
      }
    } finally {
      setGenerateVersionLoading(false);
    }
  }

  async function handleAsk(question) {
    if (!currentContract) return;
    setError(null);
    setAsking(true);
    try {
      const { answer } = await askQuestion(currentContract.contract_id, question);
      setLastQuestion(question);
      setLastAnswer(answer);
    } catch (err) {
      setError(err.message);
    } finally {
      setAsking(false);
    }
  }

  async function handleLoadDiff() {
    if (!currentContract || !version) return;
    setError(null);
    setDiffLoading(true);
    try {
      const entries = await getClauseDiff(currentContract.contract_id, version.version_number);
      setDiffEntries(entries);
    } catch (err) {
      setError(err.message);
    } finally {
      setDiffLoading(false);
    }
  }

  async function handleRunVersionReview() {
    if (!currentContract || !version) return;
    // 和 handleOpenContract 共用同一个请求令牌：如果这次复审还没跑完，用户
    // 就切换到了别的合同，下面拿到结果后发现令牌已经变了，就不再写入
    // state——避免把"刚切走的那份合同"的复审结果写到新合同的页面上。
    const requestId = openRequestRef.current;
    setError(null);
    setVersionReviewLoading(true);
    try {
      const contractId = currentContract.contract_id;
      // POST .../versions/{version}/review 本身就会先持久化再把保存后的
      // ReviewRecord 原样返回——直接用这个返回值更新 v2ReviewRecord，不用
      // 再多发一次 GET 去读刚刚存完的同一条记录。历史记录本身不会被这次
      // 调用覆盖：ContractManager.save_review 永远新增文件，这次调用只是
      // "多了一条最新记录"，不影响之前任何一条历史 ReviewRecord。
      const newRecord = await runVersionReview(contractId, version.version_number);
      if (openRequestRef.current !== requestId) return;
      setV2ReviewRecord(newRecord);
      setV2ReviewError(null);

      setRiskDiffLoading(true);
      const diff = await getRiskDiffOrNull(contractId, version.version_number);
      if (openRequestRef.current !== requestId) return;
      setRiskDiff(diff);
    } catch (err) {
      if (openRequestRef.current === requestId) {
        setError(err.message);
      }
    } finally {
      if (openRequestRef.current === requestId) {
        setVersionReviewLoading(false);
        setRiskDiffLoading(false);
      }
    }
  }

  /**
   * 加载"V2 原文"：只读取已经生成好的 V2 全文（GET /contracts/{linked_
   * contract_id}/text），不解析、不切分、不审查、不生成任何新数据——这是
   * 纯粹的"读"操作。和其他 V2 相关状态一样，用 contract_id + 版本的真实
   * 数据宿主（version.linked_contract_id）去读，不会和 V1 的原文串用；
   * 用 openRequestRef 复用阶段 02 已经建立的竞态保护，不新造一套机制。
   */
  async function handleLoadV2Text() {
    if (!currentContract || !version) return;
    const requestId = openRequestRef.current;
    setV2TextError(null);
    setV2TextLoading(true);
    try {
      const text = await getParsedText(version.linked_contract_id);
      if (openRequestRef.current !== requestId) return;
      setV2Text(text);
    } catch (err) {
      if (openRequestRef.current === requestId) {
        setV2TextError(err.message);
      }
    } finally {
      if (openRequestRef.current === requestId) {
        setV2TextLoading(false);
      }
    }
  }

  /**
   * 切换标签页：和单纯的 setActiveView 相比多做一件事——第一次点进"V2
   * 原文"标签时，如果还没加载过（v2Text 为空）也没有正在加载，顺带触发
   * 一次加载，这样用户点击标签本身就是"查看原文"的入口，不需要进去之后
   * 再多点一次"加载"按钮。已经加载过的内容直接展示，不会每次切换标签都
   * 重新发请求；加载失败后 V2TextView 自己的"重试"按钮会再调用
   * handleLoadV2Text。
   */
  function handleChangeView(viewKey) {
    setActiveView(viewKey);
    if (viewKey === "v2text" && version && v2Text === null && !v2TextLoading) {
      handleLoadV2Text();
    }
  }

  return (
    <div className="page app-layout">
      <header className="app-header">
        <h1 className="page-title">劳动合同智能审查</h1>
      </header>

      {error && (
        <div className="error-banner" onClick={() => setError(null)}>
          {error}
        </div>
      )}

      <div className="app-body">
        <ContractLibrary
          contracts={contracts}
          currentContractId={currentContract?.contract_id || null}
          onSelect={handleOpenContract}
          onUpload={handleUpload}
          uploadLoading={uploadLoading}
          listLoading={contractsLoading}
        />

        <ContractWorkspace
          contract={currentContract}
          clauses={clauses}
          reviewRecord={reviewRecord}
          reviewHistoryCount={reviewHistoryCount}
          modificationTasks={modificationTasks}
          activeView={activeView}
          onChangeView={handleChangeView}
          selectedClauseId={selectedClauseId}
          onSelectClause={setSelectedClauseId}
          onParse={handleParse}
          parseLoading={parseLoading}
          onReview={handleReview}
          reviewLoading={reviewLoading}
          onLocateClause={handleLocateClause}
          onCreateModificationTask={handleCreateModificationTask}
          taskSubmitting={taskSubmitting}
          workspaceLoading={workspaceLoading}
          onStartModification={handleStartModification}
          onConfirmModification={handleConfirmModification}
          onRejectModification={handleRejectModification}
          onAbandonModification={handleAbandonModification}
          busyTaskId={busyTaskId}
          currentBatch={currentBatch}
          onStartBatch={handleStartBatch}
          startBatchLoading={startBatchLoading}
          latestReviewId={reviewRecord ? reviewRecord.review_id : null}
          onAsk={handleAsk}
          asking={asking}
          lastAnswer={lastAnswer}
          lastQuestion={lastQuestion}
          version={version}
          versionsLoading={versionsLoading}
          onGenerateVersion={handleGenerateVersion}
          generateVersionLoading={generateVersionLoading}
          diffEntries={diffEntries}
          diffLoading={diffLoading}
          onLoadDiff={handleLoadDiff}
          riskDiff={riskDiff}
          riskDiffLoading={riskDiffLoading}
          onRunVersionReview={handleRunVersionReview}
          versionReviewLoading={versionReviewLoading}
          v2ReviewRecord={v2ReviewRecord}
          v2ReviewError={v2ReviewError}
          v2Text={v2Text}
          v2TextLoading={v2TextLoading}
          v2TextError={v2TextError}
          onLoadV2Text={handleLoadV2Text}
        />
      </div>
    </div>
  );
}
