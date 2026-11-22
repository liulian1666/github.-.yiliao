# -*- coding: utf-8 -*-
"""线上终验：会话 Cookie + X-Auth-Token 头，结果写 online_check.txt。"""
import http.cookiejar  # Cookie 管理
import json
import urllib.request
import urllib.error

BASE = "https://clinic-kb-mvp.app.workbuddy.host"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
out = []

cj = http.cookiejar.CookieJar()  # 会话 Cookie
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))  # 自动带 Cookie


def call(path, body=None, token=None):
    """带会话请求线上接口，返回 (状态码, 响应dict)。"""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    r = urllib.request.Request(BASE + path, data=data)
    r.add_header("User-Agent", UA)
    r.add_header("Content-Type", "application/json")
    if token:
        r.add_header("X-Auth-Token", token)  # 与前端一致的备用凭证头
    try:
        with opener.open(r, timeout=25) as resp:
            raw = resp.read().decode("utf-8", "ignore")  # 原始响应
            try:
                return resp.status, json.loads(raw)  # JSON 接口
            except Exception:
                return resp.status, {"_raw": raw[:100]}  # HTML 等非 JSON
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8"))
        except Exception:
            return e.code, {}


def check(name, cond, detail=""):
    out.append(("PASS " if cond else "FAIL ") + name + (" | " + detail if detail else ""))


s, j = call("/?sharecode=WBQBV5XJTL")
check("sharecode gate 200", s == 200, f"cookies={[c.name for c in cj]}")

s, j = call("/api/health")
check("health", s == 200 and j.get("ok") is True)

s, j = call("/api/auth/login", {"username": "admin", "password": "admin123"})
check("admin login", s == 200 and j.get("ok") is True)
tok = j["data"]["token"] if j.get("ok") else None

s, j = call("/api/auth/me", token=tok)
check("me via X-Auth-Token", s == 200 and j.get("data", {}).get("username") == "admin")

s, j = call("/api/rag/search", {"query": "迟到患者怎么排队"}, token=tok)
titles = [c["title"] for c in j.get("data", {}).get("chunks", [])]
check("rag search", s == 200 and len(titles) > 0, "hits=" + ",".join(titles[:3]))

s, j = call("/api/wiki/graph", token=tok)
check("wiki graph", s == 200 and len(j.get("data", {}).get("nodes", [])) > 10)

with open("online_check.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(out))
