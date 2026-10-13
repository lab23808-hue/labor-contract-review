# 本轮未能解决的问题清单（需要补充关联 / 下一轮定向调查）

本文件明确列出"本轮证据不足、不能瞎猜"的项，全部标注为需要专门调查，而不是在其他文件里悄悄假设为已知。

## 架构相关

1. `agents/review_agent.py`（5137B）的 Prompt 内容本轮未读取——是否硬编码"劳动合同"相关措辞，直接决定了 LLM Review 节点对租赁合同的可复用程度。**需要补充关联**。
2. `rules/checker.py`（2492B）/`rules/merge.py`（1679B）的真实接口签名本轮未读取——"RuleChecker 是否真的可插拔替换成租赁合同规则"目前是 INFERRED，不是 CONFIRMED。**需要补充关联**。
3. `document/splitter.py`（11328B）的切分规则细节本轮未读——是否假设了"第X条"这种劳动合同常见编号格式，若租赁合同条款编号习惯不同，可能需要调整。**需要补充关联**。
4. `frontend/src/` 下14个组件源码本轮完全未读——是否有任何前端本地持久化（localStorage等）机制，以及是否有合同类型相关的硬编码文案。**需要补充关联**。
5. `Labor_Contract_Review_Project_Report.md`（25327B）、`README.md`（32434B）、`tree.txt`（5.6MB）三份既有文档本轮刻意未读（为避免被旧文档断言污染本轮独立核查结论）——下一轮可以把它们当作交叉校验材料，但不应直接当作事实来源。

## 数据存储相关

6. `data/contracts/` 下22个真实合同目录，本轮只确认了目录结构模式，未逐一统计总字节数/sha256/逐目录是否齐备5类子项。**需要补充关联**。
7. `data/eval_samples/RAG_HUMAN_REVIEW_BATCH1.xlsx`（11609B）——本轮首次发现此文件存在，完全未打开核实内容，文件名暗示"人工复核批次1"，可能是一份真实有价值的人工标注产出，建议下一轮优先核实。**需要补充关联，优先级较高**。
8. `data/eval_samples/results/` 下14个历史原始实验结果文件（180KB-1.4MB级别）——本轮只确认存在性和大小，未逐一核实其内容是否与 `RAG_EXPERIMENT_REGISTER.csv` 中记录的 E001-E010 等实验严格对应。**需要补充关联**。
9. `docs/DEVELOPMENT_LOG.md` vs `docs/DEVLOG.md`、`docs/INTERVIEW_QA.md` vs `docs/INTERVIEW.md` 两对疑似重复文档——本轮只凭文件名与体量猜测可能重复，未读取内容核实，不排除实为"不同阶段的独立记录，恰好体量接近"。**需要补充关联**。
10. `scripts/build_snapshot_fingerprint.py`（16517B）与 `experiment_kb/build_snapshot_fingerprint.py`（同样16517B）——体量完全相同，高度疑似是同一份文件的两个拷贝，但本轮未做字节级diff确认。**需要补充关联**。

## 脚本相关

11. `EXPERIMENT_SCRIPT_CATALOG.csv` 中列出的31个脚本（`scripts/`根级29个中除已验证的3个experiment_kb脚本外的全部）——本轮只核实了文件名和大小，purpose/risk/triggers_external_calls/modifies_data 全部是基于命名的推断（INFERRED），不是读码确认（CONFIRMED）。下一轮如果要真正评估"哪些脚本可以安全删除/哪些仍有复现价值"，必须逐篇打开阅读。**需要补充关联，这是本轮最大的证据缺口**。
12. `scripts/README.md`（8184B）本轮未读——这份文件理论上应该是了解全部29个脚本真实用途的最高效起点，建议作为下一轮的第一个读取对象。

## experiment_kb / A001-A006 相关

13. A006报告中"长度因素"vs"高频词共享因素"对竞争加剧的具体贡献占比——A006原文已明确标注为 `UNDETERMINED`（需要消融实验），本轮未新增任何计算，原样保留为未解决问题。
14. 方案C（查询关键词路由）在 final_test（development未触碰的90条）上的独立验证结果——A006明确要求"等待用户确认后才可能开展"，本轮未执行，仍是未知。
15. `RAG_EXPERIMENT_REGISTER.csv` 作为未来DB导入基础是否存在字段缺口——本轮已在 DATA_STORAGE_AUDIT.md 第5节给出初步结论（存在字段过载、枚举不统一等问题），但"缺口清单是否完整"本身仍需要在真正设计表结构时进一步校验，不排除还有本轮未发现的缺口。

## 需要用户决策，不是证据缺口

16. 是否接受"500份合同评测集中真实合同占比很低、主体是标注清晰的合成数据"这一务实方案（A003已提出，等待确认，本轮延续沿用A003的现状，未重新发起讨论）。
17. 是否授权对 `tmp_runtime/` 下4个临时文件、`RAG_EXPERIMENT_REGISTER_with_A004.csv` 做实际归档/清理（本轮按指令只报告不操作）。
