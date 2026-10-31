"""Optional mature main-text extraction; no network or publication-date guessing.

The result is a text candidate, not admission as today's news. All source/time
and access checks remain the caller's responsibility.
"""
import importlib.metadata
import re
from urllib.parse import urlsplit
from bs4 import BeautifulSoup


def reader_kind(url):
    parts=urlsplit(url);host=parts.hostname or ''
    if host in {'www.jisilu.cn','jisilu.cn','guba.eastmoney.com','www.taoguba.com.cn'}:return 'discussion'
    if 'vReport_Show' in parts.path:return 'research_summary'
    return 'article_candidate'


def extract_main_text(html,url):
    try:
        from trafilatura import extract
    except ImportError:
        return dict(status='unavailable',reason='generic_extractor_not_installed')
    raw=html if isinstance(html,bytes) else html.encode('utf-8')
    if len(raw)>2*1024*1024:return dict(status='rejected',reason='generic_html_size_limit')
    soup=BeautifulSoup(raw,'html.parser')
    from .overseas_sources import ld_restricted
    if ld_restricted(soup) or re.search(r'订阅后阅读|登录后阅读|subscribe to continue|sign in to continue',soup.get_text(' ',strip=True),re.I):
        return dict(status='rejected',reason='generic_restricted_content')
    page_title=soup.title.get_text(' ',strip=True) if soup.title else ''
    if (re.search(r'^(?:access denied|just a moment|verify you are human|人机验证)',page_title,re.I)
        or soup.select_one('form#challenge-form')):
        return dict(status='rejected',reason='generic_verification_page')
    # Do not extract hidden JSON articleBody, scripts, hidden subscribers' text,
    # or embedded comments. Publisher adapters retain their stronger guards.
    for node in list(soup.select('script,style,noscript,iframe,[hidden],[aria-hidden="true"]')):
        if node.parent is not None:node.decompose()
    for node in list(soup.select('[style]')):
        if node.parent is not None and re.search(r'display\s*:\s*none|visibility\s*:\s*hidden',node.get('style',''),re.I):
            node.decompose()
    text=extract(str(soup),url=url,include_comments=False,include_tables=True,with_metadata=False,
                 include_links=False,include_images=False) or ''
    warnings=[]
    if re.search(r'海量资讯|扫描二维码关注|点击加载更多|责任编辑',text):warnings.append('possible_boilerplate_requires_review')
    return dict(status='text_candidate' if len(text.strip())>=160 else 'insufficient_text',text=text,
        method='trafilatura',version=importlib.metadata.version('trafilatura'),warnings=warnings,
        publication_date_inferred=False,complete_document_verified=False,
        scope='algorithm_extracted_main_text_not_certified_full_article',
        limitation='正文算法可能漏段或混入页脚，表格顺序与数值对应须核对；不推断发布时间或宣称事实已验证。')
