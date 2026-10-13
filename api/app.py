"""FastAPI 应用入口。

本阶段只做三件事：
    1. 创建 FastAPI 实例
    2. 挂载 lifespan（见 api/dependencies.py），启动时把重对象构造一次
    3. 留出后续业务路由的挂载位置

刻意不在这里实现任何 /contracts 等业务接口——那是确认过的下一步。
本文件不应该出现任何业务逻辑（请求校验、序列化、调用 ContractManager 等），
这些属于 api/routes/ 下的路由模块。

运行方式（本地开发）：
    uvicorn api.app:app --reload

注意：当前业务链路（run_review / DeepSeek chat / LangGraph invoke）都是
同步阻塞调用。业务路由统一使用普通 `def`，不用 `async def`——
用 `async def` 反而会让这些阻塞调用占住事件循环，弄巧成拙。FastAPI 对
`def` 路由会自动放到线程池里执行，这正是我们需要的行为。
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.dependencies import lifespan
from api.routes import contracts, modification

app = FastAPI(title="劳动合同智能审查系统 API", lifespan=lifespan)

# 仅为前端 MVP（Vite 开发服务器 http://localhost:5173）放行跨域请求。
# 这是本次前端任务里唯一允许的后端改动，不涉及任何业务逻辑，
# 不影响 /contracts 等接口本身的行为。
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(contracts.router)
app.include_router(modification.router)
