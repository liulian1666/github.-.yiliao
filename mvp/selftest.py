# -*- coding: utf-8 -*-
"""本地自测脚本：全接口冒烟测试，结果写入 selftest_result.txt（UTF-8）。"""
import json
import urllib.request

BASE = "http://127.0.0.1:8765"
out = []


def req(method, path, body=None, token=None):
    """发起 HTTP 请求，返回 (状态码, 响应dict)。"""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method)
    r.add_header("Content-Type", "application/json")
    if token:
        r.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(r) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def check(name, cond, detail=""):
    out.append(("PASS " if cond else "FAIL ") + name + (" | " + detail if detail else ""))


# 1. 健康检查
s, j = req("GET", "/api/health")
check("health", s == 200 and j.get("ok") is True)

# 2. 管理员登录
s, j = req("POST", "/api/auth/login", {"username": "admin", "password": "admin123"})
check("admin login", s == 200 and j["ok"] and j["data"]["user"]["role"] == "admin")
admin_token = j["data"]["token"]

# 3. 错误密码
s, j = req("POST", "/api/auth/login", {"username": "admin", "password": "wrong"})
check("bad password 401", s == 401 and j["error"]["code"] == "AUTH_011")

# 4. me
s, j = req("GET", "/api/auth/me", token=admin_token)
check("me", s == 200 and j["data"]["username"] == "admin")

# 5. 无 Token 访问
s, j = req("GET", "/api/kb/list")
check("no token 401", s == 401 and j["error"]["code"] == "AUTH_001")

# 6. 管理员知识库全量
s, j = req("GET", "/api/kb/list", token=admin_token)
admin_count = len(j["data"])
check("admin kb all", s == 200 and admin_count == 13, f"count={admin_count}")

# 7. 三个层级用户登录与可见条目数
tier_counts = {}
tier_tokens = {}
for u in ("user1", "user2", "user3"):
    s, j = req("POST", "/api/auth/login", {"username": u, "password": "123456"})
    tier_tokens[u] = j["data"]["token"]
    tier_counts[u] = j["data"]["user"]["tier"]
    s2, j2 = req("GET", "/api/kb/list", token=j["data"]["token"])
    tier_counts[u + "_kb"] = len(j2["data"])
check("user1 tier1 kb=7", tier_counts["user1"] == 1 and tier_counts["user1_kb"] == 7, f"user1_kb={tier_counts['user1_kb']}")
check("user2 tier2 kb=12", tier_counts["user2"] == 2 and tier_counts["user2_kb"] == 12, f"user2_kb={tier_counts['user2_kb']}")
check("user3 tier3 kb=13", tier_counts["user3"] == 3 and tier_counts["user3_kb"] == 13, f"user3_kb={tier_counts['user3_kb']}")

# 8. RAG 检索（user1 问急症红线，应命中急症条目）
s, j = req("POST", "/api/rag/search", {"query": "急症患者应该怎么处理，转人工的红线是什么"}, token=tier_tokens["user1"])
titles = [c["title"] for c in j["data"]["chunks"]]
check("rag search hits", s == 200 and "急症转人工红线" in titles, "hits=" + ",".join(titles[:3]))

# 9. 普通用户访问管理员接口
s, j = req("GET", "/api/admin/users", token=tier_tokens["user1"])
check("user blocked from admin", s == 403 and j["error"]["code"] == "AUTH_004")

# 10. 知识图谱
s, j = req("GET", "/api/wiki/graph", token=tier_tokens["user1"])
n_nodes = len(j["data"]["nodes"])
n_links = len(j["data"]["links"])
check("wiki graph", s == 200 and n_nodes > 10 and n_links > 10, f"nodes={n_nodes} links={n_links}")

# 11. 管理员创建用户并重置层级（时间戳用户名保证可重复执行）
import time as _time  # 时间戳
stu_name = "stu%05d" % (int(_time.time()) % 100000)  # 唯一用户名
s, j = req("POST", "/api/admin/users/create", {"username": stu_name, "password": "abc12345", "role": "user", "tier": 1}, token=admin_token)
new_uid = j["data"]["id"]
s, j = req("POST", "/api/admin/users/update", {"id": new_uid, "tier": 2}, token=admin_token)
s, j = req("POST", "/api/auth/login", {"username": stu_name, "password": "abc12345"})
check("create user + update tier + login", s == 200 and j["data"]["user"]["tier"] == 2)

# 12. 管理员新增知识条目（层级3）后 user1 仍不可见
s, j = req("POST", "/api/kb/create", {"title": "自测条目XYZ", "content": "自测内容，用于验证分层可见性。", "category": "测试", "tier_required": 3}, token=admin_token)
new_kb = j["data"]["id"]
s, j = req("GET", "/api/kb/list", token=tier_tokens["user1"])
check("tier3 entry hidden from user1", all(e["title"] != "自测条目XYZ" for e in j["data"]))
s, j = req("GET", "/api/kb/list", token=tier_tokens["user3"])
check("tier3 entry visible to user3", any(e["title"] == "自测条目XYZ" for e in j["data"]))

# 13. 删除自测条目
s, j = req("POST", "/api/kb/delete", {"id": new_kb}, token=admin_token)
check("kb delete", s == 200 and j["ok"])

# 14. 问答留痕
s, j = req("POST", "/api/rag/log", {"question": "测试问题", "sources": "测试来源"}, token=tier_tokens["user1"])
check("rag log", s == 200 and j["ok"])
s, j = req("GET", "/api/admin/chatlogs", token=admin_token)
check("chatlogs visible to admin", s == 200 and len(j["data"]) >= 1)

# 15. 静态首页（返回 HTML，不走 JSON 解析）
s2 = 0
try:
    with urllib.request.urlopen(BASE + "/") as resp:
        s2 = resp.status  # 记录状态码
        html_ok = b"<title>" in resp.read()  # 简单确认是 HTML 页面
except Exception:
    html_ok = False
check("static index", s2 == 200 and html_ok, f"status={s2}")
out.append("INDEX_STATUS=" + str(s2))

import os  # 路径处理
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "selftest_result.txt"), "w", encoding="utf-8") as f:
    f.write("\n".join(out))
print("done")
