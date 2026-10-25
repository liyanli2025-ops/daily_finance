"""Mainland and Hong Kong editorial day, independent of the server timezone."""
from datetime import datetime, timedelta, timezone

CHINA_TIME = timezone(timedelta(hours=8), "Asia/Shanghai")


def china_now():
    # Existing database columns use naive datetimes in China local time.
    return datetime.now(CHINA_TIME).replace(tzinfo=None)


def china_today():
    return china_now().date()
