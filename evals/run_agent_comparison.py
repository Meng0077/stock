"""D08：同一个 case 分别运行 Manual Agent 和 LangChain Agent，打印流程摘要。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from langchain.messages import AIMessage, ToolMessage
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel

from stock_agent.agents.langchain.langchain_agent import build_langchain_agent

if __package__:
    from .run_basic_cases import load_agent, load_cases, run_case
else:
    from run_basic_cases import load_agent, load_cases, run_case


ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "evals" / "basic_cases.jsonl"

CASE_IDS = ("D05-02", "D05-06", "D05-07", "D05-10")


class ScriptedToolModel(FakeMessagesListChatModel):
    """让 FakeMessagesListChatModel 支持 LangChain Agent 的 bind_tools。"""

    def bind_tools(self, tools, **kwargs):
        return self


def load_comparison_cases():
    cases = load_cases(DATASET)

    return [
        case
        for case in cases
        if case["case_id"] in CASE_IDS
    ]


async def run_manual(case):
    """运行 Manual Agent。"""

    return await run_case(
        case,
        "offline",
        load_agent(),
    )


def build_scripted_responses(case):
    """把 D05 scripted response 转成 LangChain AIMessage。"""

    responses = []

    for item in case["scripted_responses"]:

        if item["finish_reason"] == "tool_calls":

            responses.append(
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": call["name"],
                            "args": call["arguments"],
                            "id": call["id"],
                        }
                        for call in item["tool_calls"]
                    ],
                )
            )

        else:

            content = item["content"]

            responses.append(
                AIMessage(
                    content=(
                        content
                        if isinstance(content, str)
                        else json.dumps(content, ensure_ascii=False)
                    )
                )
            )

    return responses


async def run_langchain(case):
    """运行 LangChain Agent。"""

    model = ScriptedToolModel(
        responses=build_scripted_responses(case)
    )

    agent = build_langchain_agent(model)
    
    input_state = {
        "messages": [
            {
                "role": "user",
                "content": json.dumps(
                    case["input"],
                    ensure_ascii=False,
                ),
            }
        ]
    }
    
    state = input_state
    
    try:
        async for state in agent.astream(
            state,
            {"recursion_limit": 6},
            stream_mode="values",
        ):
            pass

        status = "returned"
        error = None

    except Exception as exc:
        status = "error"
        error = type(exc).__name__
    return {
        "status": status,
        "messages": state["messages"],
        "error": error,}


def summarize_manual(run):
    """提取 Manual Agent 的关键流程。"""

    events = run["events"]

    return {
        "status": run["terminal_status"],
        "error": (run["safe_error"] or {}).get("code"),
        "tool_order": [
            event["tool"]
            for event in events
            if event.get("type") == "tool_requested"
        ],
        "tool_results": [
            event["type"]
            for event in events
            if event.get("type") in (
                "tool_succeeded",
                "tool_failed",
            )
        ],
        "message_types": [
            message["role"]
            for message in run["messages"]
        ],
    }


def summarize_langchain(state):
    """提取 LangChain Agent 的关键流程。"""

    messages = state["messages"]

    return {
        "status": state["status"],
        "error": state["error"],
        "tool_order": [
            call["name"]
            for message in messages
            if isinstance(message, AIMessage)
            for call in message.tool_calls
        ],
        "tool_results": [
            message.status
            for message in messages
            if isinstance(message, ToolMessage)
        ],
        "message_types": [
            type(message).__name__
            for message in messages
        ],
    }


async def compare_case(case):

    manual = await run_manual(case)

    langchain = await run_langchain(case)

    return {
        "case_id": case["case_id"],
        "manual": summarize_manual(manual),
        "langchain": summarize_langchain(langchain),
    }


async def main():

    cases = load_comparison_cases()

    results = []

    for case in cases:
        results.append(
            await compare_case(case)
        )

    print(
        json.dumps(
            results,
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
