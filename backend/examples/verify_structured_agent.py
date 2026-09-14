"""D04 一键离线验收：复用已有 pytest 案例，不请求真实模型。"""

from pathlib import Path

import pytest


TESTS = Path(__file__).resolve().parents[1] / "tests"
CASE_FILES = (
    "test_research_output.py",
    "test_evidence_validation.py",
    "test_public_error.py",
    "test_structured_agent_response.py",
    "test_structured_agent_repair.py",
    "test_structured_agent_runtime.py",
    "test_structured_agent_async.py",
    "test_structured_agent_preview.py",
    "test_tool_calling.py",
    "test_timeout_cancel.py",
)


def main() -> int:
    """无入参；逐项显示离线案例结果，全部通过返回 0，否则返回 1。"""
    print("D04 离线验收：结构、证据、修复、超时、取消、预算与安全事件", flush=True)
    result = pytest.main(["-v", *(str(TESTS / name) for name in CASE_FILES)])
    return 0 if result == pytest.ExitCode.OK else 1


if __name__ == "__main__":
    raise SystemExit(main())
