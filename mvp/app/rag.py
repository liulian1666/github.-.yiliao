# -*- coding: utf-8 -*-
"""RAG 检索层：纯 Python 实现的轻量检索（字符二元组重叠 + 关键词加权）。

不做向量数据库（部署环境无额外服务），检索质量对课程 MVP 演示足够：
- 中文按相邻字符组成 bigram，统计查询与文档的重叠度；
- 标题命中加权、查询词在原文出现次数加权；
- 只在当前用户层级可见的条目内检索（权限过滤前置到检索入口）。
"""

import re  # 清洗标点


def _clean(text: str) -> str:
    """去掉空白与标点，只保留参与匹配的字符。

    入参：text —— 任意文本。
    出参：str —— 清洗后的文本。
    失败时的行为：无失败路径。
    """
    return re.sub(r"[\s，。；：\"\"''（）()、,.;:!?！？—\-]", "", text)  # 正则去除空白与常见中英标点


def _bigrams(text: str) -> set:
    """把文本拆成字符二元组集合。

    入参：text —— 清洗后的文本。
    出参：set —— bigram 集合。
    失败时的行为：无失败路径。
    """
    t = _clean(text)  # 先清洗
    if len(t) < 2:  # 太短
        return {t} if t else set()  # 单字也放进集合
    return {t[i:i + 2] for i in range(len(t) - 1)}  # 相邻两字成组


def score_entry(query: str, title: str, content: str) -> float:
    """计算查询与单条知识的匹配分。

    入参：query —— 用户问题；title —— 条目标题；content —— 条目内容。
    出参：float —— 得分，越高越相关。
    失败时的行为：无失败路径。
    """
    q_grams = _bigrams(query)  # 查询 bigram
    if not q_grams:  # 空查询
        return 0.0  # 零分
    t_grams = _bigrams(title)  # 标题 bigram
    c_grams = _bigrams(content)  # 内容 bigram
    title_hit = len(q_grams & t_grams) / max(len(q_grams), 1)  # 标题重叠率
    content_hit = len(q_grams & c_grams) / max(len(q_grams), 1)  # 内容重叠率
    title_sub = 3.0 if _clean(title) in _clean(query) or _clean(query) in _clean(title) else 0.0  # 标题整串命中重奖
    keyword_bonus = sum(2.0 for kw in _split_keywords(query) if kw in content or kw in title)  # 关键词逐个加权
    return title_hit * 4.0 + content_hit * 2.0 + title_sub + keyword_bonus  # 合成总分


def _split_keywords(query: str) -> list:
    """把查询切成候选关键词（按常见连接词与标点切分，取 2-6 字片段）。

    入参：query —— 用户问题。
    出参：list —— 关键词列表。
    失败时的行为：无失败路径。
    """
    parts = re.split(r"[的了吗呢吧啊是与和或及对关于怎么怎样如何什么？?！!。，,；;：:\s]+", query)  # 切分
    return [p for p in parts if 2 <= len(p) <= 6]  # 只保留长度合适的片段


def search(query: str, entries: list, top_k: int = 4) -> list:
    """在给定条目集合内检索最相关的 top_k 条。

    入参：query —— 用户问题；entries —— [{id,title,content,category,tier_required}]（已按权限过滤）；
          top_k —— 返回条数。
    出参：list —— [{id,title,content,category,score}]，按得分降序。
    失败时的行为：无失败路径，无命中时返回空列表。
    """
    scored = []  # 打分结果
    for e in entries:  # 逐条打分
        s = score_entry(query, e["title"], e["content"])  # 计算得分
        if s > 0:  # 只要有分就候选
            scored.append({"id": e["id"], "title": e["title"], "content": e["content"],
                           "category": e["category"], "tier_required": e["tier_required"],
                           "score": round(s, 3)})  # 记录
    scored.sort(key=lambda x: x["score"], reverse=True)  # 降序
    return scored[:top_k]  # 取前 k 条
