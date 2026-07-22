"""
app_server — 服务层 + 数据层

管理用户认证、会话、数据库、API 路由和渠道集成。
通过 agent_engine 的公共 API 调用 LLM 引擎。

入口: uvicorn app_server.main:app
"""
