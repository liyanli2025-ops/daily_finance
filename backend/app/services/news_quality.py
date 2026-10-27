"""Reading scope and admission rules shared by collection and report selection."""
import re
from urllib.parse import urlsplit

from .evidence import article_url

FEEDS={'金十数据','东方财富研报','百度财经焦点','百度股票焦点','百度国际新闻','百度社会新闻',
       '百度科技焦点','香港经济日报','信报财经新闻','36氪快讯','Finviz美股新闻','格隆汇7x24快讯',
       '华尔街见闻-全球','华尔街见闻-股市','格隆汇港股','IT之家'}
AUTOMATED=re.compile(r'获融资买入|融资余额.*占流通|(?:融资|融券)余额.*分位|主力资金净流入')


def company_focus(item,stock):
    """A body mention alone does not earn a company-specific editorial slot."""
    return bool((stock.name and stock.name in item.title)
        or re.search(r'(?<!\d)'+re.escape(stock.code)+r'(?!\d)',item.title)
        or ((item.source or '').startswith('上市公司公告-') and stock.code in (item.related_stocks or [])))


def reading_scope(item):
    source=item.source or ''
    if source=='东方财富研报':return 'research_excerpt'
    if (source in {'华尔街见闻原文','证券时报原文','证监会原文','央行新闻原文','央行公开市场操作原文',
                   '新浪财经-逐股新闻','新浪财经-自动生成快讯'}
            or source.startswith('上市公司公告-东方财富披露镜像-')):
        return 'full_text'
    if source.startswith('微信公众号原文-'):return 'full_text'
    if source in {'经济观察网公开原文','界面新闻公开原文','上海有色网公开原文','TrendForce公开研究发布'}:return 'full_text'
    if source in {'BBC公开原文','Guardian公开原文','美联储公开原文','美国财政部公开原文','EIA公开原文'}:return 'full_text'
    if source in {'财联社公开原文','中国证券网公开原文','第一财经公开原文','21世纪经济报道公开原文',
                   '中证网公开原文','每日经济新闻公开原文','发改委公开原文','上交所公开原文'}:return 'full_text'
    if source in FEEDS:return 'feed_excerpt'
    if '快讯' in source:return 'wire_text'
    return 'unverified_text'


def excluded_reason(item):
    if not article_url(item.source_url):return 'untraceable_url'
    parts=urlsplit(item.source_url)
    if parts.hostname in {'wallstreetcn.com','www.wallstreetcn.com'} and re.match(r'^/(member|premium|vip)/',parts.path):
        return 'restricted_article'
    if ('自动生成快讯' in (item.source or '') or '/aiassist/' in parts.path
            or AUTOMATED.search(item.title)):
        return 'automated_market_bulletin'
    from .evidence_audit import title_only
    if title_only(item):return 'title_only'
    return None


def priority(item):
    # This is evidence completeness, NOT truth, independent corroboration or importance.
    rank={'full_text':3,'wire_text':2,'feed_excerpt':1,'research_excerpt':0,'unverified_text':0}
    return rank[reading_scope(item)],item.importance_score,item.published_at


def scope_label(item):
    return {'full_text':'已读取原文主体；不代表独立核实',
            'feed_excerpt':'RSS采集文本/摘要，未核验完整正文；只能按所给文本引用',
            'research_excerpt':'研报采集摘要，未核验完整PDF；仅为带归属的观点背景',
            'wire_text':'快讯文本，未读取扩展报道',
            'unverified_text':'采集文本，正文阅读范围未确认'}[reading_scope(item)]
