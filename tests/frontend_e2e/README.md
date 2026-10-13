# 前端交互全流程验证（替身后端 + 真实 React 应用）

这不是 pytest 用例，是一次性用 esbuild + Playwright 跑的真实浏览器交互验证：
真实的 React/ReactDOM、真实且完全未改动的 `frontend/src/App.jsx` 及其全部
子组件、真实的 `frontend/src/api/client.js`，只把 `window.fetch` 替换成一个
内存里的假后端（按真实 schemas 字段形状拼数据、按真实路由 URL 分发）。

跑法（需要 esbuild + playwright + 一个本地 Chromium，构建/运行环境相关，
不是每个环境都能直接跑）：

    node build_app.mjs        # 用 esbuild 把 harness_app.jsx + 真实 src 打包成一个 iife bundle
    python3 run_app_playwright.py   # 用 Playwright 打开 bundle，驱动一遍完整交互流程

覆盖的交互链路：上传合同 → 解析 → 查看条款 → 发起审查 → 定位条款 →
提交修改任务 → 开始修改（假 Agent 返回候选）→ 确认修改 → 生成 V2 →
查看条款 Diff → 对 V2 发起复审 → 查看风险 Diff → 模拟刷新页面。

因为 LLM/Validator 是假的（固定返回一个能通过的候选），这份验证测的是
"前端交互链路对不对"，不是"Agent/Validator 本身对不对"——后者由
scripts/verify_modification.py 和 scripts/verify_agent_function_calling.py
用真实 Python 代码覆盖。
