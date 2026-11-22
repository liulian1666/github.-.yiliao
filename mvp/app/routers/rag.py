# -*- coding: utf-8 -*-
"""RAG 路由：检索 + 问答留痕。

分工：检索在本后端完成（权限过滤前置），大模型生成由前端通过云服务 LLM 通道调用——
后端不持有任何模型密钥（密钥永不落代码）。
"""

from fastapi import APIRouter, Depends  # 路由与依赖
from pydantic import BaseModel  # 请求体模型

from ..core import ok  # 统一返回
from ..db import get_conn  # 数据库
from ..deps import get_current_user  # 登录态
from ..rag import search  # 检索实现

router = APIRouter(prefix="/api/rag", tags=["rag"])  # RAG 路由


class SearchBody(BaseModel):
    """检索请求体。"""

    query: str  # 用户问题
    top_k: int = 4  # 返回条数


@router.post("/search")
def rag_search(body: SearchBody, user: dict = Depends(get_current_user)):
    """RAG 检索接口：在当前用户可见的知识范围内检索最相关的条目。

    入参：body —— {query, top_k?}。
    出参：统一结构，data = {chunks:[{id,title,content,category,score}]}。
    失败时的行为：空查询返回 400；未登录 401。
    """
    query = body.query.strip()  # 清理空白
    if not query:  # 空查询
        from ..core import AppError  # 异常
        raise AppError(400, "RAG_001", "问题不能为空")  # 400
    conn = get_conn()  # 取连接
    tier = 3 if user["role"] == "admin" else user["tier"]  # 管理员视为最高层级
    entries = _visible(conn, tier)  # 取可见条目
    conn.close()  # 关连接
    chunks = search(query, entries, top_k=max(1, min(body.top_k, 6)))  # 检索
    return ok({"chunks": chunks})  # 返回


def _visible(conn, tier: int) -> list:
    """取某层级可见条目（避免从 kb 路由导入造成耦合）。

    入参：conn —— 连接；tier —— 层级。
    出参：list —— dict 列表。
    失败时的行为：无失败路径。
    """
    rows = conn.execute(
        "SELECT id, title, content, category, tier_required FROM kb_entries WHERE tier_required <= ?",
        (tier,),
    ).fetchall()  # 查询
    return [dict(r) for r in rows]  # 转换


class LogBody(BaseModel):
    """问答留痕请求体。"""

    question: str  # 问题
    sources: str = ""  # 引用来源（标题拼接）


@router.post("/log")
def rag_log(body: LogBody, user: dict = Depends(get_current_user)):
    """问答留痕：记录一次 RAG 问答的问题与引用来源（审计用）。

    入参：body —— {question, sources}。
    出参：统一结构，data = {id}。
    失败时的行为：未登录 401。
    """
    import time as _t  # 时间戳
    conn = get_conn()  # 取连接
    cur = conn.execute(
        "INSERT INTO chat_logs (user_id, question, sources, created_at) VALUES (?,?,?,?)",
        (user["id"], body.question[:500], body.sources[:300], int(_t.time())),
    )  # 插入留痕（截断防超长）
    conn.commit()  # 提交
    conn.close()  # 关连接
    return ok({"id": cur.lastrowid})  # 返回
