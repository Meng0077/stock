from collections.abc import Callable
from datetime import datetime, tzinfo
from typing import cast
from zoneinfo import ZoneInfo

from pathlib import Path

from stock_agent.macro.forecast_matching import (
    load_forecast_snapshots,
    match_release_forecasts,
)
from stock_agent.macro.calculations.fed import build_policy_snapshot
from stock_agent.macro.calculations.treasury import build_treasury_snapshot
from stock_agent.macro.errors import MacroDataProviderError
from stock_agent.macro.models.release import MacroReleaseEvent
from stock_agent.macro.models.snapshot import MacroSnapshot
from stock_agent.macro.models.fed import FedMedianProjection, FedPolicySnapshot
from stock_agent.macro.models.treasury import TREASURY_TENORS, TreasurySnapshot
from stock_agent.macro.providers.bea import BEAPCEProvider
from stock_agent.macro.providers.bls import BLSProvider
from stock_agent.macro.providers.fed import FedDataProvider
from stock_agent.macro.providers.fred import FredProvider
from stock_agent.macro.providers.fred_claims import WeeklyClaimsProvider
from stock_agent.macro.providers.trading_economics import (
    TradingEconomicsConsensusProvider,
)
from stock_agent.macro.providers.treasury import TreasuryRatesProvider
from stock_agent.macro.release_builders import (
    build_bls_inflation_release,
    build_employment_release,
    build_pce_release,
    build_weekly_claims_release,
)
from stock_agent.macro.temporal import filter_releases_as_of

from stock_agent.macro.longbridge_latest import (
    find_latest_available_release_date,
)
from stock_agent.macro.release_builders import (
    InflationReleaseType,
    LaborReleaseType,
    build_longbridge_release,
    build_longbridge_labor_release,
)
from stock_agent.macro.models.release import (
    MacroReleaseEvent,
    MacroReleaseType,
)
from stock_agent.macro.providers.longbridge_macro import (
    LongbridgeMacroProvider,
)


EASTERN = ZoneInfo("America/New_York")


def build_macro_snapshot(
    *,
    as_of: datetime,
    recent_releases: list[MacroReleaseEvent],
    fed_policy: FedPolicySnapshot | None,
    fed_projections: list[FedMedianProjection],
    treasury: TreasurySnapshot | None,
) -> MacroSnapshot:
    """组合已经计算完成的各宏观模块。

    输入：
        所有参数必须已经完成 Provider 请求和业务计算。

    输出：
        Agent 可以直接消费的 MacroSnapshot。

    职责：
        - 组合不同宏观模块
        - 生成数据完整性警告

    不负责：
        - 网络请求
        - CPI/PCE 等指标计算
        - Surprise 计算
        - 历史版本查询
    """

    warnings: list[str] = []

    if not recent_releases:
        warnings.append("recent_releases_missing")

    # ---------- Fed ----------

    if fed_policy is None:
        warnings.append("fed_policy_missing")

    if not fed_projections:
        # SEP 并不是每次 FOMC 都发布，
        # 因此这里仅提示，不认为整个 Snapshot 失败。
        warnings.append("fed_projections_missing")

    # ---------- Treasury ----------

    if treasury is None:
        warnings.append("treasury_data_missing")
    elif treasury.is_stale:
        warnings.append("treasury_data_stale")

    return MacroSnapshot(
        as_of=as_of,
        recent_releases=recent_releases,
        fed_policy=fed_policy,
        fed_projections=fed_projections,
        treasury=treasury,
        warnings=warnings,
    )


class MacroSnapshotBuilder:
    """组装当前最新宏观研究快照。

    职责：
        - 调用已经存在的各业务 Provider
        - 调用各 Release Builder
        - 允许单个数据源失败后返回部分 Snapshot
        - 收集 warnings

    不负责：
        - HTTP 请求实现
        - JSON / CSV 解析
        - CPI / PCE 数学公式
        - 单次 Release 的组装细节
        - 市场反应计算
        - 严格历史回测
    """

    def __init__(
        self,
        *,
        bls: BLSProvider,
        bea: BEAPCEProvider,
        consensus: TradingEconomicsConsensusProvider | None,
        fred: FredProvider,
        fed: FedDataProvider,
        treasury: TreasuryRatesProvider,
        claims: WeeklyClaimsProvider,
        longbridge_macro: LongbridgeMacroProvider | None = None,
        longbridge_vendor_timezone: tzinfo | None = None,
        forecast_snapshots_path: Path | None = None,
    ) -> None:
        self.bls = bls
        self.bea = bea
        self.consensus = consensus
        self.fred = fred
        self.fed = fed
        self.treasury = treasury
        self.claims = claims
        self.forecast_snapshots_path = forecast_snapshots_path

        if (
            longbridge_macro is not None
            and longbridge_vendor_timezone is None
        ):
            raise ValueError(
                "Longbridge vendor timezone must be explicit"
            )

        self.longbridge_macro = longbridge_macro
        self.longbridge_vendor_timezone = (
            longbridge_vendor_timezone
)

    def build_latest(
        self,
        *,
        as_of: datetime,
    ) -> MacroSnapshot:
        """构建当前最新宏观研究快照。

        这是在线研究路径，不是严格历史回测路径。
        单个宏观模块失败时跳过该模块，并写入 warnings。
        """

        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")

        releases: list[MacroReleaseEvent] = []
        warnings: list[str] = []
        research_date = as_of.astimezone(EASTERN).date()

        fallback_builders: dict[
            MacroReleaseType,
            Callable[[], MacroReleaseEvent | None],
        ] = {
            "cpi": lambda: build_bls_inflation_release(
                bls=self.bls,
                consensus=self.consensus,
                fred=self.fred,
                release_type="cpi",
                as_of=as_of,
                warnings=warnings,
            ),

            "ppi": lambda: build_bls_inflation_release(
                bls=self.bls,
                consensus=self.consensus,
                fred=self.fred,
                release_type="ppi",
                as_of=as_of,
                warnings=warnings,
            ),

            "pce": lambda: build_pce_release(
                bea=self.bea,
                consensus=self.consensus,
                fred=self.fred,
                as_of=as_of,
                warnings=warnings,
            ),

            "employment_situation":
                lambda: build_employment_release(
                    bls=self.bls,
                    fred=self.fred,
                    as_of=as_of,
                    consensus=self.consensus,
                    warnings=warnings,
                ),

            "weekly_claims":
                lambda: build_weekly_claims_release(
                    claims=self.claims,
                    fred=self.fred,
                    consensus=self.consensus,
                    as_of=as_of,
                    warnings=warnings,
                ),
        }

        for release_type, fallback in fallback_builders.items():
            self._append_release(
                releases=releases,
                warnings=warnings,
                name=release_type,
                builder=lambda rt=release_type, fb=fallback: (
                    self._prefer_longbridge(
                        release_type=rt,
                        as_of=as_of,
                        warnings=warnings,
                        fallback=fb,
                    )
                )
            )

        try:
            ranges = self.fed.get_target_ranges(as_of=research_date)
            fed_policy = build_policy_snapshot(ranges)
            if fed_policy is None:
                warnings.append("fed_policy_missing")
        except MacroDataProviderError:
            fed_policy = None
            warnings.append("fed_policy_unavailable")

        try:
            fed_projections = self.fed.get_current_projections(
                as_of=research_date
            )
            if not fed_projections:
                warnings.append("fed_projections_missing")
        except MacroDataProviderError:
            fed_projections = []
            warnings.append("fed_projections_unavailable")

        try:
            # Provider 只负责取数；完整曲线和利差由纯计算函数组装。
            treasury_yields = self.treasury.get_yields(
                list(TREASURY_TENORS),
                as_of=research_date,
            )
            treasury = build_treasury_snapshot(
                observations=treasury_yields,
                as_of=research_date,
            )
            if treasury is None:
                warnings.append("treasury_data_missing")
            elif treasury.is_stale:
                warnings.append("treasury_data_stale")
        except MacroDataProviderError:
            treasury = None
            warnings.append("treasury_unavailable")

        releases = self._attach_saved_forecasts(
            releases=releases,
            as_of=as_of,
            warnings=warnings,
        )

        releases, temporal_warnings = filter_releases_as_of(
            releases,
            as_of=as_of,
            strict_pit=False,
        )

        warnings.extend(temporal_warnings)

        # 最新发布在前。
        releases.sort(
            key=lambda item: item.release_date,
            reverse=True,
        )

        return MacroSnapshot(
            as_of=as_of,
            recent_releases=releases,
            fed_policy=fed_policy,
            fed_projections=fed_projections,
            treasury=treasury,
            warnings=warnings,
        )

    def _append_release(
        self,
        *,
        releases: list[MacroReleaseEvent],
        warnings: list[str],
        name: str,
        builder: Callable[[], MacroReleaseEvent | None],
    ) -> None:
        """执行一个 Release Builder，并隔离 Provider 故障。

        这里只捕获明确的领域 Provider 异常，不使用
        except Exception，以免把编程错误伪装成 API unavailable。
        """

        try:
            release = builder()
        except MacroDataProviderError:
            warnings.append(f"{name}_release_unavailable")
            return

        if release is None:
            warnings.append(f"{name}_release_missing")
            return

        releases.append(release)

    def _prefer_longbridge(
        self,
        *,
        release_type: MacroReleaseType,
        as_of: datetime,
        warnings: list[str],
        fallback: Callable[
            [],
            MacroReleaseEvent | None,
        ],
    ) -> MacroReleaseEvent | None:
        """优先使用长桥，完全不可用时调用原有 Builder。"""

        if self.longbridge_macro is None:
            return fallback()

        if self.longbridge_vendor_timezone is None:
            raise ValueError(
                "Longbridge vendor timezone is missing"
            )

        try:
            release_date = (
                find_latest_available_release_date(
                    macro=self.longbridge_macro,
                    release_type=release_type,
                    as_of=as_of,
                    vendor_timezone=(
                        self.longbridge_vendor_timezone
                    ),
                )
            )

            if release_date is None:
                warnings.append(
                    f"{release_type}_longbridge_no_release"
                )
                return fallback()

            if release_type in ("cpi", "ppi", "pce"):
                release = build_longbridge_release(
                    macro=self.longbridge_macro,
                    release_type=cast(
                        InflationReleaseType,
                        release_type,
                    ),
                    release_date=release_date,
                    as_of=as_of,
                    vendor_timezone=(
                        self.longbridge_vendor_timezone
                    ),
                    warnings=warnings,
                )
            else:
                release = build_longbridge_labor_release(
                    macro=self.longbridge_macro,
                    release_type=cast(
                        LaborReleaseType,
                        release_type,
                    ),
                    release_date=release_date,
                    as_of=as_of,
                    vendor_timezone=(
                        self.longbridge_vendor_timezone
                    ),
                    warnings=warnings,
                )

            if release is not None:
                # 部分发布也是有效结果；
                # 不把另一供应商的值混入同一次发布。
                return release

            warnings.append(
                f"{release_type}_longbridge_build_failed"
            )

        except MacroDataProviderError:
            warnings.append(
                f"{release_type}_longbridge_unavailable"
            )

        # 只有长桥无法形成发布事件时，才整体回退。
        warnings.append(
            f"{release_type}_using_official_fallback"
        )

        return fallback()

    def _attach_saved_forecasts(
        self,
        *,
        releases: list[MacroReleaseEvent],
        as_of: datetime,
        warnings: list[str],
    ) -> list[MacroReleaseEvent]:
        """用公布前保存的 Forecast 补充宏观发布事件。

        当前只处理长桥生成的发布事件。
        官方 Provider 回退事件暂不跨源合并。
        """

        path = self.forecast_snapshots_path

        if path is None:
            return releases

        if not path.exists():
            warnings.append("forecast_snapshots_missing")
            return releases

        try:
            snapshots = load_forecast_snapshots(path)
        except (OSError, ValueError):
            # 快照文件损坏不应导致 Fed 或 Treasury
            # 等其他宏观模块全部失败。
            warnings.append("forecast_snapshots_read_failed")
            return releases

        if not snapshots:
            warnings.append("forecast_snapshots_empty")
            return releases

        updated_releases: list[MacroReleaseEvent] = []

        for release in releases:
            # Step 8 的官方回退路径保持独立。
            # 暂不把长桥 Forecast 混入 BLS/BEA 的发布，
            # 避免在未校验跨源口径前产生错误匹配。
            if not release.metrics or any(
                metric.source != "longbridge"
                for metric in release.metrics
            ):
                updated_releases.append(release)
                continue

            updated, _, match_warnings = (
                match_release_forecasts(
                    release=release,
                    snapshots=snapshots,
                    as_of=as_of,
                )
            )

            updated_releases.append(updated)

            warnings.extend(
                f"{release.release_id}:{warning}"
                for warning in match_warnings
            )

        return updated_releases
