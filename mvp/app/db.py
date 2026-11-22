# -*- coding: utf-8 -*-
"""数据库层：SQLite 建表、连接、种子数据（管理员/分层用户/知识库/图谱关系）。

设计要点：
- 用标准库 sqlite3，不引入 ORM，部署环境零额外依赖。
- 知识条目带 tier_required（最低可见层级），实现"用户分层"的数据隔离。
- 管理员（SaaS 管理员）role=admin，可以看到和管理全部数据。
"""

import os  # 路径拼接
import sqlite3  # 标准库 SQLite 驱动
import time  # 时间戳

from .security import hash_password  # 密码哈希函数

# 数据库文件放在项目根目录 data/ 下
_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "clinic_kb.db")  # 数据库文件路径


def get_conn() -> sqlite3.Connection:
    """获取数据库连接。

    入参：无。
    出参：sqlite3.Connection —— 已开启外键的连接。
    失败时的行为：数据库文件损坏时抛出 sqlite3 异常，由上层兜底处理。
    """
    conn = sqlite3.connect(_DB_PATH)  # 建立连接
    conn.row_factory = sqlite3.Row  # 让查询结果可以按列名取值
    conn.execute("PRAGMA foreign_keys = ON")  # 开启外键约束
    return conn  # 返回连接


def init_db() -> None:
    """建表（幂等，重复执行不报错）。

    入参：无。
    出参：无。
    失败时的行为：SQL 错误直接抛出，应用拒绝启动。
    """
    os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)  # 确保 data 目录存在
    conn = get_conn()  # 取连接
    # 系统元数据表：存 token 签名密钥等
    conn.execute(
        "CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT NOT NULL)"
    )  # 元数据表
    # 用户表：role 区分管理员/普通用户，tier 是用户层级（1 普通用户 2 高级用户 3 内部用户）
    conn.execute(
        """CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            salt TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user',
            tier INTEGER NOT NULL DEFAULT 1,
            display_name TEXT NOT NULL DEFAULT '',
            created_at INTEGER NOT NULL
        )"""
    )  # 用户表
    # 知识条目表：tier_required 表示可见该条目所需的最低用户层级
    conn.execute(
        """CREATE TABLE IF NOT EXISTS kb_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            category TEXT NOT NULL,
            tier_required INTEGER NOT NULL DEFAULT 1,
            updated_at INTEGER NOT NULL
        )"""
    )  # 知识条目表
    # 知识关系表：Wiki 知识图谱的边（属于某分类 / 与某条目关联）
    conn.execute(
        """CREATE TABLE IF NOT EXISTS kb_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_id INTEGER NOT NULL REFERENCES kb_entries(id) ON DELETE CASCADE,
            to_id INTEGER NOT NULL REFERENCES kb_entries(id) ON DELETE CASCADE,
            relation TEXT NOT NULL
        )"""
    )  # 知识关系表
    # 问答留痕表：记录每次 RAG 问答的问题与引用来源，便于审计
    conn.execute(
        """CREATE TABLE IF NOT EXISTS chat_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            question TEXT NOT NULL,
            sources TEXT NOT NULL DEFAULT '',
            created_at INTEGER NOT NULL
        )"""
    )  # 问答留痕表
    conn.commit()  # 提交建表
    conn.close()  # 关闭连接


def _seed_users(conn: sqlite3.Connection) -> None:
    """写入演示账号（幂等）：1 个 SaaS 管理员 + 3 个分层用户。

    入参：conn —— 数据库连接。
    出参：无。
    失败时的行为：写入失败抛异常，启动终止。
    """
    now = int(time.time())  # 当前时间戳
    demo_users = [  # 演示账号清单：用户名/密码/角色/层级/显示名
        ("admin", "admin123", "admin", 3, "SaaS管理员"),
        ("user1", "123456", "user", 1, "普通用户"),
        ("user2", "123456", "user", 2, "高级用户"),
        ("user3", "123456", "user", 3, "内部用户"),
    ]
    for username, pwd, role, tier, display in demo_users:  # 逐个写入
        row = conn.execute(
            "SELECT id FROM users WHERE username = ?", (username,)
        ).fetchone()  # 查重
        if row:  # 已存在则跳过，保证幂等
            continue  # 跳过
        pw_hash, salt = hash_password(pwd)  # 计算密码哈希与盐
        conn.execute(
            "INSERT INTO users (username, password_hash, salt, role, tier, display_name, created_at) VALUES (?,?,?,?,?,?,?)",
            (username, pw_hash, salt, role, tier, display, now),
        )  # 插入用户


def _seed_kb(conn: sqlite3.Connection) -> None:
    """写入门诊业务知识种子数据（幂等）：13 条知识 + 分类归属 + 关联关系。

    入参：conn —— 数据库连接。
    出参：无。
    失败时的行为：写入失败抛异常，启动终止。
    """
    count = conn.execute("SELECT COUNT(*) AS c FROM kb_entries").fetchone()["c"]  # 现有条目数
    if count > 0:  # 已有数据则不重复写，保证幂等
        return  # 跳过
    now = int(time.time())  # 当前时间戳
    entries = [  # (标题, 内容, 分类, 最低可见层级)
        ("三套等待时间口径",
         "门诊等待时间同时存在三套口径：①预约口径——从患者预约时段起算的等待；②现场口径——从签到/取号时刻起算的候诊等待；③系统口径——HIS 系统内记录的叫号间隔。三套口径数字不同是正常现象，对外解释时必须同时展示并标注口径来源与最后同步时间，避免患者拿不同口径的数字对质引发争议。",
         "等待口径", 1),
        ("候诊等待改善目标",
         "东湖门诊中心业务现状：虽然预约率高，但因迟到患者与现场加号混队，候诊等待中位数约 68 分钟。系统改善目标是把中位数压缩到 40 分钟以内。改善手段不是加快叫号，而是让队列信息透明、减少次序争议与护士的重复解释。",
         "等待口径", 1),
        ("队列次序规则",
         "队列次序基本原则：预约患者按预约时段排序；迟到患者排入同类别队列的当前时段之后，不插队到已等候患者之前；现场加号排在同类别预约患者之后。系统只读展示队列信息并给出辅助建议，不自动修改次序，任何次序调整都必须由对应岗位人工确认后生效。",
         "队列规则", 1),
        ("迟到患者处理",
         "迟到患者的定义：超过预约时段仍未签到的患者。处理规则：迟到患者到院后插入当前时段队列末尾，不占用已按时候诊患者的位置；导诊护士负责向患者解释排位依据，系统提供排位依据的原始记录（预约时段、签到时间）以支撑解释，减少口头争议。",
         "队列规则", 1),
        ("现场加号处理",
         "现场加号由医生或分诊台按需开出，加号患者排在同类别预约患者之后依次就诊。加号数量与顺序由排班管理员核对登记；系统对加号只做展示与排序建议，不生成、不撤销加号本身。加号记录须带原始登记时间，便于审计追溯。",
         "队列规则", 2),
        ("排班快照机制",
         "排班数据以只读快照方式接入，每天两次定时更新。当快照更新中断时，系统沿用上一份快照并在界面上明确标注\"暂未更新\"，不得静默使用过期数据而不提示。快照带时间戳，任何建议输出都须附带数据同步时间，让使用者判断新鲜度。",
         "异常处理", 2),
        ("异常检测与暂停建议",
         "异常检测智能体识别以下情形：排班快照未按时更新、队列版本冲突、数据缺失或校验失败。识别到异常时系统输出\"暂停建议\"并进入人工修复队列，错误结果不得覆盖原记录；修复完成后由工程师或排班管理员确认解除暂停。",
         "异常处理", 2),
        ("急症转人工红线",
         "急症识别是最高优先级红线：一旦对话或信息中出现急症症状（胸痛、呼吸困难、意识障碍等），必须 100% 转人工处理，预约顺序永不置于临床优先级之上。任何自动化建议都不得延迟急症患者的临床处置。",
         "转人工", 1),
        ("转人工留痕三要素",
         "每次转人工必须完整记录三要素：触发原因（急症/缺依据/版本冲突/系统不可用）、接手人（具体岗位与姓名）、确认时间（对方确认才算交接完成）。三要素缺失的转工单视为无效交接，审计时按不合格处理。",
         "转人工", 1),
        ("患者数据脱敏红线",
         "患者姓名、证件号、联系方式等隐私字段一律不入库、不进入任何模型输入，系统内只允许出现脱敏编号（如 MZ2026-0001）。排查数据问题时也必须使用脱敏编号关联，禁止通过真实身份反查系统记录。",
         "数据红线", 3),
        ("审计留痕六字段",
         "每次系统建议必须保留六个审计字段：业务编号、资料版本、事实引用、建议结果、人工改动、签核人。审计日志支持重建完整处理链，留存 90 天，期满由医疗质控专员复核后删除或归档。禁止记录口令与不必要的个人信息。",
         "数据红线", 2),
        ("六角色权限矩阵",
         "系统设六个角色：导诊护士（查看建议、确认放行）、排班管理员（校核、分派异常）、门诊运营主任（定范围、验收）、门诊系统工程师（维护只读接口）、患者服务主管（受理争议）、医疗质控专员（审计查询、否决上线）。禁止借用账号，只有授权岗位可看号源、排班、签到叫号时间与分诊规则。",
         "权限角色", 2),
        ("系统定位与边界",
         "本系统是门诊预约与分诊的协作辅助系统，不是分诊诊断系统。只做三类事：时间解释（三套口径透明展示）、队列信息辅助（谁迟到、谁加号、该排哪）、异常提示与暂停。不做：自动改队列次序、分诊诊断、调整医嘱、对外承诺结果，所有最终放行由对应岗位人工确认。",
         "权限角色", 1),
    ]
    id_map = {}  # 标题 -> 自增 id 的映射，供关系表引用
    for title, content, category, tier in entries:  # 逐条写入
        cur = conn.execute(
            "INSERT INTO kb_entries (title, content, category, tier_required, updated_at) VALUES (?,?,?,?,?)",
            (title, content, category, tier, now),
        )  # 插入条目
        id_map[title] = cur.lastrowid  # 记录 id
    # 分类归属边（属于）+ 条目关联边（关联/触发/依据）
    links = [  # (from标题, to标题, 关系)
        ("迟到患者处理", "队列次序规则", "依据"),
        ("现场加号处理", "队列次序规则", "依据"),
        ("排班快照机制", "异常检测与暂停建议", "触发"),
        ("异常检测与暂停建议", "转人工留痕三要素", "触发"),
        ("急症转人工红线", "转人工留痕三要素", "依据"),
        ("患者数据脱敏红线", "审计留痕六字段", "互补"),
        ("三套等待时间口径", "系统定位与边界", "支撑"),
        ("六角色权限矩阵", "系统定位与边界", "约束"),
        ("候诊等待改善目标", "三套等待时间口径", "量化"),
    ]  # 关联关系
    categories = ["等待口径", "队列规则", "异常处理", "转人工", "数据红线", "权限角色"]  # 六大分类
    for title, tid in id_map.items():  # 每个条目连向其分类
        pass  # 分类节点在图谱接口动态生成，无需建虚拟条目
    for a, b, rel in links:  # 写入条目间关系
        conn.execute(
            "INSERT INTO kb_links (from_id, to_id, relation) VALUES (?,?,?)",
            (id_map[a], id_map[b], rel),
        )  # 插入关系
    conn.commit()  # 提交


def seed_all() -> None:
    """初始化全部种子数据（幂等）：演示账号 + 知识库 + 关系。

    入参：无。
    出参：无。
    失败时的行为：失败抛异常，应用拒绝启动。
    """
    conn = get_conn()  # 取连接
    _seed_users(conn)  # 用户种子
    _seed_kb(conn)  # 知识种子
    conn.close()  # 关闭连接
