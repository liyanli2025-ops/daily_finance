"""Per-statement discovery, not automatic truth or investment-value scoring."""
from collections import defaultdict,deque
from datetime import datetime,timedelta
import hashlib,re

from ..models.news import News


def cues(text):
    """Describe explicit textual cues. Unsupported guesses remain guesses."""
    tags=[]
    if re.search(r'https?://\S+',text):tags.append('linked_reference')
    if re.search(r'\d+(?:\.\d+)?\s*(?:%|亿|万|吨|bp|基点|户|元)',text,re.I):tags.append('numeric_claim')
    if re.search(r'相比|比较|占比|降幅|环比|同比|流通市值|前后|相对',text):tags.append('comparison')
    if re.search(r'库存|排产|订单|交期|报价|回款|渠道|保证金|融资余额|融资融券|兑付|赎回|贴水|折溢价',text):tags.append('operating_or_trading_detail')
    if re.search(r'我(?:看到|查到|问|买|卖|持有|参与)|我们(?:公司|厂|店)|据(?:报|说)|听说|称|透露',text):tags.append('attributed_or_personal_observation')
    if re.search(r'不一定|不能|不同意|不算|但|然而|只是|而非',text):tags.append('different_explanation')
    if re.search(r'\b(?:inventory|backlogs?|capacity|deliveries|redemptions?|margin calls?|lead times?)\b',text,re.I):tags.append('operating_or_trading_detail')
    if re.search(r'\b(?:however|alternative explanation|does not imply|rather than)\b',text,re.I):tags.append('different_explanation')
    if re.search(r'\b(?:I observed|we observed|our factory|according to|reportedly)\b',text,re.I):tags.append('attributed_or_personal_observation')
    if re.search(r'猜|可能|或许|大概|感觉|肯定|必然|将会|下周.*更',text):tags.append('speculative_language')
    generic=bool(re.fullmatch(r'[\s.。!！?？]*(?:如题|太正常了|难受|吾命休矣|跌吧|希望涨|支持|赞)[\s.。!！?？]*',text))
    # A number alone is not a reason to prioritize; non-numerical industry
    # observations and opposing explanations must also get reading chances.
    substantive=bool(set(tags)&{'linked_reference','operating_or_trading_detail','different_explanation','attributed_or_personal_observation'})
    return dict(tags=tags,reading_tier=0 if generic else 2 if substantive else 1,
                status='textual_cues_not_verified_value',requires_verification=True)


def order_records(records):
    """Different threads and speakers get turns; no deletion or daily count cap."""
    result=[]
    for tier in (2,1,0):
        threads=defaultdict(lambda:defaultdict(deque))
        for row in records:
            if row['cues']['reading_tier']==tier:
                threads[row['url']][row['statement'].get('author') or 'unknown'].append(row)
        queues={}
        for url,speakers in threads.items():
            # Preserve source order within each speaker, rotate speakers.
            q=deque()
            while any(speakers.values()):
                for own in speakers.values():
                    if own:q.append(own.popleft())
            queues[url]=q
        providers=defaultdict(deque)
        for q in queues.values():
            item=q[0].get('item');provider=getattr(item,'source','unknown')
            providers[provider].append(q)
        while any(providers.values()):
            for threads in providers.values():
                if not threads:continue
                q=threads.popleft();result.append(q.popleft())
                if q:threads.append(q)
    return result


def statement_documents(thread_news,threads,now,hours):
    """Keep a complete current-statement pool; prepare readable portions later.

    Parent context is explicitly a fragment. Full thread reading remains an
    available option, so a late reply does not require resending the whole page.
    """
    by_url={item.source_url:item for item in thread_news};records=[]
    for thread in threads:
        item=by_url.get(thread['url'])
        if item is None:continue
        for row in thread['statements']:
            if not now-timedelta(hours=hours)<=datetime.fromisoformat(row['published_at'])<=now:continue
            records.append(dict(url=thread['url'],thread=thread,item=item,statement=row,cues=cues(row['text'])))
    documents=[];catalogue=[]
    for record in order_records(records):
        row=record['statement'];thread=record['thread'];item=record['item'];root=thread['statements'][0]
        identifier='discussion-statement-'+hashlib.sha256((row['id']+'\0'+row['published_at']).encode()).hexdigest()[:24]
        pieces=[f'[发言位置：{row["position"]}；公开账号：{row["author"] or "未知"}；发言时间：{row["published_at"]}；未经核实]\n'+row['text']]
        for text in row.get('quoted_context',[]):pieces.append('[引用上下文；被引作者未核]\n'+text)
        if row['position']!=root['position'] and datetime.fromisoformat(root['published_at'])<=now:
            end=min(300,len(root['text']))
            pieces.append(f'[原帖背景片段：{root["published_at"]}；账号：{root["author"] or "未知"}；字符0:{end}/{len(root["text"])}；非本条新发言]\n'+root['text'][:end])
        pieces.append('[范围说明] 当前发言及标明范围的上下文；不是完整讨论串。可按原链接请求granularity=thread补读可见整页。')
        # Parent changes create a new immutable evidence version, too.
        content='\n\n'.join(pieces)
        identifier+='-'+hashlib.sha256(content.encode()).hexdigest()[:8]
        title=thread['title']+'｜'+(row['author'] or '未知账号')+'：'+re.sub(r'\s+',' ',row['text'])[:35]
        documents.append(News(id=identifier,title=title,content=content,source=item.source,
            source_url=item.source_url,published_at=datetime.fromisoformat(row['published_at']),
            related_stocks=item.related_stocks,category='参与者具体发言',importance_score=.5,
            market_impact=thread['source_role']+'；仅发言和背景片段，线索标签不是真实性、投资价值或全网代表性判断。'))
        catalogue.append(dict(id=identifier,url=row['url'],position=row['position'],author=row['author'],
            published_at=row['published_at'],cues=record['cues'],preview=row['text'][:100],
            reading_status='statement_catalogue_not_model_read_receipt'))
    return documents,catalogue
