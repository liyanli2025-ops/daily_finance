"""Deterministic watchlist matching and publication-time filtering."""
import re
from datetime import timedelta, timezone


def matches_watchlist(item, stocks):
    text = (item.title + " " + (item.content or "")).casefold()
    related = set(item.related_stocks or [])
    for stock in stocks:
        if stock.code in related:
            return True
        if stock.name and stock.name.casefold() in text:
            return True
        if re.search(r"(?<![0-9])" + re.escape(stock.code) + r"(?![0-9])", text):
            return True
    return False


def within_window(item, now, hours):
    published = item.published_at
    if published.tzinfo is not None:
        published = published.astimezone(timezone(timedelta(hours=8))).replace(tzinfo=None)
    return now - timedelta(hours=hours) <= published <= now
