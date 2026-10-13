"""api：对外提供 HTTP 接口的入口层。

只负责把已有业务模块（contract / parser / clause / rag / llm / review / rules）
通过 FastAPI 暴露出去，不在这里重新实现业务逻辑。

app.py           创建 FastAPI 实例、挂载 lifespan、挂载业务路由（业务路由待实现）
dependencies.py  lifespan + 依赖注入：重对象只在应用启动时构造一次
"""
