"""共享的离线预览格式化函数。"""

import json


def format_preview(data: object) -> str:
    """将预览数据转成易读 JSON；入参为可序列化数据，返回字符串。"""
    return json.dumps(data, ensure_ascii=False, indent=2)
