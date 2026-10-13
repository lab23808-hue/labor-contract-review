# 实验知识库工作目录（统一版，取代 experiment_kb_v2 / experiment_kb_v3）

**重要澄清（回应"是否已写入电脑"）**：本目录及其前身 `experiment_kb_v2`、
`experiment_kb_v3` 从未写入过用户电脑的真实项目目录。真实设备上`labor_contract_review/`
根目录下没有任何 `experiment_kb*` 文件夹（已用 `device_list_dir` 直接核对确认）。
v2/v3 只存在于：(1) 云端沙箱这个路径，(2) 之前通过SendUserFile发给用户的zip文件。

## 结构
- `baseline/`：正式生产知识库的只读副本（2026-10-12从真实设备重新拉取，26条Evidence，
  指纹 `f9a4897645aa0f4c6426966bc529c9702101fd8904a2d2a25207ae387c0a741f`）。
- `working/`：当前工作版本 = baseline + 本轮白名单A+B（37条Evidence，指纹见`snapshots/`）。
  **后续小幅更新直接在这里修改，不新建v4/v5目录**；每次更新前后都在`snapshots/`留一份
  带时间戳说明的快照、在`diff_reports/`留一份diff，不覆盖旧快照文件。
- `reference_only/`：仲裁法第十—十六条参考材料，不参与核心索引。
- `whitelist/WHITELIST_current.md`：当前唯一现行白名单（取代v2/v3各自的白名单文件）。
- `snapshots/`、`diff_reports/`：baseline与working的快照及diff。

## 本轮（2026-10-12）变更摘要
- Evidence: 26 → 37（新增11条：劳动合同法第五十条1条 + 劳动法第三十六—四十五条10条）
- 0重复，最长新增条文171字（第四十四条），未触发截断保护
- 仲裁法范围从v3的"第十—三十条"收窄为"第十—十六条，且不进入核心索引"
- 劳动法来源状态如实标注"来源版本尚待进一步核实"，不等同于官方核验完成
