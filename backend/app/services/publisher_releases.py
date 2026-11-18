"""Publisher-owned release streams. A directory row is still only a lead."""
from datetime import date, timedelta
import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup


PUBLISHERS = {
    'mfa': dict(name='外交部', directory='https://www.mfa.gov.cn/wjdt_674879/wsrc_674883/',
        path=r'/(?:[\w-]+/)*\d{6}/t\d{8}_\d+\.shtml',
        headline='h1', body='#News_Body_Txt_A', clock='p.time'),
    'mofcom': dict(name='商务部', directory='https://www.mofcom.gov.cn/xwfb/',
        path=r'/(?:[\w-]+/)*art/\d{4}/art_[\da-f]+\.html',
        directory_section='/xwfb/rcxwfb/', headline='.art-title', body='.art-con[ergodic="article"]',
        clock='.article-tool .at-left p > span'),
}


def article_publisher(url):
    address = urlsplit(url)
    if address.scheme != 'https' or address.netloc != address.hostname:
        return None
    return next((p for p in PUBLISHERS.values() if address.hostname == urlsplit(p['directory']).hostname
                 and re.fullmatch(p['path'], address.path)), None)


def catalogue(html, publisher, cutoff, limit=5):
    """Take links and publication labels from the same official list item."""
    soup = BeautifulSoup(html, 'html.parser')
    lower = cutoff.date() - timedelta(days=4)
    rows = {}
    pattern = r'[（(\[]\s*(\d{4}-\d{2}-\d{2})\s*[）)\]]'
    for link in soup.select('li a[href]'):
        url = urljoin(publisher['directory'], link['href'])
        if (article_publisher(url) is not publisher or url in rows
                or not urlsplit(url).path.startswith(publisher.get('directory_section', '/'))):
            continue
        title = link.get_text(' ', strip=True)
        stamped = re.search(pattern, link.parent.get_text(' ', strip=True))
        if not stamped:
            continue
        try:
            day = date.fromisoformat(stamped[1])
        except ValueError:
            continue
        title = re.sub(pattern, '', title).strip()
        if lower <= day <= cutoff.date() and 6 <= len(title) <= 300:
            rows[url] = dict(title=title, url=url, snippet=None, published_hint=day.isoformat(),
                original_publisher=publisher['name'], reading_status='official_directory_not_body')
    return sorted(rows.values(), key=lambda row: row['published_hint'], reverse=True)[:limit]


def article_fields(soup, publisher):
    """Bind the short notice to the publisher's own headline/body/date fields."""
    heading = soup.select_one(publisher['headline'])
    article = soup.select_one(publisher['body'])
    if heading is None or article is None:
        raise ValueError('web_source_article_structure_missing')
    clock = next((node.get_text(' ', strip=True) for node in soup.select(publisher['clock'])
                  if re.fullmatch(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}(?::\d{2})?', node.get_text(' ', strip=True))), None)
    if not clock:
        raise ValueError('web_source_time_missing')
    return heading, article, clock
