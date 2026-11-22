# -*- coding: utf-8 -*-
"""依赖注入层：FastAPI 依赖项，负责从请求中解析登录态并做权限卡点。

权限模型（对应老师要求"管理员（SaaS）、用户（分层）"）：
- role=admin：SaaS 管理员，可管理用户与知识库，可见全部数据。
- role=user：普通用户，tier 层级 1/2/3，只能看到 tier_required <= 自身 tier 的知识。
"""

from fastapi import Depends, Header  # FastAPI 依赖

from .db import get_conn  # 数据库连接
from .security import parse_token  # Token 解析


def get_current_user(
    authorization: str = Header(default=""),  # 标准 Bearer 头
    x_auth_token: str = Header(default=""),  # 备用头：部分网关会改写 Authorization
) -> dict:
    """解析登录凭证，返回当前登录用户信息。

    入参：authorization —— "Bearer <token>"；x_auth_token —— 备用凭证头。
    出参：dict —— {id, username, role, tier, display_name}。
    失败时的行为：未登录/Token 无效时抛 401 业务异常（由统一异常处理器返回）。
    """
    from .core import AppError  # 延迟导入避免循环依赖

    token = x_auth_token.strip()  # 优先取备用头（防网关改写 Authorization）
    if not token and authorization.startswith("Bearer "):  # 回落到标准头
        token = authorization[7:].strip()  # 取出 token 本体
    if not token:  # 没带 Token
        raise AppError(401, "AUTH_001", "未登录或凭证缺失")  # 401
    payload = parse_token(token)  # 解析签名与有效期
    if payload is None:  # 无效或过期
        raise AppError(401, "AUTH_002", "登录已过期，请重新登录")  # 401
    conn = get_conn()  # 取连接
    row = conn.execute("SELECT * FROM users WHERE id = ?", (payload["uid"],)).fetchone()  # 查库里的用户
    conn.close()  # 关连接
    if row is None:  # 用户已被删除
        raise AppError(401, "AUTH_003", "账号不存在")  # 401
    return {  # 返回当前用户视图（不回传密码字段）
        "id": row["id"],  # 用户 id
        "username": row["username"],  # 用户名
        "role": row["role"],  # 角色
        "tier": row["tier"],  # 层级
        "display_name": row["display_name"],  # 显示名
    }


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    """管理员卡点：仅 SaaS 管理员可通过。

    入参：user —— 当前用户（由 get_current_user 注入）。
    出参：dict —— 当前用户。
    失败时的行为：非管理员抛 403（权限不足）。
    """
    from .core import AppError  # 延迟导入

    if user["role"] != "admin":  # 不是管理员
        raise AppError(403, "AUTH_004", "需要 SaaS 管理员权限")  # 403
    return user  # 放行
