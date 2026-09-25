from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

import httpx

from stock_agent.macro.errors import MacroDataProviderError


FRED_API_BASE = "https://api.stlouisfed.org/fred"


@dataclass(frozen=True)
class FredObservation:
    series_id: str
    period: date
    value: Decimal

    # FRED / ALFRED 的 vintage 范围。
    realtime_start: date | None = None
    realtime_end: date | None = None


@dataclass(frozen=True)
class FredRelease:
    """FRED 中某条 Series 对应的 Economic Release。"""

    release_id: int
    name: str


class FredProvider:
    def __init__(self, client: httpx.Client, api_key: str):
        self.client = client
        self.api_key = api_key

    def get_observations(
        self,
        series_id: str,
        *,
        observation_start: date | None = None,
        observation_end: date | None = None,
        realtime_start: date | None = None,
        realtime_end: date | None = None,
        sort_order: str = "asc",
        limit: int = 100000,
    ) -> list[FredObservation]:
        params: dict[str, str | int] = {
            "series_id": series_id,
            "api_key": self.api_key,
            "file_type": "json",
            "sort_order": sort_order,
            "limit": limit,
        }

        if observation_start is not None:
            params["observation_start"] = observation_start.isoformat()
        if observation_end is not None:
            params["observation_end"] = observation_end.isoformat()
        if realtime_start is not None:
            params["realtime_start"] = realtime_start.isoformat()
        if realtime_end is not None:
            params["realtime_end"] = realtime_end.isoformat()

        try:
            response = self.client.get(
                f"{FRED_API_BASE}/series/observations",
                params=params,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise MacroDataProviderError(
                f"Failed to fetch FRED series {series_id}"
            ) from exc

        rows = payload.get("observations")
        if not isinstance(rows, list):
            raise MacroDataProviderError(
                "Unexpected FRED observations response"
            )

        observations: list[FredObservation] = []

        for row in rows:
            raw_value = str(row.get("value", "")).strip()

            # FRED 用 "." 表示缺失值。
            if raw_value in {"", "."}:
                continue

            try:
                value = Decimal(raw_value)
                period = date.fromisoformat(row["date"])
            except (InvalidOperation, ValueError, KeyError) as exc:
                raise MacroDataProviderError(
                    f"Invalid FRED observation for {series_id}"
                ) from exc

            if not value.is_finite():
                raise MacroDataProviderError(
                    f"Non-finite FRED value for {series_id}"
                )

            observations.append(
                FredObservation(
                    series_id=series_id,
                    period=period,
                    value=value,
                    realtime_start=_parse_optional_date(
                        row.get("realtime_start")
                    ),
                    realtime_end=_parse_optional_date(
                        row.get("realtime_end")
                    ),
                )
            )

        return observations

    def get_series_release(self, series_id: str) -> FredRelease:
        """获取某条 FRED Series 所属的 Economic Release。

        这里只用于定位发布日历，不使用该 Series
        替代 BLS / BEA 的 actual 数据。
        """

        try:
            response = self.client.get(
                f"{FRED_API_BASE}/series/release",
                params={
                    "series_id": series_id,
                    "api_key": self.api_key,
                    "file_type": "json",
                },
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise MacroDataProviderError(
                f"Failed to fetch FRED release for {series_id}"
            ) from exc

        releases = payload.get("releases")
        if not isinstance(releases, list) or len(releases) != 1:
            raise MacroDataProviderError(
                f"Unexpected FRED release for {series_id}"
            )

        item = releases[0]
        try:
            return FredRelease(
                release_id=int(item["id"]),
                name=str(item["name"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise MacroDataProviderError(
                f"Invalid FRED release for {series_id}"
            ) from exc

    def get_release_dates(
        self,
        release_id: int,
        *,
        include_future: bool = False,
    ) -> list[date]:
        """获取某个 Economic Release 的发布日期。

        FRED 这里只提供 date，不能据此构造具体 released_at。
        """

        try:
            response = self.client.get(
                f"{FRED_API_BASE}/release/dates",
                params={
                    "release_id": release_id,
                    "api_key": self.api_key,
                    "file_type": "json",
                    "include_release_dates_with_no_data": (
                        "true" if include_future else "false"
                    ),
                },
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise MacroDataProviderError(
                f"Failed to fetch FRED release dates for {release_id}"
            ) from exc

        rows = payload.get("release_dates")
        if not isinstance(rows, list):
            raise MacroDataProviderError(
                "Unexpected FRED release dates response"
            )

        result: list[date] = []
        for row in rows:
            raw_date = row.get("date")
            if not isinstance(raw_date, str):
                raise MacroDataProviderError("Invalid FRED release date")

            try:
                result.append(date.fromisoformat(raw_date))
            except ValueError as exc:
                raise MacroDataProviderError(
                    f"Invalid FRED release date: {raw_date}"
                ) from exc

        return sorted(result)


def _parse_optional_date(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None
