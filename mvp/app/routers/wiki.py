# -*- coding: utf-8 -*-
"""Wiki（知识图谱）路由：输出 ECharts 可用的节点与边。

图谱结构：
- 节点 = 知识条目（按层级过滤：普通用户只看到自己可见的条目）+ 六个分类枢纽节点；
- 边 = 条目→分类（"属于"）+ 条目↔条目（kb_links 里维护的"依据/触发/支撑"等关系）。
"""

from fastapi import APIRouter, Depends  # 路由与依赖

from ..core import ok  # 统一返回
from ..db import get_conn  # 数据库
from ..deps import get_current_user  # 登录态

router = APIRouter(prefix="/api/wiki", tags=["wiki"])  # Wiki 路由

CATEGORIES = ["等待口径", "队列规则", "异常处理", "转人工", "数据红线", "权限角色"]  # 分类清单（与种子数据一致）


@router.get("/graph")
def wiki_graph(user: dict = Depends(get_current_user)):
    """输出当前用户可见的知识图谱（节点 + 边）。

    入参：登录态。
    出参：统一结构，data = {nodes, links, categories}。
    失败时的行为：未登录 401。
    """
    tier = 3 if user["role"] == "admin" else user["tier"]  # 管理员视为最高层级
    conn = get_conn()  # 取连接
    entries = conn.execute(
        "SELECT id, title, category, tier_required FROM kb_entries WHERE tier_required <= ?",
        (tier,),
    ).fetchall()  # 可见条目
    links = conn.execute("SELECT from_id, to_id, relation FROM kb_links").fetchall()  # 全部关系边
    conn.close()  # 关连接
    visible_ids = {r["id"] for r in entries}  # 可见条目 id 集合
    nodes = []  # 节点列表
    for cat in CATEGORIES:  # 分类枢纽节点
        nodes.append({
            "name": cat, "category": CATEGORIES.index(cat), "symbolSize": 46, "isCategory": True,
        })  # 分类节点大一号
    for r in entries:  # 条目节点
        cat = r["category"] if r["category"] in CATEGORIES else CATEGORIES[-1]  # 未知分类归入最后一组
        nodes.append({
            "name": r["title"], "category": CATEGORIES.index(cat),
            "symbolSize": 22 + min(len(r["title"]), 10),  # 标题越长节点稍大
            "tier_required": r["tier_required"],  # 供前端打层级徽标
            "id": r["id"], "isCategory": False,
        })  # 条目节点
    edges = []  # 边列表
    for r in entries:  # 条目→分类（属于）
        cat = r["category"] if r["category"] in CATEGORIES else CATEGORIES[-1]  # 分类名
        edges.append({"source": r["title"], "target": cat, "relation": "属于"})  # 属于边
    for lk in links:  # 条目↔条目（仅保留两端都可见的边）
        if lk["from_id"] in visible_ids and lk["to_id"] in visible_ids:  # 两端可见
            edges.append({"source": _title_of(entries, lk["from_id"]),
                          "target": _title_of(entries, lk["to_id"]),
                          "relation": lk["relation"]})  # 关系边
    return ok({"nodes": nodes, "links": edges, "categories": CATEGORIES})  # 返回


def _title_of(entries, eid: int) -> str:
    """按 id 找条目标题（图谱边用标题做节点名）。

    入参：entries —— 条目列表；eid —— 条目 id。
    出参：str —— 标题，找不到返回空串。
    失败时的行为：无失败路径。
    """
    for r in entries:  # 线性查找（条目量小，够用）
        if r["id"] == eid:  # 命中
            return r["title"]  # 返回标题
    return ""  # 找不到
