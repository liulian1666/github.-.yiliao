# -*- coding: utf-8 -*-
"""项目启动入口：读取 PORT 环境变量并启动 FastAPI 服务。

部署环境（线上沙箱）会注入 PORT 环境变量，本地默认 8000。
"""

import os  # 读取环境变量

import uvicorn  # ASGI 服务器

from app.main import app  # 引入装配好的 FastAPI 应用实例


if __name__ == "__main__":
    # 端口：线上用 PORT 环境变量，本地默认 8000
    port = int(os.environ.get("PORT", "8000"))  # 端口号
    # 必须绑定 0.0.0.0，线上反向代理才能访问到
    uvicorn.run(app, host="0.0.0.0", port=port)  # 启动服务
