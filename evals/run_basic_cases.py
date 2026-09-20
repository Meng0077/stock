"""D05 固定案例评估；默认离线，真实模型必须显式选择。"""

import argparse
import asyncio
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import importlib.util
import inspect
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace
import uuid

import httpx
from dotenv import load_dotenv
from pydantic import ValidationError
from stock_agent.llm_client import (
    LLMFunction,
    LLMMessage,
    LLMToolCall,
    get_llm_config,
)

from stock_agent.agents import tool_calling
from stock_agent.schemas.errors import PublicError
from stock_agent.tools import registry


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = ROOT / "evals" / "basic_cases.jsonl"
DEFAULT_RESULTS = ROOT / "evals" / "results"
AGENT_PATH = ROOT / "backend" / "examples" / "structured_agent.py"
PROMPT_VERSION = "d04-structured-v1"


def load_agent():
    """无入参；载入现有 D04 Agent，返回模块对象。"""
    spec = importlib.util.spec_from_file_location("d05_structured_agent", AGENT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("无法载入 D04 Agent")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_cases(path: Path) -> list[dict]:
    """读取 JSONL；入参为文件路径，返回唯一 ID 的案例列表。"""
    cases = []
    seen = set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            case = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"数据集第 {line_number} 行不是 JSON") from error
        if not isinstance(case, dict) or not isinstance(case.get("case_id"), str):
            raise ValueError(f"数据集第 {line_number} 行缺少 case_id")
        case_id = case["case_id"]
        if case_id in seen:
            raise ValueError(f"数据集第 {line_number} 行重复 case_id: {case_id}")
        if not isinstance(case.get("input"), dict) or not isinstance(case.get("expected"), dict):
            raise ValueError(f"数据集第 {line_number} 行缺少 input 或 expected")
        if not isinstance(case.get("scripted_responses"), list):
            raise ValueError(f"数据集第 {line_number} 行 scripted_responses 必须是列表")
        seen.add(case_id)
        cases.append(case)
    if not cases:
        raise ValueError("数据集没有案例")
    return cases


class ScriptedClient:
    """逐次返回固定模型消息；不会读取密钥或访问网络。"""

    def __init__(self, responses: list[dict]):
        self.responses = responses
        self.calls = 0

    async def create(self, **kwargs):
        if self.calls >= len(self.responses):
            raise ValueError("固定模型响应已用完")
        item = self.responses[self.calls]
        self.calls += 1
        if item["finish_reason"] == "tool_calls":
            calls = [
                LLMToolCall(
                    id=call["id"],
                    type="function",
                    function=LLMFunction(
                        name=call["name"],
                        arguments=json.dumps(
                            call["arguments"],
                            ensure_ascii=False,
                        ),
                    ),
                )
                for call in item["tool_calls"]
            ]

            message = LLMMessage(
                role="assistant",
                tool_calls=calls,
            )

        else:
            content = item["content"]

            message = LLMMessage(
                role="assistant",
                content=(
                    content
                    if isinstance(content, str)
                    else json.dumps(
                        content,
                        ensure_ascii=False,
                    )
                ),
            )

        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=message,
                    finish_reason=item["finish_reason"],
                )
            ],
            usage=None,
        )


class CountingClient:
    """包装真实客户端；只统计请求次数，不保存请求头。"""

    def __init__(self, client):
        self.client = client
        self.calls = 0

    async def create(self, **kwargs):
        self.calls += 1
        return await self.client.create(**kwargs)


@contextmanager
def offline_tool_spy(fault: str | None):
    """入参为故障类型；临时替换 handler，产出实际进入 handler 的计数。"""
    original = {name: info["handler"] for name, info in registry.TOOL_REGISTRY.items()}
    original_timeout = tool_calling.TOOL_TIMEOUT_SECONDS
    calls = {"count": 0}
    try:
        for name, handler in original.items():
            async def counted(company_id, *, _handler=handler):
                calls["count"] += 1
                if fault == "tool_timeout":
                    await asyncio.sleep(0.05)
                value = _handler(company_id)
                return await value if inspect.isawaitable(value) else value
            registry.TOOL_REGISTRY[name]["handler"] = counted
        if fault == "tool_timeout":
            tool_calling.TOOL_TIMEOUT_SECONDS = 0.005
        yield calls
    finally:
        for name, handler in original.items():
            registry.TOOL_REGISTRY[name]["handler"] = handler
        tool_calling.TOOL_TIMEOUT_SECONDS = original_timeout


def case_messages(agent, case: dict) -> list[dict]:
    """输入 Agent 和案例，返回该案例自己的消息列表。"""
    return [
        deepcopy(agent.messages[0]),
        {"role": "user", "content": json.dumps(case["input"], ensure_ascii=False)},
    ]


def code_version() -> str | None:
    result = subprocess.run(
        ["git", "describe", "--always", "--dirty"],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def source_hash() -> str:
    """返回评估主流程及工具代码的 SHA-256，补足未提交版本的标识。"""
    digest = hashlib.sha256()
    paths = (
        AGENT_PATH,
        Path(__file__),
        ROOT / "backend" / "src" / "stock_agent" / "agents" / "manual" / "manual_agent.py",
        ROOT / "backend" / "src" / "stock_agent" / "agents" / "tool_calling.py",
        ROOT / "backend" / "src" / "stock_agent" / "tools" / "registry.py",
    )
    for path in paths:
        digest.update(path.relative_to(ROOT).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def usage_from_events(events: list[dict]) -> dict | None:
    """输入事件列表；返回 token 合计，未知字段用 null。"""
    rows = [event["usage"] for event in events if event.get("type") == "model_usage"]
    if not rows:
        return None
    return {
        field: sum(row[field] for row in rows)
        if all(isinstance(row.get(field), int) for row in rows) else None
        for field in ("prompt_tokens", "completion_tokens", "total_tokens")
    }


def normalize_terminal(event: dict) -> str:
    if event.get("status") == "failed":
        return event.get("error", {}).get("code", "failed")
    return event.get("status", "missing")


def check_record(record: dict, expected: dict | None = None) -> list[str]:
    """检查可确定的规则；返回违规代码列表，不判断事实语义。"""
    errors = []
    events = record.get("events", [])
    terminals = [event for event in events if event.get("type") == "run_finished"]
    if len(terminals) != 1:
        return ["terminal_count"]
    terminal = terminals[0]
    run_id = record.get("run_id")
    if terminal.get("run_id") != run_id or any(
        event.get("run_id", run_id) != run_id for event in events
    ):
        errors.append("run_id_mismatch")
    if record.get("terminal_status") != normalize_terminal(terminal):
        errors.append("terminal_mismatch")
    if expected and record.get("terminal_status") != expected["terminal_status"]:
        errors.append("unexpected_terminal")
    if record.get("safe_error") != terminal.get("error"):
        errors.append("safe_error_mismatch")
    if (terminal.get("status") == "failed") != ("error" in terminal):
        errors.append("terminal_error_mismatch")
    if terminal.get("error"):
        try:
            PublicError.model_validate(terminal["error"])
        except ValidationError:
            errors.append("unsafe_error")
    requested = [event for event in events if event.get("type") == "tool_requested"]
    resolved = [
        event for event in events
        if event.get("type") in ("tool_succeeded", "tool_failed")
    ]
    requested_ids = [event["tool_call_id"] for event in requested]
    resolved_ids = [event["tool_call_id"] for event in resolved]
    if sorted(requested_ids) != sorted(resolved_ids) or len(requested_ids) != len(set(requested_ids)):
        errors.append("tool_call_id_mismatch")
    if record.get("model_request_count", 0) > record["budgets"]["model_rounds"]:
        errors.append("model_budget")
    if record.get("tool_execution_count", 0) > record["budgets"]["tool_calls"]:
        errors.append("tool_budget")
    observed_tool_count = max(
        (event.get("tool_calls_executed", 0) for event in events), default=0
    )
    if record.get("tool_execution_count") != observed_tool_count:
        errors.append("tool_execution_count_mismatch")
    if record.get("handler_call_count") is not None and record["handler_call_count"] > record["budgets"]["tool_calls"]:
        errors.append("handler_budget")
    allowed_ids = {item["id"] for item in record["input_snapshot"]["evidence"]}
    allowed_ids.update(
        event["evidence_id"] for event in events
        if event.get("type") == "tool_succeeded" and event.get("evidence_id")
    )
    output = record.get("final_output")
    if terminal.get("status") in ("completed", "insufficient_information") and output is None:
        errors.append("missing_final_output")
    if output is not None:
        if output.get("status") != terminal.get("status"):
            errors.append("output_status_mismatch")
        claims = output.get("facts", []) + output.get("inferences", [])
        expected_mode = record["input_snapshot"]["data_mode"] if claims else None
        if output.get("data_mode") != expected_mode:
            errors.append("data_mode_mismatch")
        for claim in output.get("facts", []) + output.get("inferences", []):
            if not set(claim.get("evidence_ids", [])) <= allowed_ids:
                errors.append("invalid_evidence")
                break
    if any(
        not isinstance(event.get("fixture_result"), dict)
        or event["fixture_result"].get("data_mode") != "fixture"
        for event in events if event.get("type") == "tool_succeeded"
    ):
        errors.append("fixture_mismatch")
    if record["execution_mode"] == "offline" and expected:
        if [event["tool"] for event in requested] != expected["tool_requests"]:
            errors.append("tool_requests")
        if [event["code"] for event in resolved if event["type"] == "tool_failed"] != expected["tool_failures"]:
            errors.append("tool_failures")
        if record["handler_call_count"] != expected["handler_calls"]:
            errors.append("handler_calls")
        if record["model_request_count"] != expected["model_requests"]:
            errors.append("model_requests")
    return errors


def set_terminal(agent, events: list[dict], run_id: str, code: str) -> None:
    """异常发生在清理阶段时，更新已有终态，避免一轮出现两个终态。"""
    for event in events:
        if event.get("type") == "run_finished":
            event["status"] = "failed"
            event["error"] = agent.make_public_error(code).model_dump()
            return
    agent.record_run_finished(events, run_id, "failed", code)


async def run_case(
    case: dict,
    mode: str,
    agent,
    *,
    api_key: str = "",
    model: str = "",
    provider: str = "",
) -> dict:
    """运行一个案例；输入案例/模式/Agent，返回可保存的安全结果。"""
    run_id = str(uuid.uuid4())
    initial = case_messages(agent, case)
    events: list[dict] = []
    sink: dict = {}
    handler_calls = None
    client = None
    started_at = datetime.now(timezone.utc).isoformat()
    started = time.perf_counter()
    if case.get("preparation_status") != "ready":
        agent.record_run_finished(events, run_id, "failed", "incomplete_response")
        verdict = "blocked"
    elif mode == "offline" and not case["scripted_responses"]:
        agent.record_run_finished(events, run_id, "failed", "incomplete_response")
        verdict = "blocked"
    elif mode == "real" and (
        not case.get("real_api_allowed")
        or not api_key
        or not model
        or not provider
    ):
        agent.record_run_finished(events, run_id, "failed", "model_error")
        verdict = "blocked"
    else:
        verdict = None
        try:
            if mode == "offline":
                client = ScriptedClient(case["scripted_responses"])
                with offline_tool_spy(case.get("fault")) as spy:
                    async with asyncio.timeout(agent.TASK_TIMEOUT_SECONDS):
                        await agent.model_loop(
                            client, "scripted", events=events,
                            initial_messages=initial,
                            initial_evidence_ids={e["id"] for e in case["input"]["evidence"]},
                            result_sink=sink, run_id=run_id,
                        )
                handler_calls = spy["count"]
            else:
                async with agent.LLMClient(
                    provider=provider,
                    api_key=api_key,
                    timeout=300.0,
                ) as real_client:
                    client = CountingClient(real_client)

                    async with asyncio.timeout(
                        agent.TASK_TIMEOUT_SECONDS
                    ):
                        await agent.model_loop(
                            client,
                            model,
                            events=events,
                            initial_messages=initial,
                            initial_evidence_ids={
                                e["id"]
                                for e in case["input"]["evidence"]
                            },
                            result_sink=sink,
                            run_id=run_id,
                        )
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            set_terminal(agent, events, run_id, "total_timeout")
        except httpx.TimeoutException:
            set_terminal(agent, events, run_id, "model_timeout")
        except Exception:
            set_terminal(agent, events, run_id, "model_error")
        if mode == "offline":
            handler_calls = spy["count"]
    terminal = next(event for event in events if event.get("type") == "run_finished")
    record = {
        "run_id": run_id,
        "case_id": case["case_id"],
        "dataset_version": case["dataset_version"],
        "execution_mode": mode,
        "started_at": started_at,
        "elapsed_seconds": round(time.perf_counter() - started, 6),
        "input_snapshot": deepcopy(case["input"]),
        "scripted_responses_snapshot": deepcopy(case["scripted_responses"]) if mode == "offline" else None,
        "messages": sink.get("messages", initial),
        "events": events,
        "final_output": sink.get("final_output"),
        "terminal_status": normalize_terminal(terminal),
        "safe_error": terminal.get("error"),
        "model_request_count": client.calls if client else 0,
        "tool_execution_count": max(
            (event.get("tool_calls_executed", 0) for event in events), default=0
        ),
        "handler_call_count": handler_calls,
        "usage": usage_from_events(events),
        "versions": {
            "code": code_version(),
            "source_sha256": source_hash(),
            "python": sys.version.split()[0],
            "llm_client": "internal-httpx",
            # "sdk": importlib.metadata.version("zai-sdk"),
            "httpx": importlib.metadata.version("httpx"),
            "model": model if mode == "real" else "scripted",
            "prompt": PROMPT_VERSION,
        },
        "budgets": {
            "model_rounds": agent.MAX_MODEL_ROUNDS,
            "tool_calls": agent.MAX_TOOL_CALLS,
            "output_tokens_per_request": agent.MAX_OUTPUT_TOKENS,
            "task_timeout_seconds": agent.TASK_TIMEOUT_SECONDS,
            "model_timeout_seconds": 300.0,
        },
        "request_options": {"response_format": {"type": "json_object"}},
        "automatic_verdict": None,
        "automatic_errors": [],
        "human_review": {"verdict": "pending", "reason": None},
    }
    if verdict == "blocked":
        record["automatic_verdict"] = "blocked"
        record["automatic_errors"] = ["case_not_ready"]
    else:
        errors = check_record(record, case["expected"])
        record["automatic_errors"] = errors
        record["automatic_verdict"] = "pass" if not errors else "fail"
    return record


async def run_selected(cases: list[dict], mode: str, agent, *, api_key="", model="", provider: str = "") -> list[dict]:
    """逐项运行；普通失败继续，整体取消向外传播。"""
    return [
        await run_case(case, mode, agent, api_key=api_key, model=model, provider=provider)
        for case in cases
    ]


def save_records(records: list[dict], output_dir: Path, mode: str) -> Path:
    """输入结果、目录和模式；独占新文件并返回路径。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    path = output_dir / f"d05-{mode}-{stamp}-{uuid.uuid4().hex[:8]}.jsonl"
    with path.open("x", encoding="utf-8") as file:
        for record in records:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")
    return path


def main(argv: list[str] | None = None) -> int:
    """解析命令、执行评估并保存结果；全部自动通过返回 0，否则 1。"""
    parser = argparse.ArgumentParser(description="D05 固定案例评估")
    parser.add_argument("--mode", choices=("offline", "real"), default="offline")
    parser.add_argument("--case", help="只运行指定 case_id")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_RESULTS)
    args = parser.parse_args(argv)
    try:
        cases = load_cases(args.dataset)
    except (OSError, ValueError) as error:
        print(f"数据集错误：{error}", file=sys.stderr)
        return 1
    if args.case:
        cases = [case for case in cases if case["case_id"] == args.case]
        if not cases:
            print("找不到指定案例。", file=sys.stderr)
            return 1
    provider = ""
    if args.mode == "real":
        cases = [case for case in cases if case.get("real_api_allowed")]
        if not cases:
            print("所选案例不允许真实模型请求。", file=sys.stderr)
            return 1
        load_dotenv(ROOT / "backend" / ".env", override=False)
        config = get_llm_config(ROOT / "backend" / ".env")
        if not config:
            print("LLM 配置错误。", file=sys.stderr,)
            return 1
        provider = config.provider
        api_key = config.api_key
        model = config.model
    else:
        api_key = model = ""
    agent = load_agent()
    try:
        records = asyncio.run(run_selected(cases, args.mode, agent, api_key=api_key, model=model, provider=provider))
    except asyncio.CancelledError:
        print("评估已取消。", file=sys.stderr)
        raise
    path = save_records(records, args.output_dir, args.mode)
    for record in records:
        print(f"{record['case_id']}: {record['automatic_verdict']} / {record['terminal_status']}")
    passed = sum(record["automatic_verdict"] == "pass" for record in records)
    blocked = sum(record["automatic_verdict"] == "blocked" for record in records)
    print(f"自动检查 {passed}/{len(records)} 通过，blocked {blocked}；人工复核均为 pending。")
    print(f"结果：{path}")
    return 0 if passed == len(records) else 1


if __name__ == "__main__":
    raise SystemExit(main())
