from stock_agent.agents.langgraph.state import ResearchPlan, ResearchState

MAX_RESEARCH_RETRIES = 1


def collect_security_missing_information(
    *,
    plan: ResearchPlan,
    company_id: str,
    results: dict[str, object],
) -> list[str]:
    """
    检查一个证券对应的研究结果。

    missing item 使用：
        <reason>:<company_id>[:<detail>]

    这样多证券场景下可以明确知道
    哪个证券缺少什么数据。
    """
    missing: list[str] = []

    def add(reason: str) -> None:
        missing.append(f"{reason}:{company_id}")

    # Company Profile
    if plan.needs_company_profile:
        if "company_profile" not in results:
            add("company_profile_not_executed")
        elif results["company_profile"] is None:
            add("company_profile_unavailable")

    # Quote
    if plan.needs_quote:
        if "quote" not in results:
            add("quote_not_executed")
        elif results["quote"] is None:
            add("quote_unavailable")

    # Technical
    if plan.needs_technical:
        if "technical" not in results:
            add("technical_not_executed")
        elif results["technical"] is None:
            add("technical_unavailable")

    # Decision
    if plan.needs_decision:
        decision = results.get("decision")
        if "decision" not in results:
            add("decision_not_executed")
        elif decision is None:
            add("decision_unavailable")
        elif getattr(decision, "status", None) == "blocked":
            decision_missing = getattr(decision, "missing_information", None)
            if decision_missing:
                for item in decision_missing:
                    add(item)
            else:
                add("decision_blocked")

    # Earnings latest
    if plan.needs_earnings_reaction:
        if "earnings_reaction" not in results:
            add("earnings_reaction_not_executed")
        elif results["earnings_reaction"] is None:
            add("earnings_reaction_unavailable")

    # Earnings history
    if plan.needs_earnings_reaction_history:
        if "earnings_reaction_history" not in results:
            add("earnings_reaction_history_not_executed")
        elif not results["earnings_reaction_history"]:
            add("earnings_reaction_history_unavailable")

    # Macro latest reaction
    if plan.needs_macro_reaction:
        if "macro_reaction" not in results:
            add("macro_reaction_not_executed")
        elif results["macro_reaction"] is None:
            add("macro_reaction_unavailable")

    # Macro history reaction
    if plan.needs_macro_reaction_history:
        if "macro_reaction_history" not in results:
            add("macro_reaction_history_not_executed")
        elif not results["macro_reaction_history"]:
            add("macro_reaction_history_unavailable")

    # Knowledge
    if plan.knowledge_question is not None:
        if "knowledge" not in results:
            add("knowledge_not_executed")
        elif not results["knowledge"]:
            add("knowledge_unavailable")

    # Financial
    if plan.financial_requests:
        if "financial" not in results:
            add("financial_not_executed")
        else:
            financial = results["financial"]
            if not isinstance(financial, list):
                add("financial_result_invalid")
            else:
                for request in plan.financial_requests:
                    matched_result = next(
                        (
                            item
                            for item in financial
                            if (
                                isinstance(item, dict)
                                and item.get("concept") == request.concept
                                and item.get("period_type") == request.period_type
                                and item.get("unit") == request.unit
                            )
                        ),
                        None,
                    )
                    if matched_result is None:
                        missing.append(f"financial_request_not_executed:{company_id}:{request.concept}")
                        continue
                    facts = matched_result.get("facts")
                    if not facts:
                        missing.append(f"financial_facts_unavailable:{company_id}:{request.concept}")

    return missing


def collect_missing_information(
    *,
    plan: ResearchPlan,
    results: dict[str, object],
    company_ids: list[str],
) -> list[str]:
    """
    检查整个 Research 是否满足 Plan。

    证券级数据逐 company 检查；
    MacroSnapshot 等共享数据检查一次。
    """

    missing: list[str] = []
    companies = results.get("companies", {})
    if not isinstance(companies, dict):
        companies = {}

    for company_id in company_ids:
        company_results = companies.get(company_id, {})
        if not isinstance(company_results, dict):
            company_results = {}
        company_missing = collect_security_missing_information(
            plan=plan,
            results=company_results,
            company_id=company_id,
        )
        missing.extend(company_missing)

    # Shared Macro
    if plan.needs_macro:
        if "macro_snapshot" not in results:
            missing.append("macro_snapshot_not_executed")
        elif results["macro_snapshot"] is None:
            missing.append("macro_snapshot_unavailable")
    return missing


def _collect_security_source_warnings(
    *,
    results: dict[str, object],
    company_id: str,
) -> set[str]:
    """
    收集当前证券 Research results 中已经明确记录的
    source warnings。

    Checker 只读取已有诊断信息，
    不重新请求 Provider。
    """
    warnings: set[str] = set()
    companies = results.get("companies", {})
    if not isinstance(companies, dict):
        return warnings

    company_results = companies.get(company_id, {})
    if not isinstance(company_results, dict):
        return warnings

    market_quality = company_results.get("market_quality")
    if market_quality is not None:
        warnings.update(getattr(market_quality, "source_warnings", []))

    return warnings


def split_missing_information(
    *,
    missing_information: list[str],
    results: dict[str, object],
) -> tuple[list[str], list[str]]:
    retryable: list[str] = []
    terminal: list[str] = []

    for item in missing_information:
        parts = item.split(":", 2)
        reason = parts[0]
        company_id = parts[1] if len(parts) >= 2 else None
        security_warnings: set[str] = set()

        if company_id is not None:
            security_warnings = _collect_security_source_warnings(results=results, company_id=company_id)

        # capability 没真正执行
        if reason.endswith("_not_executed"):
            retryable.append(item)
            continue

        # Quote Provider 临时失败
        if reason == "quote_unavailable" and "quote_provider_unavailable" in security_warnings:
            retryable.append(item)
            continue

        # Bars Provider 临时失败
        if reason in {"technical_unavailable", "technical_missing"} and "bars_provider_unavailable" in security_warnings:
            retryable.append(item)
            continue

        terminal.append(item)

    return retryable, terminal


def checker_node(state: ResearchState) -> dict[str, object]:
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
    company_ids = list(state["request"].company_ids)
    missing_information = collect_missing_information(plan=plan, results=results, company_ids=company_ids)
    retryable, _terminal = split_missing_information(missing_information=missing_information, results=results)

    # 1. Nothing missing
    if not missing_information:
        return {"missing_information": [], "research_status": "enough"}

    # 2. Retryable missing
    if retryable and retry_count < MAX_RESEARCH_RETRIES:
        return {"missing_information": missing_information, "research_status": "retry"}

    # 3. Missing remains but cannot retry
    return {"missing_information": missing_information, "research_status": "cannot_retry"}


def route_after_check(state: ResearchState) -> str:
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
