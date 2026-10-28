"""Transparent topic diversity and business-overlap checks, without LLM calls."""
from collections import Counter,defaultdict,deque
import json
import re
from urllib.parse import urlsplit

from .news_selection import matches_watchlist
from .news_quality import reading_scope,company_focus,priority
from .editorial_value import profile as editorial_profile,rank as editorial_rank


def editorial_exclusion(item, stocks):
    """Keep soft-feature material searchable, without filling initial story slots.

    This narrow screen is not a general financial relevance classifier.
    Concrete company and policy/operating events override a feature heading.
    """
    title=item.title
    from .editorial_value import promotion_reason
    if promotion_reason(title):
        return 'commercial_promotion_not_primary_story'
    if re.search(r'论坛成功举办|采标企业名单.*揭晓|【直播(?:中)?】',title) and not any(company_focus(item,stock) for stock in stocks):
        return 'conference_promotion_not_primary_story'
    if re.search(r'女首富|男首富|富豪榜|身家.{0,12}亿元',title) and not re.search(r'增持|减持|收购|质押|重组|控制权',title):
        return 'wealth_profile_without_operating_event'
    feature=re.search(r'人才培养|管理人才|会计学院|老有所依|走进卧室',title)
    event=re.search(r'业绩|财报|订单|中标|合同|收购|融资|上市|回购|销售额|收入|净利润|政策|补贴|征求意见|监管',title)
    if feature and not event and not any(company_focus(item,stock) for stock in stocks):
        return 'soft_feature_without_concrete_market_event'
    return None


def diverse_rank(news):
    """Interleave publishers within reading-completeness tiers, without a quota.

    Editorial diversity is not independent corroboration. No article is removed
    from the episode workspace, and company/market buckets still take priority.
    """
    groups=defaultdict(deque)
    for item in sorted(news,key=editorial_rank,reverse=True):
        host=urlsplit(item.source_url or '').hostname or item.source
        if host.startswith(('www.','m.')):host=host.split('.',1)[1]
        groups[(priority(item)[0],editorial_profile(item)['priority'],host)].append(item)
    result=[]
    for tier in sorted({key[:2] for key in groups},reverse=True):
        keys=sorted([key for key in groups if key[:2]==tier],key=lambda key:editorial_rank(groups[key][0]),reverse=True)
        while any(groups[key] for key in keys):
            for key in keys:
                if groups[key]:result.append(groups[key].popleft())
    return result


def consultation_key(item):
    """One editorial slot for the same agency/document/day consultation.

    Not source deduplication: the notice and explanation remain readable in
    the episode pool. Different documents, dates or final rules stay separate.
    """
    if item.source not in {'证监会原文','央行新闻原文'} or '征求意见' not in item.title:return None
    match=re.search(r'《([^》]+)》',item.title)
    if not match:return None
    return item.source,match.group(1),item.published_at.date().isoformat(),'consultation'


def topic(item):
    text=item.title
    if '公开市场业务' in text:return '国内流动性操作'
    if '私募投资母基金' in text:return '国内私募基金监管'
    if any(word in text for word in ('美联储','加息预期','议息')):return '美国货币政策'
    if any(word in text for word in ('AI','人工智能')) and any(word in text for word in ('抛售','止跌','发债','资本开支','高盛','对冲基金')):
        return '海外AI交易与融资'
    if any(word in text for word in ('原油','油价','石油','阿联酋')):return '能源供给与价格'
    return None


def associations(item,stocks,profiles):
    """Overlap grades are reading guidance, never evidence of beneficiary or causation."""
    text=item.title+' '+(item.content or '')
    result=[]
    for stock in stocks:
        key=str(getattr(stock.market,'value',stock.market))+':'+stock.code
        profile=profiles.get(key) or {}
        business=' '.join(str(profile.get(field) or '') for field in ('industry','business'))
        if matches_watchlist(item,[stock]):
            result.append(dict(stock=key,level='company_mention',focus='company_specific' if company_focus(item,stock) else 'body_mention',
                reason='原文提及名称或代码；不是独立核实、持仓或受益证明；综述提及不等于公司新增事件'))
            continue
        label='行业关联 '+key+'（'
        if label not in (item.market_impact or ''):
            continue
        level='keyword_only';reason='只有行业词匹配，尚未证明具体产品、经营指标或交易影响'
        if any(word in business for word in ('塑封料','环氧塑封','封装材料')):
            if any(word in text for word in ('塑封料','环氧模塑料','环氧塑封','封装材料')):
                level='business_overlap';reason='材料环节存在文本交集；具体规格、客户和份额仍未知'
            elif any(word in text for word in ('基板','FC-BGA','载板')):
                reason='报道对象是基板/载板，不能等同塑封材料需求或该公司订单'
        elif any(word in business for word in ('生猪','养猪','养殖')):
            if any(word in text for word in ('生猪价格','猪价','活猪收购','能繁母猪','出栏','养殖成本','饲料价格')):
                level='business_overlap';reason='涉及养殖经营变量；区域、口径与该公司敞口仍需核验'
            elif '屠宰' in text:
                reason='屠宰项目属不同经营环节；缺少采购、猪价及供给变化证据'
        elif any(word in business for word in ('水电','水力发电')):
            from .news_selection import industry_terms
            if industry_terms(text,('来水','水电发电量','水电电价','水电站')):
                level='business_overlap';reason='涉及水电经营变量；流域、交易电价及公司敞口仍需核验'
        result.append(dict(stock=key,level=level,reason=reason))
    return result


def weak_industry_only(item,stocks,profiles):
    rows=associations(item,stocks,profiles)
    return bool(rows) and all(row['level']=='keyword_only' for row in rows)


def briefing(news,stocks,profiles,selected=None):
    selected=selected if selected is not None else news
    counts=Counter(topic(item) for item in news if topic(item))
    selected_ids={item.id for item in selected}
    rows=[dict(id=item.id,title=item.title,source=item.source,url=item.source_url,
               published=item.published_at.isoformat(),topic=topic(item),
               reading_scope=reading_scope(item),
               editorial=editorial_profile(item),
               associations=associations(item,stocks,profiles),selected=item.id in selected_ids) for item in news]
    return dict(article_count=len(news),selected_articles=len(selected_ids),topic_counts=dict(counts),
        editorial_counts=dict(Counter(row['editorial']['kind'] for row in rows)),
        selected_editorial_counts=dict(Counter(row['editorial']['kind'] for row in rows if row['selected'])),
        direct_company_articles=sum(any(row['level']=='company_mention' for row in item['associations']) for item in rows),
        company_specific_articles=sum(any(row.get('focus')=='company_specific' for row in item['associations']) for item in rows),
        business_overlap_articles=sum(any(row['level']=='business_overlap' for row in item['associations']) for item in rows),
        keyword_only_articles=sum(bool(item['associations']) and all(row['level']=='keyword_only' for row in item['associations']) for item in rows),
        limitation='主题分组用于控制重复，不等于同一事件合并；不同报道仍保留证据ID。关联等级只说明文本交集，不证明影响方向或独立佐证。',articles=rows)


def prompt(news,stocks,profiles):
    data=briefing(news,stocks,profiles)
    lines=['## 选题与业务关联核对',data['limitation'],
        '相同主题最多选一个主问题，其他报道用作补充或反证，不分成多个重复重点。',
        'keyword_only不能充当公司新增事实或核心短线理由；business_overlap仍需原文证明影响机制。']
    lines.append('阅读排序标签只来自文本线索，不是事实核验或投资评分；具体变化先核对口径，forecast_or_hypothesis必须保留预测归属和反证。')
    lines.append('commercial_promotion是展会招揽或产品推介线索，不作为核心投资理由；recap是带时点综述，不重复包装成多个独立催化。')
    for item in data['articles']:
        if item['topic'] or item['associations'] or item['editorial']['kind']!='unclassified':
            lines.append(json.dumps(dict(id=item['id'],topic=item['topic'],associations=item['associations'],
                reading_priority=item['editorial']['kind']),ensure_ascii=False,separators=(',',':')))
    return '\n'.join(lines)
