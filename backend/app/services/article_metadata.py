"""Explicit publication fields and article headings; never infer from URL dates."""
from datetime import datetime, timezone
import re


def publication_value(raw):
    value = str(raw).strip().replace('/', '-')
    value = re.sub(r'(\d{4})年(\d{1,2})月(\d{1,2})日',
        lambda match:f'{int(match[1]):04d}-{int(match[2]):02d}-{int(match[3]):02d}',value)
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}Z?', value):
        return datetime.fromisoformat(value.rstrip('Z')), True
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')), False
    except ValueError:
        pass
    # Fixed English month names avoid dependence on the server's locale.
    match = re.fullmatch(r'([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})', value)
    if match:
        months = ('january','february','march','april','may','june','july','august','september','october','november','december')
        key = match[1].lower()
        month=next((index for index,name in enumerate(months,1) if key in {name,name[:3]}),None)
        if month is not None:
            return datetime(int(match[3]), month, int(match[2])), True
    raise ValueError('web_source_time_invalid')


def article_title(soup, article, heading=None):
    candidates = [heading]
    if article is not None:
        candidates += article.select('h1, h2.artiTit, h2[itemprop="headline"]')
        # Some mobile article templates use one h2 as their main title.
        if not article.select('h1') and len(article.select('h2')) == 1:
            candidates += article.select('h2')
    for node in candidates:
        if node is not None:
            text = node.get_text(' ', strip=True)
            if 6 <= len(text) <= 300:
                return text
    for node in soup.select('meta[property="og:title"],meta[name="ArticleTitle"]'):
        text = node.get('content', '').strip()
        if 6 <= len(text) <= 300:
            return text
    # A document title is usable only alongside an article body container.
    if article is not None and soup.title is not None:
        text = soup.title.get_text(' ', strip=True)
        if 6 <= len(text) <= 300:
            return text
    return ''


def visible_publication_fields(soup):
    """Read bounded publication widgets, never recommendation timestamps."""
    values = []
    for node in soup.select('.publication-header__details li, .artiHead .artiTime'):
        text = node.get_text(' ', strip=True)
        try:
            publication_value(text)
        except ValueError:
            continue
        values.append(text)
    for node in soup.select('time[data-showtime],span.time[data-showtime]'):
        values.append(node.get('data-showtime'))
    for node in soup.select('.info[data-article-publish-time]'):
        raw = node.get('data-article-publish-time', '')
        if re.fullmatch(r'\d{10}', raw) and 946684800 <= int(raw) < 4102444800:
            values.append(datetime.fromtimestamp(int(raw), timezone.utc).isoformat())
    return values
