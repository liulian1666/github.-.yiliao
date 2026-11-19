# -*- coding: utf-8 -*-
"""应用入口：FastAPI 应用装配、全局异常处理、启动初始化。"""  # 模块级说明

import traceback  # 引入 traceback，用于服务端错误日志

from fastapi import FastAPI, Request  # 引入 FastAPI 与请求对象
from fastapi.responses import JSONResponse  # 引入 JSON 响应
from fastapi.exceptions import RequestValidationError  # 捕获请求参数和JSON解析错误
from starlette.exceptions import HTTPException  # 同时捕获路由层404、405等框架异常

from .core.response import AppError, err  # 引入统一返回与业务异常
from .db.models import init_db  # 引入建表函数
from .db.seed import seed_users  # 引入种子数据函数
from .routers import auth, audit  # 引入路由模块


def create_app() -> FastAPI:
    """创建并装配 FastAPI 应用。

    入参：无。
    出参：FastAPI —— 装配好的应用实例。
    失败时的行为：路由注册冲突等装配错误直接抛出，启动失败即终止。
    """
    # 创建应用实例（标题与版本写在这里，业务配置都在 config.yaml）
    app = FastAPI(title="门诊预约与分诊协作智能体系统", version="0.1.0-phase1")  # 应用实例
    # 注册认证路由
    app.include_router(auth.router)  # 挂载 /api/auth
    # 注册审计路由
    app.include_router(audit.router)  # 挂载 /api/audit

    @app.exception_handler(RequestValidationError)  # 参数错误也遵守统一响应契约
    async def validation_error_handler(request: Request, exc: RequestValidationError):  # 不回显原始入参
        """将请求校验失败转换为统一422响应。

        入参：request为当前请求，exc为参数校验异常。
        出参：JSONResponse，错误码REQ_001，HTTP状态422。
        失败时的行为：不返回异常详情或请求体，避免错误类型的口令等敏感输入被回显。
        """
        # 校验异常的errors()可能包含input，不能把原始口令或患者输入直接返回客户端。
        return JSONResponse(status_code=422, content=err("REQ_001", "请求参数缺失或格式错误"))  # 保留参数错误HTTP语义

    @app.exception_handler(HTTPException)  # 使用Starlette基类覆盖框架与FastAPI异常
    async def http_error_handler(request: Request, exc: HTTPException):  # 保留状态和协议响应头
        """将HTTP异常转换为统一失败响应。

        入参：request为当前请求，exc为HTTP异常。
        出参：JSONResponse，保留原HTTP状态和响应头，错误码HTTP_状态码。
        失败时的行为：未知状态使用通用提示，不直接公开任意异常detail。
        """
        messages = {400: "请求无法处理", 401: "请先登录", 403: "无权访问该资源", 404: "请求的资源不存在", 405: "请求方法不允许", 429: "请求过于频繁，请稍后重试"}  # 公开提示不包含内部详情
        # Allow、WWW-Authenticate等响应头具有协议含义，统一JSON时必须保留。
        return JSONResponse(status_code=exc.status_code, content=err(f"HTTP_{exc.status_code}", messages.get(exc.status_code, "请求无法处理")), headers=exc.headers)  # 复用现有err结构

    # 注册业务异常处理器：把 AppError 转成统一返回结构
    @app.exception_handler(AppError)  # 异常处理器注册
    async def app_error_handler(request: Request, exc: AppError):  # 处理函数
        """把业务异常转换为统一失败返回。

        入参：request —— 当前请求；exc —— 业务异常。
        出参：JSONResponse —— 统一结构 {"ok": False, "error": {...}}。
        失败时的行为：无失败路径。
        """
        # 返回统一失败结构（HTTP 状态码随异常携带）
        return JSONResponse(status_code=exc.status, content=err(exc.code, exc.msg))  # 统一失败响应

    # 注册兜底异常处理器：未预期异常不得泄露堆栈给客户端
    @app.exception_handler(Exception)  # 兜底处理器注册
    async def sys_error_handler(request: Request, exc: Exception):  # 处理函数
        """把未预期异常转换为 SYS_001 统一返回。

        入参：request —— 当前请求；exc —— 任意异常。
        出参：JSONResponse —— 统一结构，错误码 SYS_001。
        失败时的行为：堆栈只写服务端日志，不返回给客户端（防止信息泄露）。
        """
        # 堆栈写入服务端日志供排查
        traceback.print_exc()  # 打印堆栈
        # 返回统一失败结构（对外只给通用错误码）
        return JSONResponse(status_code=500, content=err("SYS_001", "系统内部错误，请稍后重试"))  # 统一失败响应

    # 注册启动事件：建表 + 写种子数据
    @app.on_event("startup")  # 启动钩子
    def on_startup():  # 启动函数
        """应用启动时初始化数据库并写入演示账号。

        入参：无。
        出参：无。
        失败时的行为：初始化失败时异常向上抛出，应用拒绝启动。
        """
        # 建目录建表
        init_db()  # 建表
        # 写入六角色演示账号（幂等）
        seed_users()  # 种子数据

    # 返回装配好的应用
    return app  # 应用实例


# 模块级应用实例（uvicorn app.main:app 直接引用）
app = create_app()  # 应用实例
