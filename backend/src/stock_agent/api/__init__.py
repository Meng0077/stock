"""D06 FastAPI 请求/响应层。

实现顺序：
1. schemas.py：先完成 API 契约和跨字段校验。
2. agents/manual/manual_runner.py：把现有 Manual Agent 变成可调用函数。
3. dependencies.py：提供可被测试替换的 Agent runner。
4. app.py：最后连接 HTTP 路由，不在导入阶段访问网络。

本包只处理 HTTP 边界，不实现工具业务逻辑，不保存密钥，也不创建交易路径。
"""
