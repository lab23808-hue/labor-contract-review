/**
 * 展示用的中英文映射表。只是纯数据，不包含任何业务判断逻辑——
 * 合同状态、风险等级本身永远以后端返回的值为准，这里只负责把它翻译成中文。
 */

export const STATUS_LABELS_ZH = {
  uploaded: "已上传",
  parsed: "已解析",
  split: "已切分条款",
  reviewed: "已生成审查报告",
  failed: "失败",
};

export const RISK_LEVEL_LABELS_ZH = {
  none: "无风险",
  low: "低风险",
  medium: "中风险",
  high: "高风险",
};

export const TASK_STATUS_LABELS_ZH = {
  pending: "待处理",
  waiting_confirmation: "待律师确认",
  rejected: "已拒绝，待重新修改",
  needs_human: "需人工处理",
  confirmed: "已确认",
  abandoned: "已放弃",
};

export const BATCH_STATUS_LABELS_ZH = {
  in_progress: "进行中",
  ready_for_v2: "可生成 V2",
  v2_generating: "生成中",
  v2_generated: "已生成 V2",
  v2_failed: "生成失败",
};

export const RISK_RESOLUTION_LABELS_ZH = {
  resolved: "风险已化解",
  partially_resolved: "风险部分化解",
  unresolved: "风险未化解",
  unknown: "无法判断（分析失败）",
};

/** ModificationTask.status 允许的最大重试轮次，和后端 schemas/modification_task.py 保持一致。 */
export const MAX_MODIFICATION_ATTEMPTS = 3;
