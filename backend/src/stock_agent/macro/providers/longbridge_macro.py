
"""长桥宏观历史数据 Provider。

当前阶段：
- 查询单个指标
- 校验指标身份和国家
- 标准化统计期及数值
- 保留供应商提供的发布时间

暂不处理分页、重试、缓存或 Release 组装。
"""

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Protocol

import re
import time
from collections.abc import Callable

from longbridge.openapi import OpenApiException

from stock_agent.macro.errors import MacroDataProviderError
from stock_agent.macro.models.metric import (
    EconomicIndicator,
    EconomicMeasure,
    EconomicUnit,
)
from stock_agent.macro.providers.longbridge_indicators import (
    LONGBRIDGE_INDICATORS,
    normalize_value,
)

class MacroHistoryClient(Protocol):
    """Provider 对长桥 SDK 的最小依赖。"""

    def macroeconomic(
        self,
        indicator_code: str,
        *,
        start_date: str,
        end_date: str,
        offset: int,
        limit: int,
    ) -> Any:
        ...


@dataclass(frozen=True)
class LongbridgeMacroRecord:
    """已经完成单位标准化的一条宏观记录。"""

    indicator: EconomicIndicator
    measure: EconomicMeasure
    unit: EconomicUnit

    # 指标对应的统计期，不是发布日期。
    period: date

    actual: Decimal | None
    previous: Decimal | None
    forecast: Decimal | None
    revised: Decimal | None

    # 供应商时间，尚未核实为官方实际发布时间。
    vendor_release_at: datetime | None

    source: str = "longbridge"

def parse_period(value: date | datetime | str) -> date:
    """将 SDK 返回的统计期统一转换为 date。"""

    if isinstance(value, datetime):
        return value.date()

    if isinstance(value, date):
        return value

    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise MacroDataProviderError(
            f"Invalid Longbridge period: {value!r}"
        ) from exc


def parse_vendor_time(
    value: datetime | int | float | None,
) -> datetime | None:
    """解析长桥返回的事件时间。

    Unix 时间戳可以明确转换为 UTC。

    SDK 返回的无时区 datetime 保持原样，
    不擅自假定为北京时间或美国东部时间。
    """

    if value is None:
        return None

    if isinstance(value, datetime):
        return value

    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(
            value,
            tz=timezone.utc,
        )

    raise MacroDataProviderError(
        f"Invalid Longbridge release time: {value!r}"
    )

class LongbridgeMacroProvider:
    PAGE_SIZE = 100
    MAX_PAGES = 100

    def __init__(
        self,
        client: MacroHistoryClient,
        *,
        min_interval_seconds: float = 1.5,
        max_attempts: int = 4,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        if min_interval_seconds < 0:
            raise ValueError("min_interval_seconds must be >= 0")

        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")

        self.client = client
        self.min_interval_seconds = min_interval_seconds
        self.max_attempts = max_attempts

        # 注入时钟和等待函数，方便离线测试。
        self._clock = clock
        self._sleep = sleep

        # 本 Provider 上一次实际发送请求的时间。
        self._last_request_at: float | None = None

    def _wait_for_request_slot(self) -> None:
        """保证同一 Provider 实例的请求间隔。"""
        now = self._clock()

        if self._last_request_at is not None:
            elapsed = now - self._last_request_at
            remaining = self.min_interval_seconds - elapsed

            if remaining > 0:
                self._sleep(remaining)

        # 记录真正准备发送请求的时刻。
        self._last_request_at = self._clock()

    def _fetch_page(
        self,
        *,
        code: str,
        start_date: date,
        end_date: date,
        offset: int,
    ) -> Any:
        """查询一页；只有限流错误才自动重试。"""
        for attempt in range(self.max_attempts):
            self._wait_for_request_slot()
            try:
                return self.client.macroeconomic(
                    code,
                    start_date=start_date.isoformat(),
                    end_date=end_date.isoformat(),
                    offset=offset,
                    limit=self.PAGE_SIZE,
                )

            except OpenApiException as exc:
                if exc.code != 429002:
                    raise MacroDataProviderError(
                        f"Longbridge request failed: "
                        f"code={exc.code}, message={exc.message}"
                    ) from exc

                if attempt == self.max_attempts - 1:
                    raise MacroDataProviderError(
                        f"Longbridge rate limit persists: "
                        f"code={code}, offset={offset}"
                    ) from exc

                # 从异常中提取服务器要求的等待时间。
                match = re.search(
                    r"retry after:\s*([\d.]+)s",
                    exc.message,
                    flags=re.IGNORECASE,
                )

                retry_after = (
                    float(match.group(1))
                    if match
                    else 0.0
                )

                delay = max(
                    retry_after,
                    self.min_interval_seconds,
                )

                self._sleep(delay)
        raise RuntimeError("Unreachable retry state")

    def get_history(
        self,
        indicator: EconomicIndicator,
        measure: EconomicMeasure,
        *,
        start_date: date,
        end_date: date,
    ) -> list[LongbridgeMacroRecord]:
        """查询某项指标在指定发布日期区间内的记录。"""

        if start_date > end_date:
            raise ValueError(
                "start_date cannot be after end_date"
            )

        key = (indicator, measure)

        if key not in LONGBRIDGE_INDICATORS:
            raise ValueError(
                f"Unsupported macro indicator: {key}"
            )

        spec = LONGBRIDGE_INDICATORS[key]

        records: list[LongbridgeMacroRecord] = []
        offset = 0
        expected_total: int | None = None

        for _ in range(self.MAX_PAGES):
            response = self._fetch_page(
                code=spec.code,
                start_date=start_date,
                end_date=end_date,
                offset=offset,
            )

            # 每一页都核验指标身份，避免混入其他指标。
            if str(response.info.indicator_code) != spec.code:
                raise MacroDataProviderError(
                    f"Unexpected indicator code: {spec.code}"
                )

            if str(response.info.country).upper() not in {
                "US",
                "UNITED STATES",
            }:
                raise MacroDataProviderError(
                    f"Unexpected country: {spec.code}"
                )

            total = response.count
            if (
                not isinstance(total, int)
                or isinstance(total, bool)
                or total < 0
            ):
                raise MacroDataProviderError(
                    f"Invalid result count: {spec.code}"
                )

            if expected_total is None:
                expected_total = total

            elif total != expected_total:
                # 分页过程中数据集发生变化，不能静默拼接。
                raise MacroDataProviderError(
                    f"Result count changed during pagination: "
                    f"{spec.code}"
                )

            page = list(response.data)

            if len(page) > self.PAGE_SIZE:
                raise MacroDataProviderError(
                    f"Page size exceeded: {spec.code}"
                )

            if offset + len(page) > expected_total:
                raise MacroDataProviderError(
                    f"Unexpected extra records: {spec.code}"
                )

            if not page and offset < expected_total:
                raise MacroDataProviderError(
                    f"Empty page before completion: {spec.code}"
                )

            for item in page:
                try:
                    record = LongbridgeMacroRecord(
                        indicator=spec.indicator,
                        measure=spec.measure,
                        unit=spec.unit,
                        period=parse_period(item.period),
                        actual=normalize_value(
                            item.actual_value,
                            spec,
                        ),
                        previous=normalize_value(
                            item.previous_value,
                            spec,
                        ),
                        forecast=normalize_value(
                            item.forecast_value,
                            spec,
                        ),
                        revised=normalize_value(
                            getattr(
                                item,
                                "revised_value",
                                None,
                            ),
                            spec,
                        ),
                        vendor_release_at=parse_vendor_time(
                            item.release_at
                        ),
                    )
                except (ValueError, TypeError) as exc:
                    raise MacroDataProviderError(
                        f"Invalid Longbridge record: "
                        f"{spec.code}"
                    ) from exc

                records.append(record)

            # offset 是已获取的数据条数。
            offset += len(page)

            if offset == expected_total:
                return sorted(
                    records,
                    key=lambda record: record.period,
                    reverse=True,
                )

        raise MacroDataProviderError(
            f"Maximum pages exceeded: {spec.code}"
        )
