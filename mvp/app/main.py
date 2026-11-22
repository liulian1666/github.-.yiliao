# -*- coding: utf-8 -*-
"""应用入口：FastAPI 装配、统一异常处理、启动初始化、静态前端托管。"""

import os  # 路径
import traceback  # 服务端日志

from fastapi import FastAPI, Request  # 框架
from fastapi.responses import JSONResponse  # 响应
from fastapi.staticfiles import StaticFiles  # 静态文件

from .core import AppError, err  # 统一返回
from .db import init_db, seed_all  # 初始化与种子
from .routers import admin, auth, kb, rag, wiki  # 路由模块

_STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")  # 静态目录


def create_app() -> FastAPI:
    """创建并装配 FastAPI 应用。

    入参：无。
    出参：FastAPI —— 装配好的应用实例。
    失败时的行为：装配错误直接抛出，启动失败即终止。
    """
    app = FastAPI(title="门诊知识助手 MVP", version="1.0.0")  # 应用实例
    app.include_router(auth.router)  # /api/auth 登录
    app.include_router(kb.router)  # /api/kb 知识库
    app.include_router(rag.router)  # /api/rag 检索与留痕
    app.include_router(wiki.router)  # /api/wiki 知识图谱
    app.include_router(admin.router)  # /api/admin 管理后台

    @app.get("/api/health")
    def health():
        """健康检查：线上探活用。

        入参：无。
        出参：统一结构，data = {status: "up"}。
        失败时的行为：无失败路径。
        """
        return {"ok": True, "data": {"status": "up"}, "error": None}  # 固定健康结构

    @app.exception_handler(AppError)  # 业务异常处理器
    async def app_error_handler(request: Request, exc: AppError):  # 处理函数
        """把业务异常转成统一失败返回。

        入参：request —— 当前请求；exc —— 业务异常。
        出参：JSONResponse —— 统一结构。
        失败时的行为：无失败路径。
        """
        return JSONResponse(status_code=exc.status, content=err(exc.code, exc.msg))  # 统一失败

    @app.exception_handler(Exception)  # 兜底异常处理器
    async def sys_error_handler(request: Request, exc: Exception):  # 处理函数
        """未预期异常统一返回 SYS_001，堆栈只写服务端日志不外泄。

        入参：request —— 当前请求；exc —— 任意异常。
        出参：JSONResponse —— 统一结构。
        失败时的行为：无失败路径。
        """
        traceback.print_exc()  # 服务端日志
        return JSONResponse(status_code=500, content=err("SYS_001", "系统内部错误，请稍后重试"))  # 对外统一

    @app.on_event("startup")  # 启动钩子
    def on_startup():  # 启动函数
        """启动时建表并写入种子数据（幂等）。

        入参：无。
        出参：无。
        失败时的行为：初始化失败应用拒绝启动。
        """
        init_db()  # 建表
        seed_all()  # 种子数据

    # 静态前端挂载到最后（不遮蔽 /api 路由），index.html 作为首页
    app.mount("/", StaticFiles(directory=_STATIC_DIR, html=True), name="static")  # 静态托管
    return app  # 返回


app = create_app()  # 模块级实例，uvicorn app.main:app / python main.py 均可启动
