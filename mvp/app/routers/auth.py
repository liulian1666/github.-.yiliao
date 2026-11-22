# -*- coding: utf-8 -*-
"""认证路由：登录、获取当前用户信息。"""

from fastapi import APIRouter, Depends  # 路由与依赖

from ..core import AppError, ok  # 统一返回
from ..db import get_conn  # 数据库
from ..deps import get_current_user  # 登录态依赖
from ..security import issue_token, verify_password  # 签发与校验

router = APIRouter(prefix="/api/auth", tags=["auth"])  # 认证路由


@router.post("/login")
def login(body: dict):
    """登录接口：校验用户名密码，签发绑定角色与层级的 Token。

    入参：body —— {username, password}。
    出参：统一结构，data = {token, user:{username,role,tier,display_name}}。
    失败时的行为：用户名不存在或密码错误返回 401（不区分是哪种，防枚举）。
    """
    username = (body.get("username") or "").strip()  # 用户名
    password = body.get("password") or ""  # 密码
    if not username or not password:  # 参数不齐
        raise AppError(400, "AUTH_010", "用户名和密码不能为空")  # 400
    conn = get_conn()  # 取连接
    row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()  # 查用户
    conn.close()  # 关连接
    if row is None or not verify_password(password, row["salt"], row["password_hash"]):  # 校验失败
        raise AppError(401, "AUTH_011", "用户名或密码错误")  # 统一提示，防账号枚举
    token = issue_token(row)  # 签发 Token
    return ok({  # 成功返回
        "token": token,  # 凭证
        "user": {  # 用户视图
            "username": row["username"],  # 用户名
            "role": row["role"],  # 角色
            "tier": row["tier"],  # 层级
            "display_name": row["display_name"],  # 显示名
        },
    })


@router.get("/me")
def me(user: dict = Depends(get_current_user)):
    """获取当前登录用户信息（前端刷新后恢复登录态用）。

    入参：Authorization 头。
    出参：统一结构，data = 用户视图。
    失败时的行为：未登录返回 401。
    """
    return ok(user)  # 直接返回依赖注入的用户
