"""Transparent topic diversity and business-overlap checks, without LLM calls."""
from collections import Counter,defaultdict,deque
import json
import re
from urllib.parse import urlsplit

from .news_selection import matches_watchlist,matching_text
from .news_quality import reading_scope,company_focus,priority
from .editorial_value import profile as editorial_profile,rank as editorial_rank


def editorial_exclusion(item, stocks):
    """Keep soft-feature material searchable, without filling initial story slots.

    This narrow screen is not a general financial relevance classifier.
    Concrete company and policy/operating events override a feature heading.
    """
    title=item.title
    from .editorial_value import promotion_reason
    if re.search(r'融资|热钱|引入.{0,8}资本|获.{0,8}投资',title) and editorial_profile(item)['kind']=='private_consumer_funding' and not matches_watchlist(item,stocks):
        return 'private_consumer_funding_without_watchlist_link'
    if promotion_reason(title):
        return 'commercial_promotion_not_primary_story'
    if re.search(r'论坛成功举办|采标企业名单.*揭晓|【直播(?:中)?】',title) and not any(company_focus(item,stock) for stock in stocks):
        return 'conference_promotion_not_primary_story'
    if re.search(r'(?:年会|大会|论坛|峰会).{0,24}(?:圆满|成功)(?:落幕|闭幕|举办|召开)',title) and not any(company_focus(item,stock) for stock in stocks):
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


def regulatory_population_key(item):
    """Narrow same-day batch warning anchor; changed counts/metrics stay distinct.

    Only an initial-reading slot is shared. All original reports remain searchable.
    """
    title=item.title
    if not re.search(r'点名|警示|警告',title):return None
    actor=re.search(r'香港证监会|香港證監會',title)
    count=re.search(r'(\d+)\s*(?:只港股|家(?:公司|企业))',title)
    text=matching_text(title,item.content)
    concentration=re.search(r'(?:股权|股權).{0,12}集中度.{0,20}?(\d+(?:\.\d+)?)\s*%',text)
    if concentration is None and re.search(r'股权.{0,8}集中|股權.{0,8}集中',text):
        concentration=re.search(r'股东[^。！？]{0,140}(?:合计|共计|总计)[^。！？]{0,20}?(\d+(?:\.\d+)?)\s*%',text)
    if not (actor and count and concentration):return None
    return ('hk_sfc_batch_concentration_warning',item.published_at.date().isoformat(),
            int(count.group(1)),float(concentration.group(1)))


def company_reporting_event(item, stocks):
    """Group current-company quarter disclosures and coverage, not different facts.

    An explicit report year and quarter/period are required. Publication year is
    never substituted. This limits initial reading only; all source IDs survive.
    """
    def focused_company(stock):
        if company_focus(item,stock):return True
        alias=re.sub(r'(?:股份|集团|控股|有限公司)+$','',stock.name)
        return len(alias)>=2 and item.title.startswith(alias) and stock.name in (item.content or '')[:600]
    if re.search(r'业绩预告|预告修正|更正|修订|收购|并购|诉讼|立案|处罚|股权激励',item.title):return None
    focused=[stock for stock in stocks if focused_company(stock)]
    if len(focused)!=1:return None
    text=matching_text(item.title,item.content)
    if not re.search(r'季报|季度报告|业绩|净利润|归母|调研活动|投资者关系|交流会',text[:2500]):return None
    fiscal=re.search(r'(20\d{2})\s*年\s*(?:(?:第|前)?\s*([一二三四1234])\s*季度|([半全])年度?(?:报告|业绩)|1\s*[-—至]\s*(3|6|9|12)\s*月)',text[:4000])
    if not fiscal:return None
    year=fiscal.group(1)
    quarter=({'一':1,'二':2,'三':3,'四':4}.get(fiscal.group(2),fiscal.group(2))
             if fiscal.group(2) else (2 if fiscal.group(3)=='半' else 4) if fiscal.group(3)
             else int(fiscal.group(4))//3)
    stock=focused[0]
    return str(getattr(stock.market,'value',stock.market))+':'+stock.code,year,int(quarter)


def primary_rate_decision(item):
    """One verified-address policy anchor, not every government item or forecast."""
    parts=urlsplit(item.source_url or '')
    return (item.source=='美联储公开原文' and parts.hostname=='www.federalreserve.gov'
        and bool(re.fullmatch(r'/newsevents/pressreleases/monetary\d{8}a\.htm',parts.path))
        and bool(re.search(r'\bFOMC\b.*\bstatement\b|联邦公开市场委员会.*声明',item.title,re.I)))


def topic(item):
    text=item.title
    if '公开市场业务' in text:return '国内流动性操作'
    if '私募投资母基金' in text:return '国内私募基金监管'
    if any(word in text for word in ('美联储','加息预期','议息')) or re.search(r'\bFOMC\b',text,re.I):return '美国货币政策'
    if (re.search(r'公募|基金',text) and re.search(r'季报|季度|Q[1-4]',text,re.I)
            and re.search(r'持仓|重仓|调仓|科技降温',text)):return '公募季度持仓'
    if any(word in text for word in ('AI','人工智能')) and any(word in text for word in ('抛售','止跌','发债','资本开支','高盛','对冲基金')):
        return '海外AI交易与融资'
    if any(word in text for word in ('原油','油价','石油','阿联酋')):return '能源供给与价格'
    return None


def operating_context(item,profile):
    """Narrow operating-variable reading leads, not a beneficiary assertion.

    This protects business evidence that lacks the watchlist name in its title.
    Fund holding lists and related links do not establish operating exposure.
    """
    if topic(item)=='公募季度持仓':return None
    business=' '.join(str((profile or {}).get(field) or '') for field in ('industry','business'))
    text=matching_text(item.title,item.content);lead=text[:800]
    from .editorial_value import CHANGE,NUMBER
    if not (CHANGE.search(lead) or NUMBER.search(lead)):return None
    if any(word in business for word in ('塑封料','环氧塑封','封装材料')):
        if re.search(r'塑封料|环氧模塑料|环氧塑封|封装材料',lead) and re.search(r'订单|需求|产能|售价|成本|库存',lead):
            return '封装材料经营变量'
    elif any(word in business for word in ('动力电池','锂电池','锂电')):
        if re.search(r'碳酸锂|锂价|锂盐',item.title) and re.search(r'价|库存|供给|供应|需求',lead):
            return '电池原料价格与供需'
    elif any(word in business for word in ('水电','水力发电')):
        from .news_selection import industry_terms
        if re.search(r'水电|流域|来水|水库',item.title) and industry_terms(text,('来水','水电发电量','水电电价')):
            return '水电经营与同业对照'
    elif any(word in business for word in ('生猪','养猪')):
        if re.search(r'猪价|生猪价格|能繁母猪|养殖成本|饲料价格',lead):
            return '养殖价格与供需'
    return None


def associations(item,stocks,profiles):
    """Overlap grades are reading guidance, never evidence of beneficiary or causation."""
    text=matching_text(item.title,item.content)
    result=[]
    for stock in stocks:
        key=str(getattr(stock.market,'value',stock.market))+':'+stock.code
        profile=profiles.get(key) or {}
        context=operating_context(item,profile)
        business=' '.join(str(profile.get(field) or '') for field in ('industry','business'))
        if matches_watchlist(item,[stock]):
            result.append(dict(stock=key,level='company_mention',focus='company_specific' if company_focus(item,stock) else 'body_mention',
                reason='原文提及名称或代码；不是独立核实、持仓或受益证明；综述提及不等于公司新增事件',operating_context=context))
            continue
        label='行业关联 '+key+'（'
        if label not in (item.market_impact or '') and not context:
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
            else:
                reason='旧行业标签仅词匹配；其他项目向水电站购电等背景不构成水电经营变化或公司关联'
        if context:
            level='business_overlap';reason='经营变量存在文本交集；具体产品、流域、定价与公司敞口仍需核验'
        result.append(dict(stock=key,level=level,reason=reason,operating_context=context))
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
    from .market_coverage import coverage_audit
    data=briefing(news,stocks,profiles)
    lines=['## 选题与业务关联核对',data['limitation'],
        '相同主题最多选一个主问题，其他报道用作补充或反证，不分成多个重复重点。',
        'keyword_only不能充当公司新增事实或核心短线理由；business_overlap仍需原文证明影响机制。']
    lines.append('市场覆盖阅读线索（不是已核实的交易日或因果）：'+json.dumps(coverage_audit(news,news),ensure_ascii=False,separators=(',',':')))
    lines.append('收盘综述可提供当天实际走势、量价与板块分化；媒体解释保留归属。月度/单日、盘前/收盘分开，不把先后发生当传导已证实；缺某市场材料不补编。')
    lines.append('阅读排序标签只来自文本线索，不是事实核验或投资评分；具体变化先核对口径，forecast_or_hypothesis必须保留预测归属和反证。')
    lines.append('commercial_promotion是展会招揽或产品推介线索，不作为核心投资理由；recap是带时点综述，不重复包装成多个独立催化。')
    for item in data['articles']:
        if item['topic'] or item['associations'] or item['editorial']['kind']!='unclassified':
            lines.append(json.dumps(dict(id=item['id'],topic=item['topic'],associations=item['associations'],
                reading_priority=item['editorial']['kind']),ensure_ascii=False,separators=(',',':')))
    return '\n'.join(lines)
