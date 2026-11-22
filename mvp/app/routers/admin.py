# -*- coding: utf-8 -*-
"""管理后台路由（仅 SaaS 管理员）：用户管理 + 问答留痕查看。"""

import time  # 时间戳

from fastapi import APIRouter, Depends  # 路由与依赖

from ..core import AppError, ok  # 统一返回
from ..db import get_conn  # 数据库
from ..deps import require_admin  # 管理员卡点
from ..security import hash_password  # 密码哈希

router = APIRouter(prefix="/api/admin", tags=["admin"])  # 管理路由


@router.get("/users")
def list_users(user: dict = Depends(require_admin)):
    """用户列表（仅管理员）。

    入参：管理员登录态。
    出参：统一结构，data = 用户数组（不含密码字段）。
    失败时的行为：非管理员 403。
    """
    conn = get_conn()  # 取连接
    rows = conn.execute(
        "SELECT id, username, role, tier, display_name, created_at FROM users ORDER BY id"
    ).fetchall()  # 查全部用户
    conn.close()  # 关连接
    return ok([dict(r) for r in rows])  # 返回


@router.post("/users/create")
def create_user(body: dict, user: dict = Depends(require_admin)):
    """创建用户（仅管理员）：可指定角色与层级。

    入参：body —— {username, password, role?, tier?, display_name?}。
    出参：统一结构，data = {id}。
    失败时的行为：用户名已存在 400；字段不合法 400。
    """
    username = (body.get("username") or "").strip()  # 用户名
    password = body.get("password") or ""  # 密码
    role = body.get("role", "user")  # 角色，默认普通用户
    tier = body.get("tier", 1)  # 层级，默认 1
    display = (body.get("display_name") or username).strip()  # 显示名
    if not username or len(password) < 6:  # 基本校验
        raise AppError(400, "ADM_001", "用户名不能为空，密码至少 6 位")  # 400
    if role not in ("admin", "user"):  # 角色校验
        raise AppError(400, "ADM_002", "role 只能是 admin/user")  # 400
    if tier not in (1, 2, 3):  # 层级校验
        raise AppError(400, "ADM_003", "tier 只能是 1/2/3")  # 400
    conn = get_conn()  # 取连接
    dup = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()  # 查重
    if dup:  # 已存在
        conn.close()  # 关连接
        raise AppError(400, "ADM_004", "用户名已存在")  # 400
    pw_hash, salt = hash_password(password)  # 哈希
    cur = conn.execute(
        "INSERT INTO users (username, password_hash, salt, role, tier, display_name, created_at) VALUES (?,?,?,?,?,?,?)",
        (username, pw_hash, salt, role, tier, display, int(time.time())),
    )  # 插入
    conn.commit()  # 提交
    conn.close()  # 关连接
    return ok({"id": cur.lastrowid})  # 返回


@router.post("/users/update")
def update_user(body: dict, user: dict = Depends(require_admin)):
    """修改用户层级/角色/密码（仅管理员）。

    入参：body —— {id, tier?, role?, password?, display_name?}。
    出参：统一结构，data = {id}。
    失败时的行为：目标用户不存在 404；字段不合法 400。
    """
    uid = body.get("id")  # 目标用户 id
    conn = get_conn()  # 取连接
    row = conn.execute("SELECT id FROM users WHERE id = ?", (uid,)).fetchone()  # 查存在性
    if row is None:  # 不存在
        conn.close()  # 关连接
        raise AppError(404, "ADM_005", "用户不存在")  # 404
    fields, params = [], []  # 动态 SET
    if "tier" in body:  # 层级
        if body["tier"] not in (1, 2, 3):  # 校验
            conn.close()  # 关连接
            raise AppError(400, "ADM_003", "tier 只能是 1/2/3")  # 400
        fields.append("tier = ?"); params.append(body["tier"])  # 追加
    if "role" in body:  # 角色
        if body["role"] not in ("admin", "user"):  # 校验
            conn.close()  # 关连接
            raise AppError(400, "ADM_002", "role 只能是 admin/user")  # 400
        fields.append("role = ?"); params.append(body["role"])  # 追加
    if "display_name" in body and (body["display_name"] or "").strip():  # 显示名
        fields.append("display_name = ?"); params.append(body["display_name"].strip())  # 追加
    if "password" in body and len(body["password"]) >= 6:  # 重置密码
        pw_hash, salt = hash_password(body["password"])  # 新哈希
        fields.append("password_hash = ?"); params.append(pw_hash)  # 哈希
        fields.append("salt = ?"); params.append(salt)  # 盐
    if fields:  # 有更新
        params.append(uid)  # WHERE
        conn.execute(f"UPDATE users SET {', '.join(fields)} WHERE id = ?", params)  # 更新
        conn.commit()  # 提交
    conn.close()  # 关连接
    return ok({"id": uid})  # 返回


@router.get("/chatlogs")
def chat_logs(user: dict = Depends(require_admin)):
    """问答留痕列表（仅管理员，演示"管理员可见全量审计"）。

    入参：管理员登录态。
    出参：统一结构，data = 留痕数组（附用户名）。
    失败时的行为：非管理员 403。
    """
    conn = get_conn()  # 取连接
    rows = conn.execute(
        "SELECT c.id, u.username, u.display_name, c.question, c.sources, c.created_at "
        "FROM chat_logs c JOIN users u ON u.id = c.user_id ORDER BY c.id DESC LIMIT 100"
    ).fetchall()  # 最近 100 条
    conn.close()  # 关连接
    return ok([dict(r) for r in rows])  # 返回
