# -*- coding: utf-8 -*-
"""安全层：密码哈希（PBKDF2）与 HMAC 签名 Token，全部用标准库实现。

- 密码绝不明文存储：PBKDF2-HMAC-SHA256 + 随机盐。
- Token = base64(payload) + "." + HMAC 签名，签名密钥首次启动时生成并存 meta 表。
"""

import base64  # payload 编码
import hashlib  # PBKDF2 哈希
import hmac  # 签名
import json  # payload 序列化
import os  # 随机盐/密钥
import time  # 过期时间

_TOKEN_TTL = 7 * 24 * 3600  # Token 有效期 7 天（秒）


def hash_password(password: str) -> tuple:
    """计算密码哈希。

    入参：password —— 明文密码。
    出参：(哈希hex, 盐hex)。
    失败时的行为：无失败路径。
    """
    salt = os.urandom(16)  # 生成随机盐
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000)  # 迭代 10 万次
    return digest.hex(), salt.hex()  # 返回哈希与盐（hex 存储）


def verify_password(password: str, salt_hex: str, expected_hex: str) -> bool:
    """校验密码是否匹配。

    入参：password —— 用户输入的明文；salt_hex —— 库里的盐；expected_hex —— 库里的哈希。
    出参：bool —— 是否匹配。
    失败时的行为：格式异常一律返回 False（不抛错，防时序探测只做常量比较）。
    """
    try:  # 防御性捕获格式错误
        salt = bytes.fromhex(salt_hex)  # 还原盐
        expected = bytes.fromhex(expected_hex)  # 还原期望哈希
    except ValueError:  # 格式错误
        return False  # 直接不匹配
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000)  # 重算哈希
    return hmac.compare_digest(digest, expected)  # 常量时间比较，防时序攻击


def _secret() -> str:
    """获取 Token 签名密钥（首次生成后持久化到 meta 表）。

    入参：无。
    出参：str —— 密钥。
    失败时的行为：数据库异常向上抛出。
    """
    from .db import get_conn  # 延迟导入，避免与 db.py 的循环依赖

    conn = get_conn()  # 取连接
    row = conn.execute("SELECT v FROM meta WHERE k = 'token_secret'").fetchone()  # 查密钥
    if row:  # 已有密钥
        conn.close()  # 关连接
        return row["v"]  # 直接用
    secret = os.urandom(32).hex()  # 生成新密钥
    conn.execute("INSERT INTO meta (k, v) VALUES ('token_secret', ?)", (secret,))  # 落库
    conn.commit()  # 提交
    conn.close()  # 关连接
    return secret  # 返回密钥


def issue_token(user_row) -> str:
    """为用户签发 Token。

    入参：user_row —— users 表的 sqlite3.Row。
    出参：str —— 签名 Token。
    失败时的行为：无失败路径。
    """
    payload = {  # 载荷只放必要字段，不放敏感信息
        "uid": user_row["id"],  # 用户 id
        "username": user_row["username"],  # 用户名
        "role": user_row["role"],  # 角色 admin/user
        "tier": user_row["tier"],  # 用户层级 1-3
        "exp": int(time.time()) + _TOKEN_TTL,  # 过期时间
    }
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")  # 序列化
    body = base64.urlsafe_b64encode(raw).decode("ascii")  # base64 编码
    sig = hmac.new(_secret().encode("ascii"), body.encode("ascii"), hashlib.sha256).hexdigest()  # HMAC 签名
    return f"{body}.{sig}"  # 拼成 token


def parse_token(token: str) -> dict | None:
    """解析并校验 Token。

    入参：token —— 客户端带来的 Token。
    出参：dict —— 载荷；无效/过期返回 None。
    失败时的行为：任何异常都返回 None（视为未登录），不抛错。
    """
    try:  # 防御性解析
        body, sig = token.split(".", 1)  # 拆分载荷与签名
        expect = hmac.new(_secret().encode("ascii"), body.encode("ascii"), hashlib.sha256).hexdigest()  # 重算签名
        if not hmac.compare_digest(sig, expect):  # 签名不一致说明被篡改
            return None  # 拒绝
        payload = json.loads(base64.urlsafe_b64decode(body.encode("ascii")))  # 还原载荷
        if payload.get("exp", 0) < time.time():  # 过期校验
            return None  # 过期视为无效
        return payload  # 返回载荷
    except Exception:  # 任何格式问题
        return None  # 统一视为未登录
