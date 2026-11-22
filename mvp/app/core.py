# -*- coding: utf-8 -*-
"""核心公共件：统一业务异常与统一返回结构。

所有接口统一返回 {"ok": bool, "data": ..., "error": {"code","msg"}}（沿用 docs2 Phase 1 规范）。
"""

from fastapi.responses import JSONResponse  # 统一响应


class AppError(Exception):
    """业务异常：携带 HTTP 状态码、错误码与用户可读信息。"""

    def __init__(self, status: int, code: str, msg: str):  # 构造
        super().__init__(msg)  # 保留原始信息
        self.status = status  # HTTP 状态码
        self.code = code  # 业务错误码（AUTH_/KB_/RAG_/SYS_ 前缀）
        self.msg = msg  # 用户可读信息


def ok(data=None) -> dict:
    """构造成功返回。

    入参：data —— 业务数据。
    出参：dict —— {"ok": True, "data": data, "error": None}。
    失败时的行为：无失败路径。
    """
    return {"ok": True, "data": data, "error": None}  # 成功结构


def err(code: str, msg: str) -> dict:
    """构造失败返回（不含 data）。

    入参：code —— 错误码；msg —— 用户可读信息。
    出参：dict —— {"ok": False, "data": None, "error": {...}}。
    失败时的行为：无失败路径。
    """
    return {"ok": False, "data": None, "error": {"code": code, "msg": msg}}  # 失败结构


def error_response(status: int, code: str, msg: str) -> JSONResponse:
    """构造失败 JSONResponse（供异常处理器使用）。

    入参：status —— HTTP 状态码；code —— 错误码；msg —— 信息。
    出参：JSONResponse。
    失败时的行为：无失败路径。
    """
    return JSONResponse(status_code=status, content=err(code, msg))  # 统一失败响应
