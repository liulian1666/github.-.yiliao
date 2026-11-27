import unittest  # 使用标准库测试，不增加测试框架依赖
from fastapi.testclient import TestClient  # 直接验证真实路由响应
from starlette.exceptions import HTTPException  # 验证框架异常及响应头
from app.main import create_app  # 每次构建独立应用
from app.core.response import AppError  # 确保原业务异常兼容

class ErrorResponseTests(unittest.TestCase):  # 覆盖统一错误返回契约
    def setUp(self):  # 每个用例独立装配
        """无入参；创建客户端，装配失败时测试直接报错；不运行启动事件或写入数据库。"""
        self.app = create_app()  # 仅测试无需数据库的错误路径
        self.client = TestClient(self.app, raise_server_exceptions=False)  # 观察真实500响应

    def tearDown(self):  # 关闭客户端资源
        """无入参、无返回值；关闭失败时由测试框架报告。"""
        self.client.close()  # 不启动种子初始化

    def assert_error(self, response, status, code):  # 复用公开契约断言
        """入参为响应、预期状态与错误码；无返回值，契约不一致时断言失败。"""
        self.assertEqual(response.status_code, status)  # 保留HTTP语义
        body = response.json()  # 检查序列化后的实际内容
        self.assertEqual(set(body), {"ok", "data", "error"})  # 三键固定
        self.assertIs(body["ok"], False)  # 明确失败
        self.assertIsNone(body["data"])  # 错误响应没有业务数据
        self.assertEqual(body["error"]["code"], code)  # 稳定可判断的错误码
        self.assertIsInstance(body["error"]["msg"], str)  # 中文提示保持字符串

    def test_missing_login_field(self):  # 缺少口令
        """无入参、无返回值；缺字段未返回统一422时失败。"""
        self.assert_error(self.client.post("/api/auth/login", json={"username": "example"}), 422, "REQ_001")  # 不触发数据库查询

    def test_invalid_password_not_echoed(self):  # 验证敏感输入不回显
        """无入参、无返回值；口令被回显或类型错误契约不符时失败。"""
        response = self.client.post("/api/auth/login", json={"username": "example", "password": {"secret": "DO_NOT_ECHO"}})  # 故意发送错误类型
        self.assert_error(response, 422, "REQ_001")  # 参数错误统一包装
        self.assertNotIn("DO_NOT_ECHO", response.text)  # 不返回Pydantic错误中的input字段

    def test_malformed_json(self):  # JSON语法错误
        """无入参、无返回值；无效JSON未返回统一422时失败。"""
        self.assert_error(self.client.post("/api/auth/login", content="{", headers={"Content-Type": "application/json"}), 422, "REQ_001")  # 不包含原始请求体

    def test_not_found(self):  # 路径不存在
        """无入参、无返回值；404契约不符时失败。"""
        self.assert_error(self.client.get("/api/missing-route"), 404, "HTTP_404")  # 捕获Starlette层异常

    def test_method_not_allowed_preserves_allow(self):  # 请求方法错误
        """无入参、无返回值；405契约或Allow响应头缺失时失败。"""
        response = self.client.get("/api/auth/login")  # 登录仅支持POST
        self.assert_error(response, 405, "HTTP_405")  # 不能吞成500或200
        self.assertIn("POST", response.headers.get("allow", ""))  # 保留协议要求的响应头

    def test_http_headers_and_private_detail(self):  # 测试带自定义头的HTTP异常
        """无入参、无返回值；挑战头丢失或内部错误详情外泄时失败。"""
        @self.app.get("/test-http-error")  # 此路由只存在于测试应用
        def http_error():  # 构造独立异常
            """无入参、无返回值；始终抛出带认证头的401异常。"""
            raise HTTPException(401, "PRIVATE_DETAIL", headers={"WWW-Authenticate": "Bearer"})  # 模拟认证中间层
        response = self.client.get("/test-http-error")  # 读取处理结果
        self.assert_error(response, 401, "HTTP_401")  # 保持状态
        self.assertEqual(response.headers["www-authenticate"], "Bearer")  # 保留认证语义
        self.assertNotIn("PRIVATE_DETAIL", response.text)  # 不将任意内部detail公开

    def test_existing_business_error(self):  # 原业务异常仍正常
        """无入参、无返回值；原有业务错误行为发生变化时失败。"""
        @self.app.get("/test-business-error")  # 不访问真实数据库
        def business_error():  # 模拟业务拒绝
            """无入参、无返回值；始终抛出业务权限异常。"""
            raise AppError("AUTH_003", "无权访问", status=403)  # 保持原错误码
        self.assert_error(self.client.get("/test-business-error"), 403, "AUTH_003")  # 兼容已实现业务

    def test_unexpected_error(self):  # 原兜底仍正常
        """无入参、无返回值；意外异常未安全返回500时失败。"""
        @self.app.get("/test-crash")  # 仅测试用故障路由
        def crash():  # 模拟未知故障
            """无入参、无返回值；始终抛出测试运行异常。"""
            raise RuntimeError("PRIVATE_STACK_DETAIL")  # 不应返回给客户端
        response = self.client.get("/test-crash")  # 禁止测试客户端重抛
        self.assert_error(response, 500, "SYS_001")  # 保留已有兜底
        self.assertNotIn("PRIVATE_STACK_DETAIL", response.text)  # 堆栈只能在服务端

if __name__ == "__main__":  # 支持直接执行
    unittest.main()  # 测试失败时退出码非零
