"""D04 Task 5：离线工具、局部超时与总时限。"""

import asyncio
import importlib.util
from pathlib import Path

import pytest


def load_example():
    module_path = Path(__file__).parents[1] / "examples" / "timeout_cancel.py"
    spec = importlib.util.spec_from_file_location("timeout_cancel", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_fast_and_slow_write_completion_records(monkeypatch):
    example = load_example()
    monkeypatch.setattr(example, "FAST_TIME", 0)
    monkeypatch.setattr(example, "SLOW_TIME", 0)

    assert asyncio.run(example.completion_demo()) == ["fast", "slow"]


def test_unfinished_tool_does_not_write_completion_record(monkeypatch):
    example = load_example()
    monkeypatch.setattr(example, "SLOW_TIME", 60)

    async def cancel_before_completion():
        completed = []
        task = asyncio.create_task(example.slow(lambda: completed.append("slow")))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return completed

    assert asyncio.run(cancel_before_completion()) == []


def test_local_timeout_returns_tool_result_and_allows_next_step(monkeypatch):
    example = load_example()
    monkeypatch.setattr(example, "FAST_TIME", 0)
    monkeypatch.setattr(example, "SLOW_TIME", 0.02)

    outcome = asyncio.run(example.timeout_demo(tool_timeout=0.005, task_timeout=1))

    assert outcome == {
        "status": "completed",
        "started": ["fast", "slow", "after"],
        "completed": ["fast", "after"],
        "results": [
            {"tool": "fast", "ok": True},
            {"tool": "slow", "ok": False, "error": "tool_timeout"},
            {"tool": "after", "ok": True},
        ],
    }


def test_cumulative_task_timeout_stops_before_new_step(monkeypatch):
    example = load_example()
    monkeypatch.setattr(example, "FAST_TIME", 0.05)
    steps = (("first", example.fast), ("second", example.fast), ("after", example.fast))

    outcome = asyncio.run(example.timeout_demo(
        tool_timeout=0.5, task_timeout=0.085, steps=steps
    ))

    assert outcome == {
        "status": "task_timeout",
        "started": ["first", "second"],
        "completed": ["first"],
        "results": [{"tool": "first", "ok": True}],
    }


def test_unrelated_timeout_error_is_not_labeled_as_tool_timeout():
    example = load_example()

    async def failing_tool(record):
        raise TimeoutError("tool raised its own error")

    with pytest.raises(TimeoutError, match="tool raised its own error"):
        asyncio.run(example.timeout_demo(
            tool_timeout=1, task_timeout=1, steps=(("failing", failing_tool),)
        ))
