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
    for node in soup.select('.publication-header__details li, .artiHead .artiTime, '
            '.artMain > .artDes > span, .article-cont > .details > i, '
            '#content > h2 > .text-v2 > font'):
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
    values.extend(headline_publication_fields(soup))
    return list(dict.fromkeys(values))


def extracted_article_title(soup, content):
    """Only after successful generic extraction: match a visible headline.

    No hidden fields/scripts or search titles. A document title alone is not
    sufficient; it must agree with a visible heading or the extracted opening.
    The caller still checks publication, access and document type separately.
    """
    if soup.title is None:return ''
    document=soup.title.get_text(' ',strip=True)
    if not 6<=len(document)<=300:return ''
    def normalized(text):return re.sub(r'[^\w]', '', text).lower()
    doc=normalized(document)
    for node in soup.select('h1, h2, h3, strong#title'):
        if any(p.name in {'nav','aside','footer','form','script','template'} or p.has_attr('hidden')
               or p.get('aria-hidden')=='true' or re.search(r'display\s*:\s*none|visibility\s*:\s*hidden',(p.get('style') or ''),re.I)
               for p in (node,*node.parents)):
            continue
        heading=node.get_text(' ',strip=True);key=normalized(heading)
        if 6<=len(heading)<=300 and len(key)>=6 and (doc==key or document.startswith(heading)
                and re.match(r'\s*[-_|—｜]',document[len(heading):])):
            return heading
    # Some short news items use their opening as the document title. Require
    # a substantial exact prefix in successfully extracted, visible text.
    opening=normalized(content)
    title=re.split(r'[_|｜]',document,maxsplit=1)[0].strip();key=normalized(title)
    if len(key)>=24 and opening.startswith(key[:min(80,len(key))]):return title
    return ''


def headline_publication_fields(soup):
    """Publication widgets attached to a visible, document-matching headline.

    Never scan the whole page for dates or infer a date from a URL/title. A
    compact heading/header or its immediate metadata siblings is the boundary.
    """
    def visible(node):
        for parent in (node, *node.parents):
            classes = parent.get('class', [])
            if ('hidden' in classes and not any(re.fullmatch(
                    r'[a-z]+:(?:block|flex|inline|inline-block|inline-flex|grid)', name) for name in classes)):
                return False
            if (parent.name in {'nav', 'aside', 'footer', 'script', 'style', 'template', 'noscript'}
                    or parent.has_attr('hidden') or parent.get('aria-hidden') == 'true'
                    or parent.get('itemprop') == 'dateModified'
                    or re.search(r'display\s*:\s*none|visibility\s*:\s*hidden', parent.get('style', ''), re.I)
                    or re.search(r'(?:^|[ _-])(?:recommend|related|comments?|modified|updated)(?:$|[ _-])',
                                 ' '.join(parent.get('class', [])), re.I)):
                return False
        return True
    def matching(node):
        text = node.get_text(' ', strip=True)
        document = soup.title.get_text(' ', strip=True) if soup.title else ''
        return (6 <= len(text) <= 300 and (document == text or document.startswith(text)
                and re.match(r'\s*[-_|—｜]', document[len(text):])))
    headings = [n for n in soup.select('h1, h2, h3') if visible(n) and matching(n)]
    if not headings or len({n.get_text(' ', strip=True) for n in headings}) != 1:
        return []
    found = []
    for heading in headings:
        regions = []
        parent = heading.parent
        # Do not ascend into a large article/recommendation region.
        if (parent.name in {'header', 'div'} and len(parent.get_text(' ', strip=True)) <= 600
                and len(parent.select('h1, h2, h3')) == 1):
            regions.append(parent)
        # Responsive templates often repeat the same publication widget.
        for node in list(heading.next_siblings)[:8]:
            if not getattr(node, 'name', None):
                if str(node).strip():
                    break
                continue
            if (node.name in {'p', 'section', 'article', 'h1', 'h2', 'h3'}
                    or node.select_one('p, h1, h2, h3, article, section')
                    or len(node.get_text(' ', strip=True)) > 180):
                break
            if visible(node):
                regions.append(node)
        values = []
        for region in regions:
            for node in [region, *region.select('time, span, i, font')]:
                if (not visible(node) or node is heading or heading in node.parents
                        or node.select_one('h1, h2, h3') is not None):
                    continue
                if node.get('itemprop') == 'dateModified':
                    continue
                raw = node.get('datetime') if node.name == 'time' else node.get_text(' ', strip=True)
                if not raw:
                    continue
                raw = re.sub(r'^(?:发布时间|发布日期|发布于|Published(?: on)?)\s*[:：]?\s*', '', raw, flags=re.I)
                # Bare clocks, years, paragraph dates and update labels are not
                # publication dates. Unknown timezones remain unknown downstream.
                if not re.fullmatch(r'\d{4}[-/]\d{2}[-/]\d{2}[ T]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})?', raw):
                    continue
                try:
                    publication_value(raw)
                except ValueError:
                    continue
                values.append(raw)
        found.extend(values)
    # Multiple conflicting clocks near the headline require review; never
    # choose the newest clock (which could be an update rather than publication).
    unique = {publication_value(raw)[0].isoformat(): raw for raw in found}
    return list(unique.values()) if len(unique) == 1 else []
