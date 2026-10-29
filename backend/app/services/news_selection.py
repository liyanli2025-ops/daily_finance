"""Deterministic watchlist matching and publication-time filtering."""
import re
from datetime import timedelta, timezone


def matching_text(title, body):
    """Footer link titles are not reporting about the company/industry."""
    body = re.split(r'(?m)^\s*相关阅读[：:]?\s*$', body or '', maxsplit=1)[0]
    return title + ' ' + body


def industry_terms(text, terms):
    """Lexical leads only; ambiguous utility words need hydropower context."""
    text = re.split(r'(?m)^\s*相关阅读[：:]?\s*$', text, maxsplit=1)[0]
    clean = re.sub(r'自来水|水电(?:费|气|煤|工|维修|安装)', '', text)
    # A mine/factory purchasing electricity from a plant is not a report about
    # a hydropower producer's operations. Mask only the consumer-side clause
    # for hydro matching; keep the full article and other industry vocabulary.
    hydro_text = re.sub(r'(?:除了)?(?:与|同|向|从)[^。！？；;\n]{0,70}?水电站'
                        r'[^。！？；;\n]{0,70}?(?:购电|购买电力|供电|电力购买)[^。！？；;\n]*', '', clean)
    hydro_context = re.search(r'水力发电|水电站|水电发电|水电电价|流域|水库|水情|汛期|蓄水|水电企业|水电公司', hydro_text)
    hydro_terms={'水电','来水','水电站','水电发电量','水电电价','水力发电'}
    return [term for term in terms if len(term) >= 2 and
            (term in hydro_text and hydro_context if term in hydro_terms else term in clean)]


def matches_watchlist(item, stocks):
    text = matching_text(item.title, item.content).casefold()
    has_related_footer = bool(re.search(r'(?m)^\s*相关阅读[：:]?\s*$',item.content or ''))
    related = set(item.related_stocks or [])
    for stock in stocks:
        if stock.code in related and not has_related_footer:
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
