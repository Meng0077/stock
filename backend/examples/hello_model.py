"""D01：读取本地财报摘要，向智谱发送一次请求。"""

import argparse
import json
import logging
import math
import os
from pathlib import Path
import sys
from time import perf_counter

from dotenv import load_dotenv
from zai import ZhipuAiClient
from zai.core import APIStatusError, APITimeoutError

BACKEND = Path(__file__).resolve().parents[1]
SYSTEM_PROMPT = "你是财报阅读助手。仅依据用户提供的资料回答，区分事实、推断和缺失信息。"


def explain_api_error(error: APIStatusError) -> str:
    """只读取数字业务码，使用本地提示，不输出服务端原始文本。"""
    code = "未知"
    try:
        body = error.response.json()
        raw = str(body["error"]["code"])
        if raw.isascii() and raw.isdigit() and len(raw) <= 6:
            code = raw
    except (ValueError, KeyError, TypeError):
        pass
    hints = {
        "1113": "账户余额不足或无可用资源。请先在控制台核对当前模型、账户状态和免费模型可用条件。",
        "1302": "账户触发速率或并发限制。请停止其他调用，稍后单次重试，并查看模型并发额度。",
        "1305": "模型服务当前过载。请稍后重试。",
        "1308": "已达到使用上限。请在控制台查看额度和重置时间。",
        "1310": "已达到每周或每月使用上限。请查看重置时间。",
        "1311": "当前套餐未开放该模型权限。请核对 API 模型权限。",
    }
    fallback = (
        "请检查 API Key 是否有效。" if error.status_code == 401 else
        "请根据业务码核对平台错误说明；仅凭 HTTP 状态无法确定原因。"
    )
    return f"模型服务拒绝请求（HTTP {error.status_code}，业务码 {code}）：{hints.get(code, fallback)}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preview", action="store_true", help="只显示模型输入，不发送请求")
    parser.add_argument("--model", help="临时覆盖模型名称，可用于验证错误模型配置")
    args = parser.parse_args()
    # 禁止依赖库输出 HTTP 调试日志，避免凭据或原始错误泄露。
    logging.disable(logging.CRITICAL)

    # 1. 构造输入：文件包含财报摘要及问题；模型不会自动打开其中的链接。
    try:
        announcement = (BACKEND / "fixtures/nvda_2026_08_earnings.txt").read_text(encoding="utf-8")
        if not announcement.strip():
            raise ValueError
    except (OSError, UnicodeError, ValueError):
        print("输入错误：财报文件不存在、无法读取或为空。", file=sys.stderr)
        return 1
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": announcement},
    ]
    if args.preview:
        print(json.dumps(messages, ensure_ascii=False, indent=2))
        return 0

    # 本机环境变量优先于 .env；不打印密钥。
    load_dotenv(BACKEND / ".env", override=False)
    api_key = os.getenv("ZHIPU_API_KEY", "").strip()
    model = (args.model if args.model is not None else os.getenv("MODEL_NAME", "")).strip()
    if not api_key or not model:
        print("配置错误：请填写 backend/.env 中的 ZHIPU_API_KEY 和 MODEL_NAME。", file=sys.stderr)
        return 1
    try:
        timeout = float(os.getenv("MODEL_TIMEOUT_SECONDS", "30"))
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError
    except ValueError:
        print("配置错误：MODEL_TIMEOUT_SECONDS 必须是大于 0 的有限数字。", file=sys.stderr)
        return 1

    started = perf_counter()
    client = None
    try:
        # 2. 发送一次请求：关闭自动重试和深度思考，限制输出长度。
        client = ZhipuAiClient(api_key=api_key, timeout=timeout, max_retries=0)
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            thinking={"type": "disabled"},
            max_tokens=1200,
            stream=False,
        )
        # 3. 解析输出：只取最终回答，不输出模型内部推理。
        if not response.choices or not response.choices[0].message.content:
            print("响应错误：模型没有返回可用的正文。", file=sys.stderr)
            return 1
        choice = response.choices[0]
        print(choice.message.content.replace(api_key, "[REDACTED]"))
        print(f"结束原因: {choice.finish_reason}")
        print("\nToken 用量：")
        if response.usage is None:
            print("供应商未返回用量（不表示用量为零）。")
        else:
            for field in ("prompt_tokens", "completion_tokens", "total_tokens"):
                print(f"  {field}: {getattr(response.usage, field, None)}")
        if choice.finish_reason != "stop":
            print("回答未正常结束，可能已达到输出上限，请勿当作完整分析。", file=sys.stderr)
            return 1
        return 0
    # 4. 失败处理：不打印原始异常、请求头或密钥。
    except APITimeoutError:
        print("请求超时：请检查网络或增加超时配置；远端请求可能仍在执行。", file=sys.stderr)
        return 1
    except APIStatusError as error:
        print(error)
        # print(f"HTTP {error.status_code} 错误：{error.response.reason}", file=sys.stderr)
        print(explain_api_error(error), file=sys.stderr)
        return 1
    except Exception:
        print("调用失败：请检查网络和依赖版本；原始异常已隐藏以保护密钥。", file=sys.stderr)
        return 1
    finally:
        print(f"请求阶段耗时：{perf_counter() - started:.2f} 秒")
        if client is not None:
            client.close()


if __name__ == "__main__":
    raise SystemExit(main())
