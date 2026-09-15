from __future__ import annotations

import os
from dataclasses import dataclass
from os import PathLike
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict

from dotenv import load_dotenv


class LLMFunction(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    arguments: str


class LLMToolCall(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    type: str = "function"
    function: LLMFunction


class LLMMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    role: str = "assistant"
    content: str | None = None
    refusal: str | None = None
    tool_calls: list[LLMToolCall] | None = None

    # DeepSeek thinking 模式可能返回。
    # 当前关闭 thinking，但保留字段，避免以后再改 schema。
    reasoning_content: str | None = None


class LLMChoice(BaseModel):
    model_config = ConfigDict(extra="ignore")

    index: int = 0
    finish_reason: str | None = None
    message: LLMMessage


class LLMUsage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


class LLMCompletion(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str | None = None
    model: str | None = None
    choices: list[LLMChoice]
    usage: LLMUsage | None = None


Provider = Literal["zhipu", "deepseek"]


class LLMClient:
    """统一的 OpenAI-compatible Chat Completions 客户端。"""

    def __init__(
        self,
        *,
        provider: Provider,
        api_key: str,
        timeout: float,
        transport=None,
    ):
        self.provider: Provider = provider

        if provider == "zhipu":
            base_url = "https://open.bigmodel.cn/api/paas/v4/"
        elif provider == "deepseek":
            base_url = "https://api.deepseek.com/"
        else:
            raise ValueError(f"不支持的 LLM provider：{provider}")

        self._http = httpx.AsyncClient(
            base_url=base_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=timeout,
            transport=transport,
        )

    async def __aenter__(self):
        await self._http.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        await self._http.__aexit__(
            exc_type,
            exc_value,
            traceback,
        )

    def _prepare_payload(
        self,
        kwargs: dict[str, Any],
    ) -> dict[str, Any]:
        payload = dict(kwargs)

        if self.provider == "deepseek":
            # DeepSeek 当前默认开启 thinking。
            # 你的 Agent 暂时没有回传 reasoning_content，
            # 所以这里显式关闭。
            payload.setdefault(
                "thinking",
                {"type": "disabled"},
            )

        return payload

    async def create(self, **kwargs) -> LLMCompletion:
        payload = self._prepare_payload(kwargs)

        response = await self._http.post(
            "chat/completions",
            json=payload,
        )

        response.raise_for_status()

        return LLMCompletion.model_validate(
            response.json()
        )


@dataclass(frozen=True)
class LLMConfig:
    provider: Provider
    api_key: str
    model: str


def get_llm_config(env_path: str | PathLike[str]) -> LLMConfig | None:
    """读取 provider、对应密钥和模型名；配置不完整时返回 None。"""
    load_dotenv(env_path, override=False)

    provider = os.getenv(
        "LLM_PROVIDER",
        "deepseek",
    ).strip().lower()

    model = os.getenv(
        "MODEL_NAME",
        "",
    ).strip()

    if provider == "deepseek":
        api_key = os.getenv(
            "DEEPSEEK_API_KEY",
            "",
        ).strip()

    elif provider == "zhipu":
        api_key = os.getenv(
            "ZHIPU_API_KEY",
            "",
        ).strip()

    else:
        return None

    if not api_key or not model:
        return None

    return LLMConfig(
        provider=provider,
        api_key=api_key,
        model=model,
    )
