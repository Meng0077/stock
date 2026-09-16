"""只读工具的预期业务错误。"""


class UnsupportedCompanyError(ValueError):
    """工具没有请求公司的教学数据；不是程序执行故障。"""
