from collections.abc import Callable
from datetime import datetime
from zoneinfo import ZoneInfo

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
    ) -> None:
        self.bls = bls
        self.bea = bea
        self.consensus = consensus
        self.fred = fred
        self.fed = fed
        self.treasury = treasury
        self.claims = claims

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

        self._append_release(
            releases=releases,
            warnings=warnings,
            name="cpi",
            builder=lambda: build_bls_inflation_release(
                bls=self.bls,
                consensus=self.consensus,
                fred=self.fred,
                release_type="cpi",
                as_of=as_of,
                warnings=warnings,
            ),
        )
        self._append_release(
            releases=releases,
            warnings=warnings,
            name="ppi",
            builder=lambda: build_bls_inflation_release(
                bls=self.bls,
                consensus=self.consensus,
                fred=self.fred,
                release_type="ppi",
                as_of=as_of,
                warnings=warnings,
            ),
        )
        self._append_release(
            releases=releases,
            warnings=warnings,
            name="pce",
            builder=lambda: build_pce_release(
                bea=self.bea,
                consensus=self.consensus,
                fred=self.fred,
                as_of=as_of,
                warnings=warnings,
            ),
        )
        self._append_release(
            releases=releases,
            warnings=warnings,
            name="employment_situation",
            builder=lambda: build_employment_release(
                bls=self.bls,
                fred=self.fred,
                as_of=as_of,
                warnings=warnings,
                consensus=self.consensus,
            ),
        )

        self._append_release(
            releases=releases,
            warnings=warnings,
            name="weekly_claims",
            builder=lambda: build_weekly_claims_release(
                claims=self.claims,
                fred=self.fred,
                consensus=self.consensus,
                as_of=as_of,
                warnings=warnings,
            ),
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
