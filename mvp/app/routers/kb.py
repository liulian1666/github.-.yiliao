# -*- coding: utf-8 -*-
"""知识库路由：条目查询（按层级过滤）与管理员的增删改。"""

import time  # 时间戳

from fastapi import APIRouter, Depends  # 路由与依赖

from ..core import AppError, ok  # 统一返回
from ..db import get_conn  # 数据库
from ..deps import get_current_user, require_admin  # 权限依赖

router = APIRouter(prefix="/api/kb", tags=["kb"])  # 知识库路由


@router.get("/list")
def list_entries(user: dict = Depends(get_current_user)):
    """查询当前用户可见的知识条目（用户分层的核心卡点）。

    入参：登录态。
    出参：统一结构，data = 可见条目数组（含 tier_required 标注）。
    失败时的行为：未登录 401。
    """
    conn = get_conn()  # 取连接
    if user["role"] == "admin":  # SaaS 管理员看全部
        rows = conn.execute(
            "SELECT id, title, content, category, tier_required, updated_at FROM kb_entries ORDER BY category, id"
        ).fetchall()  # 全量
    else:  # 普通用户只看自己层级够得着的条目
        rows = conn.execute(
            "SELECT id, title, content, category, tier_required, updated_at FROM kb_entries "
            "WHERE tier_required <= ? ORDER BY category, id",
            (user["tier"],),
        ).fetchall()  # 按层级过滤
    conn.close()  # 关连接
    data = [dict(r) for r in rows]  # 转普通 dict
    return ok(data)  # 返回


def _visible_entries(conn, tier: int) -> list:
    """取出某层级可见的全部条目（给 RAG 检索用）。

    入参：conn —— 连接；tier —— 用户层级。
    出参：list —— dict 列表。
    失败时的行为：无失败路径。
    """
    rows = conn.execute(
        "SELECT id, title, content, category, tier_required FROM kb_entries WHERE tier_required <= ?",
        (tier,),
    ).fetchall()  # 查询
    return [dict(r) for r in rows]  # 转换


@router.post("/create")
def create_entry(body: dict, user: dict = Depends(require_admin)):
    """新增知识条目（仅 SaaS 管理员）。

    入参：body —— {title, content, category, tier_required}。
    出参：统一结构，data = 新条目 id。
    失败时的行为：标题/内容为空返回 400；层级不合法返回 400。
    """
    title = (body.get("title") or "").strip()  # 标题
    content = (body.get("content") or "").strip()  # 内容
    category = (body.get("category") or "未分类").strip()  # 分类
    tier = body.get("tier_required", 1)  # 最低可见层级
    if not title or not content:  # 校验
        raise AppError(400, "KB_001", "标题和内容不能为空")  # 400
    if tier not in (1, 2, 3):  # 层级校验
        raise AppError(400, "KB_002", "tier_required 只能是 1/2/3")  # 400
    conn = get_conn()  # 取连接
    cur = conn.execute(
        "INSERT INTO kb_entries (title, content, category, tier_required, updated_at) VALUES (?,?,?,?,?)",
        (title, content, category, tier, int(time.time())),
    )  # 插入
    conn.commit()  # 提交
    conn.close()  # 关连接
    return ok({"id": cur.lastrowid})  # 返回新 id


@router.post("/update")
def update_entry(body: dict, user: dict = Depends(require_admin)):
    """修改知识条目（仅 SaaS 管理员）。

    入参：body —— {id, title?, content?, category?, tier_required?}。
    出参：统一结构，data = {id}。
    失败时的行为：条目不存在返回 404；字段不合法返回 400。
    """
    eid = body.get("id")  # 条目 id
    conn = get_conn()  # 取连接
    row = conn.execute("SELECT id FROM kb_entries WHERE id = ?", (eid,)).fetchone()  # 查存在性
    if row is None:  # 不存在
        conn.close()  # 关连接
        raise AppError(404, "KB_003", "知识条目不存在")  # 404
    fields, params = [], []  # 动态拼 SET 子句
    if "title" in body and (body["title"] or "").strip():  # 标题
        fields.append("title = ?"); params.append(body["title"].strip())  # 追加
    if "content" in body and (body["content"] or "").strip():  # 内容
        fields.append("content = ?"); params.append(body["content"].strip())  # 追加
    if "category" in body and (body["category"] or "").strip():  # 分类
        fields.append("category = ?"); params.append(body["category"].strip())  # 追加
    if "tier_required" in body:  # 层级
        if body["tier_required"] not in (1, 2, 3):  # 校验
            conn.close()  # 关连接
            raise AppError(400, "KB_002", "tier_required 只能是 1/2/3")  # 400
        fields.append("tier_required = ?"); params.append(body["tier_required"])  # 追加
    if fields:  # 有更新才写库
        fields.append("updated_at = ?"); params.append(int(time.time()))  # 刷新时间戳
        params.append(eid)  # WHERE 参数
        conn.execute(f"UPDATE kb_entries SET {', '.join(fields)} WHERE id = ?", params)  # 更新
        conn.commit()  # 提交
    conn.close()  # 关连接
    return ok({"id": eid})  # 返回


@router.post("/delete")
def delete_entry(body: dict, user: dict = Depends(require_admin)):
    """删除知识条目（仅 SaaS 管理员，级联删除关系边）。

    入参：body —— {id}。
    出参：统一结构，data = {id}。
    失败时的行为：条目不存在返回 404。
    """
    eid = body.get("id")  # 条目 id
    conn = get_conn()  # 取连接
    row = conn.execute("SELECT id FROM kb_entries WHERE id = ?", (eid,)).fetchone()  # 查存在性
    if row is None:  # 不存在
        conn.close()  # 关连接
        raise AppError(404, "KB_003", "知识条目不存在")  # 404
    conn.execute("DELETE FROM kb_links WHERE from_id = ? OR to_id = ?", (eid, eid))  # 删关系边
    conn.execute("DELETE FROM kb_entries WHERE id = ?", (eid,))  # 删条目
    conn.commit()  # 提交
    conn.close()  # 关连接
    return ok({"id": eid})  # 返回
