from stock_agent.agents.langgraph.state import (
    ResearchPlan,
    ResearchState,
)

MAX_RESEARCH_RETRIES = 1

def collect_missing_information(
    *,
    plan: ResearchPlan,
    results: dict[str, object],
) -> list[str]:
    """
    根据 ResearchPlan 和 Research results，
    收集当前回答仍然缺少的信息。

    这里只判断：
    - 请求的 capability 是否执行；
    - 请求的 capability 是否有可用结果；
    - deterministic result 是否明确声明 blocked。

    不负责：
    - 判断是否值得 retry；
    - 重新计算业务结果；
    - 重新执行 quality validation。
    """

    missing: list[str] = []

    # 1. Company Profile
    if plan.needs_company_profile:
        if "company_profile" not in results:
            missing.append("company_profile_not_executed")
        elif results["company_profile"] is None:
            missing.append("company_profile_unavailable")

    # 2. Quote
    if plan.needs_quote:
        if "quote" not in results:
            missing.append("quote_not_executed")
        elif results["quote"] is None:
            missing.append("quote_unavailable")

    # technical
    if plan.needs_technical:
        if "technical" not in results:
            missing.append("technical_not_executed")
        elif results["technical"] is None:
            missing.append("technical_unavailable")

    # decision
    if plan.needs_decision:
        decision = results.get("decision")
        if "decision" not in results:
            missing.append("decision_not_executed")
        elif decision  is None:
            missing.append("decision_unavailable")
        elif getattr(decision, "status", None) == "blocked":
            decision_missing = getattr(decision, "missing_information", None)
            if decision_missing:
                missing.extend(decision_missing)
            else:
                missing.append("decision_blocked")

    # Earnings latest reaction
    if plan.needs_earnings_reaction:
        if "earnings_reaction" not in results:
            missing.append("earnings_reaction_not_executed")
        elif results["earnings_reaction"] is None:
            missing.append("earnings_reaction_unavailable")

    # Earnings history
    if plan.needs_earnings_reaction_history:
        if "earnings_reaction_history" not in results:
            missing.append("earnings_reaction_history_not_executed")
        elif not results["earnings_reaction_history"]:
            missing.append("earnings_reaction_history_unavailable")

    # Macro snapshot
    if plan.needs_macro:
        if "macro_snapshot" not in results:
            missing.append("macro_snapshot_not_executed")
        elif results["macro_snapshot"] is None:
            missing.append("macro_snapshot_unavailable")

    # Macro latest reaction
    if plan.needs_macro_reaction:
        if "macro_reaction" not in results:
            missing.append("macro_reaction_not_executed")
        elif results["macro_reaction"] is None:
            missing.append("macro_reaction_unavailable")

    # Macro reaction history
    if plan.needs_macro_reaction_history:
        if "macro_reaction_history" not in results:
            missing.append("macro_reaction_history_not_executed")
        elif not results["macro_reaction_history"]:
            missing.append("macro_reaction_history_unavailable")

    # Knowledge
    if plan.knowledge_question is not None:
        if "knowledge" not in results:
            missing.append("knowledge_not_executed")
        elif not results["knowledge"]:
            missing.append("knowledge_unavailable")

    # Financial
    if plan.financial_requests:
        if "financial" not in results:
            missing.append("financial_not_executed")
        else:
            financial = results["financial"]
            if not isinstance(financial, list):
                missing.append("financial_result_invalid")
            else:
                for request in plan.financial_requests:
                    matched_result = next((
                        item
                        for item in financial
                        if (
                            isinstance(item, dict)
                            and item.get("concept") == request.concept
                            and item.get("period_type") == request.period_type
                            and item.get("unit") == request.unit
                        )
                    ), None)
                    if matched_result is None:
                        missing.append(f"financial_request_not_executed:{request.concept}")
                        continue
                    facts = matched_result.get("facts")
                    if not facts:
                        missing.append(f"financial_facts_unavailable:{request.concept}")
    return missing

def _collect_source_warnings(
    results: dict[str, object],
) -> set[str]:
    """
    收集当前 Research results 中已经明确记录的
    source warnings。

    Checker 只读取已有诊断信息，
    不重新请求 Provider。
    """
    warnings = set()

    market_quality = results.get("market_quality")
    if market_quality is not None:
        source_warnings = getattr(market_quality, "source_warnings", [])
        warnings.update(source_warnings)

    macro_quality = results.get("macro_quality")
    if macro_quality is not None:
        source_warnings = getattr(macro_quality, "source_warnings", [])
        warnings.update(source_warnings)

    macro_history_warnings = results.get("macro_history_warnings")
    if isinstance(macro_history_warnings, list):
        warnings.update(item for item in macro_history_warnings if isinstance(item, str))

    return warnings

def split_missing_information(
    *,
    missing_information: list[str],
    results: dict[str, object],
) -> tuple[
    list[str],
    list[str],
]:
    """
    把当前缺失信息分成：

    retryable:
        再执行一次 Research 有合理机会恢复。

    terminal:
        相同输入 / 相同 as_of 下立即重试，
        通常不会改变结果。

    原则：
        默认 terminal；
        只有明确执行缺口或临时 Provider 失败
        才进入 retryable。
    """
    retryable = []
    terminal = []

    source_warnings = _collect_source_warnings(results)

    for item in missing_information:
        #  Plan 要了，但 capability 根本没执行
        if item.endswith("_not_executed") or item.startswith("financial_request_not_executed:"):
            retryable.append(item)
            continue

        # Quote 不可用:只有明确是 Provider 暂时不可用时才重试
        if item == 'quote_unavailable' and "quote_provider_unavailable" in source_warnings:
            retryable.append(item)
            continue

        # Technical / Decision: Bars Provider 临时失败，
        if item in {'technical_unavailable', "technical_missing"} and "bars_provider_unavailable" in source_warnings:
            retryable.append(item)
            continue

        # 其他 missing 默认 terminal
        terminal.append(item)

    return (retryable, terminal)

def checker_node(
    state: ResearchState,
) -> dict[str, object]:
    """
    检查当前 Research results 是否足够。

    输出三种状态：

    enough:
        当前没有缺失信息，可以进入 Answer。

    retry:
        存在明确可重试的缺失，
        且尚未达到最大重试次数。

    cannot_retry:
        仍有缺失，
        但没有可重试项，
        或已经达到最大重试次数。

    Checker 不重新执行任何 Research。
    """
    plan = state.get("plan")
    if plan is None:
        raise ValueError("research plan is missing")

    results = state.get("results", {})

    retry_count = state.get("retry_count", 0)

    missing_information = collect_missing_information(
        plan=plan,
        results=results,
    )

    retryable, _terminal = split_missing_information(
        missing_information=missing_information,
        results=results,
    )

    # 1. Nothing missing
    if not missing_information:
        return {
            "missing_information": [],
            "research_status": "enough"
        }

    # 2. Retryable missing
    if retryable and retry_count < MAX_RESEARCH_RETRIES:
        return {
            "missing_information": missing_information,
            "research_status": "retry"
        }

    # 3. Missing remains but cannot retry
    return {
        "missing_information": missing_information,
        "research_status": "cannot_retry"
    }

def route_after_check(
    state: ResearchState,
) -> str:
    """
    根据 Checker 已经写入的 research_status，
    决定下一条 Workflow edge。

    Checker 负责判断；
    Router 只负责映射。
    """
    research_status = state.get("research_status")

    if research_status in {"enough", "cannot_retry"}:
        return "answer"

    if research_status == "retry":
        return "research"
    raise ValueError("research status is missing")
