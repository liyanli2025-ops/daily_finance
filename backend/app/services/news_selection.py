"""Deterministic watchlist matching and publication-time filtering."""
import re
from datetime import timedelta, timezone


def industry_terms(text, terms):
    """Lexical leads only; ambiguous utility words need hydropower context."""
    clean = re.sub(r'自来水|水电(?:费|气|煤|工|维修|安装)', '', text)
    hydro_context = re.search(r'水力发电|水电站|水电发电|水电电价|流域|水库|水情|汛期|蓄水|水电企业|水电公司', clean)
    return [term for term in terms if len(term) >= 2 and term in clean
            and (term not in {'水电', '来水'} or hydro_context)]


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
