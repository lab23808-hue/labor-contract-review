"""modification：合同修改闭环（Service 编排 → Validator → Tool）。

Modification Agent 已经迁移到 agents.modification_agent（Stage 1 架构重构，
Agent 统一归属 agents 包）。

本包的 __init__ 故意不在包级别 re-export Service / Validator / Tool：
agents.modification_agent 需要 import modification.tool（Tool 仍然留在
本包内，只是实现细节），而 modification.service 需要 import
agents.modification_agent——如果 __init__.py 在包初始化时就 eager 加载
modification.service，会在"agents.modification_agent 导入中途又反过来
导入 modification 包"这条路径上形成循环导入。调用方统一直接从子模块
import（例如 `from modification.service import ModificationService`），
不经过包级别的re-export，从源头避免这个循环。
"""
