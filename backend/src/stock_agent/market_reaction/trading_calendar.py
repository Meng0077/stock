from datetime import datetime, timedelta, timezone

import exchange_calendars as xcals


def resolve_close_at(
    event_at: datetime,
) -> tuple[datetime, str]:
    """找到事件发生后的第一次正式收盘。

    返回：
        close_at：UTC 收盘时间。
        session_date：交易日 YYYY-MM-DD。
    """

    if event_at.tzinfo is None or event_at.utcoffset() is None:
        raise ValueError("event_at must be timezone-aware")

    event_utc = event_at.astimezone(timezone.utc)

    # 覆盖未来两个星期的交易日。
    start = event_utc.date()
    end = start + timedelta(days=14)

    calendar = xcals.get_calendar("XNYS")

    sessions = calendar.sessions_in_range(
        start.isoformat(),
        end.isoformat(),
    )

    for session in sessions:
        closed = calendar.session_close(session).to_pydatetime()
        # 必须是事件发生之后的收盘。
        if closed > event_utc:
            return closed, session.strftime("%Y-%m-%d")

    raise ValueError("no trading session found after event")
