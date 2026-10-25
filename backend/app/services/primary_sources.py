"""Issuer originals and dated government observations, selected by live business profile.

No search-engine snippets, credentials, inferred customers or guessed numeric fields.
Monthly operating releases are current-period baselines, never today's catalysts.
"""
from datetime import datetime, timedelta, timezone
import re
import threading
import time
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup
import requests

from .time_context import china_now
from .research_documents import read_pdf, excerpt

HEADERS = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.cninfo.com.cn/'}
CN = 'https://www.cninfo.com.cn'
SOURCES = {
    'moa': dict(url='https://xmsyj.moa.gov.cn/jcyj/', source='农业农村部畜牧兽医局',
                groups=[['畜产品和饲料集贸市场价格'], ['生猪收购和白条肉出厂价格']],
                selectors=['.TRS_Editor']),
    'nea': dict(url='https://www.nea.gov.cn/', source='国家能源局',
                groups=[['全社会用电量', '全国电力工业统计', '全国电力统计'],
                        ['电力市场', '电价']],
                selectors=['#detailContent', '.article-content']),
    'nbs_industry': dict(url='https://www.stats.gov.cn/sj/zxfb/', source='国家统计局',
                         groups=[['规模以上工业增加值']], selectors=['.trs_editor_view']),
    'nbs_energy': dict(url='https://www.stats.gov.cn/sj/zxfb/', source='国家统计局',
                        groups=[['能源生产情况']], selectors=['.trs_editor_view']),
}
BODY_TERMS = {
    '半导体': ['集成电路', '电子设备制造', '半导体', '计算机'],
    '电力': ['发电', '用电', '电力', '水电'],
    '汽车': ['汽车'], '新能源': ['太阳能', '电池', '新能源', '发电'],
    '资源': ['煤', '原油', '天然气', '有色', '钢'],
    '消费': ['消费', '食品', '饮料', '零售'],
    '养殖': ['生猪', '仔猪', '猪肉', '玉米', '豆粕', '饲料'],
}
OPERATING_TITLE = re.compile(r'销售简报|产销|主要经营数据|发电量|运营数据|经营情况|业务经营')
IMPORTANT_TITLE = re.compile(r'业绩|季度报告|年度报告|半年度报告|投资者关系|调研|订单|合同|投产|扩产|收购|重组|减持|增持|回购|诉讼|处罚|停产|复产|风险提示')
_locks = {}
_lock_guard = threading.Lock()


def cached(hub, key, ttl, fetch, attempt_version=None):
    # All stocks share government indexes and issuer identities; one fetch per cache key.
    with _lock_guard:
        lock = _locks.setdefault((str(hub.root), key), threading.Lock())
    with lock:
        from .source_health import ensure_active,record_failure
        ensure_active(hub.root,key)
        def attempt():
            try:
                return dict(ok=True, value=hub.cache(key, ttl, fetch))
            except Exception as error:
                record_failure(hub.root,key,error)
                reason=str(error)
                # Only our fixed parser diagnostics may enter the cache/logs.
                safe_reason=reason if (re.fullmatch(r'pdf_parser_exit:-?\d+',reason)
                    or reason in {'pdf_queue_budget_exhausted','pdf_parse_budget_exhausted',
                                  'pdf_download_budget_exhausted',
                                  'media_article_structure_missing','media_publication_missing',
                                  'media_full_body_unavailable','media_host_not_allowed',
                                  'media_budget_exhausted','media_response_invalid','media_api_response_invalid',
                                  'media_identity_or_access_rejected','media_access_unknown',
                                  'publisher_source_date_missing','publisher_public_page_state_missing',
                                  'publisher_identity_or_free_access_rejected','publisher_identity_rejected',
                                  'publisher_paid_access_rejected','publisher_full_body_unavailable',
                                  'publisher_restricted_content','publisher_time_budget_exhausted',
                                  'publisher_response_invalid','publisher_article_url_rejected',
                                  'publisher_host_or_path_rejected','overseas_full_body_unavailable',
                                  'overseas_restricted_content','overseas_source_time_missing',
                                  'overseas_source_timezone_missing','overseas_article_url_rejected',
                                  'overseas_response_invalid'}) else None
                return dict(ok=False, error=type(error).__name__, reason=safe_reason)
        attempt_key='primary:attempt:'+((attempt_version+':') if attempt_version else '')+key
        result = hub.cache(attempt_key, min(ttl,600), attempt)
        if not result['ok']:
            # Migrate old parser failures too, without re-requesting an article
            # merely to recover the diagnostic discarded by an older version.
            if result.get('error')=='ValueError' and not result.get('reason'):
                record_failure(hub.root,key,ValueError('legacy_negative_result_requires_review'))
            raise ValueError('cached_primary_failure:'+result['error']+
                             (':'+result['reason'] if result.get('reason') else ''))
        return result['value']


def request(url, deadline, data=None):
    remaining = deadline-time.monotonic()
    if remaining <= 0:
        raise TimeoutError('primary_source_budget_exhausted')
    response = requests.request('POST' if data is not None else 'GET', url, data=data,
                                headers=HEADERS, timeout=min(8, remaining), allow_redirects=False)
    response.raise_for_status()
    if response.status_code != 200:
        raise ValueError('primary_source_redirect')
    return response


def get_json(url, deadline, data=None):
    value = request(url, deadline, data).json()
    if not isinstance(value, dict):
        raise ValueError('primary_json_structure_invalid')
    return value


def html(url, deadline):
    response = request(url, deadline)
    response.encoding = 'utf-8'
    if len(response.content) > 3*1024*1024:
        raise ValueError('primary_html_size_limit')
    return response.text


def parse_date(value):
    for pattern in ('%Y-%m-%d %H:%M:%S', '%Y/%m/%d %H:%M', '%Y-%m-%d', '%Y/%m/%d'):
        try:
            return datetime.strptime(str(value), pattern)
        except ValueError:
            pass
    return None


def within(value, days, now):
    return value is not None and timedelta() <= now-value <= timedelta(days=days)


def failure(error):
    result = dict(error=type(error).__name__)
    if isinstance(error, ValueError):
        # Our ValueError messages are fixed parser/cooldown codes, never headers.
        result['reason'] = str(error)[:160]
    return result


def government_tasks(profile):
    families = set((profile or {}).get('families', []))
    tasks = []
    if '养殖' in families:
        tasks.append('moa')
    if '电力' in families:
        tasks.extend(['nea', 'nbs_energy'])
    if families & {'半导体', '汽车', '新能源', '资源', '消费'} and '养殖' not in families:
        tasks.append('nbs_industry')
    return tasks


def cninfo_notices(hub, stock, deadline):
    market = str(getattr(stock.market, 'value', stock.market))
    if market != 'A' or not stock.code.startswith(('0', '3', '6')):
        return [], dict(status='unsupported', reason='本适配器仅验证沪深A股原始披露，不套用港股或北交所标识')
    now = china_now()
    identities = cached(hub, 'cninfo:issuer-identities', 86400,
                        lambda: get_json(CN+'/new/data/szse_stock.json', deadline))
    rows = identities.get('stockList')
    if not isinstance(rows, list):
        raise ValueError('cninfo_identity_list_invalid')
    matches = [row for row in rows if str(row.get('code')) == stock.code and row.get('category') == 'A股']
    if len(matches) != 1 or not re.fullmatch(r'[A-Za-z0-9]+', str(matches[0].get('orgId', ''))):
        raise ValueError('cninfo_issuer_identity_missing')
    org = matches[0]['orgId']
    params = dict(pageNum=1, pageSize=50, column='sse' if stock.code.startswith('6') else 'szse',
                  tabName='fulltext', stock=stock.code+','+org,
                  seDate=(now-timedelta(days=35)).date().isoformat()+'~'+now.date().isoformat(),
                  searchkey='', isHLtitle='false', sortName='time', sortType='desc')
    data = cached(hub, 'cninfo:notices:'+stock.code, 1800,
                  lambda: get_json(CN+'/new/hisAnnouncement/query', deadline, params))
    rows = data.get('announcements')
    if rows is None and data.get('totalAnnouncement') == 0:
        rows = []
    if not isinstance(rows, list):
        raise ValueError('cninfo_announcement_list_invalid')
    candidates, failures, excluded = [], [], 0
    for row in rows:
        if str(row.get('secCode')) != stock.code or str(row.get('orgId')) != org:
            excluded += 1
            continue
        title = BeautifulSoup(str(row.get('announcementTitle', '')), 'html.parser').get_text(' ', strip=True)
        try:
            stamp = float(row['announcementTime'])
            published = datetime.fromtimestamp(stamp/1000, timezone(timedelta(hours=8))).replace(tzinfo=None)
        except (KeyError, ValueError, TypeError, OverflowError, OSError):
            excluded += 1
            continue
        operating = bool(OPERATING_TITLE.search(title))
        if not within(published, 35 if operating else 7, now):
            excluded += 1
            continue
        priority = 0 if within(published, 3, now) and IMPORTANT_TITLE.search(title) else 1 if operating else 2
        candidates.append((priority, published, title, row, operating))
    candidates.sort(key=lambda row: (row[0], -row[1].timestamp()))
    # One latest operating release, plus one fresh original notice. No filler when absent.
    selected, operating_seen = [], False
    for candidate in candidates:
        if candidate[4] and operating_seen:
            continue
        selected.append(candidate)
        operating_seen |= candidate[4]
        if len(selected) >= 2:
            break
    materials = []
    for _, published, title, row, operating in selected:
        identifier, path = str(row.get('announcementId', '')), str(row.get('adjunctUrl', ''))
        if not re.fullmatch(r'\d+', identifier) or not re.fullmatch(r'finalpage/\d{4}-\d{2}-\d{2}/'+identifier+r'\.PDF', path, re.I):
            failures.append(dict(title=title, error='invalid_original_pdf_identity'))
            continue
        url = 'https://static.cninfo.com.cn/'+path
        try:
            def parse_pdf():
                remaining = deadline-time.monotonic()
                if remaining <= 1:
                    raise TimeoutError('primary_pdf_budget_exhausted')
                return read_pdf(url, timeout=min(18, remaining))
            parsed = cached(hub, 'cninfo:pdf:'+identifier, 365*86400, parse_pdf)
            body = excerpt(parsed)
            compact = re.sub(r'\s+', '', body)
            expected_name = re.sub(r'\s+', '', matches[0]['zwjc'])
            if stock.code not in compact and expected_name not in compact:
                raise ValueError('original_pdf_issuer_not_found')
            material = hub.material(stock.name+'：'+title, '巨潮资讯公司原始披露', url,
                'operating_release' if operating else 'primary_notice', 'A:'+stock.code,
                '原始披露日期：'+published.date().isoformat()+'（日期粒度；不能当成精确首次公开时刻）。\n'
                +('这是最近35天内取得的最新一期经营基线，不能重包装成今日新闻；需核对文内统计期间。\n' if operating else '')
                +'日期窗口内的公告也不等于今日新增催化；必须核对是否已有市场反应。\n'
                +'PDF文本节选，表格列关系尚未人工核对；不得自行重算或错配数值。\n'+body,
                published, reading=parsed['reading_status']+'；入模为带页码节选；日期粒度')
            materials.append(material)
        except Exception as error:
            failures.append(dict(title=title, **failure(error)))
    return materials, dict(status='partial' if failures else 'ok' if materials else 'no_material',
        retrieved=len(rows), eligible=len(candidates), read=len(materials), failures=failures,
        excluded=excluded, list_truncated=bool(data.get('hasMore')),
        limitation='普通公告7天；最新经营披露35天仅作经营基线；无正文不提供给模型。清单仅首50条，不声明完整覆盖。')


def cninfo_financial(hub, stock, deadline):
    """Latest issuer periodic report; financial baselines have their own reporting cadence."""
    market=str(getattr(stock.market,'value',stock.market))
    if market!='A' or not stock.code.startswith(('0','3','6')):
        return [],dict(status='unsupported',reason='仅验证沪深定期报告原文')
    now=china_now()
    identities=cached(hub,'cninfo:issuer-identities',86400,
                      lambda:get_json(CN+'/new/data/szse_stock.json',deadline))
    issuer=next((row for row in identities.get('stockList',[]) if str(row.get('code'))==stock.code and row.get('category')=='A股'),None)
    if not issuer or not re.fullmatch(r'[A-Za-z0-9]+',str(issuer.get('orgId',''))):
        raise ValueError('financial_original_issuer_missing')
    org=issuer['orgId']
    params=dict(pageNum=1,pageSize=30,column='sse' if stock.code.startswith('6') else 'szse',
                tabName='fulltext',stock=stock.code+','+org,
                seDate=(now-timedelta(days=180)).date().isoformat()+'~'+now.date().isoformat(),
                category='category_ndbg_szsh;category_bndbg_szsh;category_sjdbg_szsh;category_yjdbg_szsh',
                searchkey='',isHLtitle='false',sortName='time',sortType='desc')
    data=cached(hub,'cninfo:financial-list:'+stock.code,21600,
                lambda:get_json(CN+'/new/hisAnnouncement/query',deadline,params))
    rows=data.get('announcements')
    if rows is None and data.get('totalAnnouncement')==0:
        rows=[]
    if not isinstance(rows,list):
        raise ValueError('financial_original_list_invalid')
    candidates=[]
    for row in rows:
        title=BeautifulSoup(str(row.get('announcementTitle','')),'html.parser').get_text(' ',strip=True)
        if (str(row.get('secCode'))!=stock.code or str(row.get('orgId'))!=org
                or not re.search(r'年度报告|半年度报告|季度报告',title)
                or any(word in title for word in ['摘要','英文','取消','更正','审计','董事会','监事会','决议'])):
            continue
        try:
            stamp=datetime.fromtimestamp(float(row['announcementTime'])/1000,timezone(timedelta(hours=8))).replace(tzinfo=None)
        except (KeyError,TypeError,ValueError,OverflowError,OSError):
            continue
        if within(stamp,180,now):
            candidates.append((stamp,title,row))
    candidates.sort(key=lambda item:item[0],reverse=True)
    if not candidates:
        return [],dict(status='no_material',retrieved=len(rows),read=0)
    published,title,row=candidates[0]
    identifier,path=str(row.get('announcementId','')),str(row.get('adjunctUrl',''))
    if not re.fullmatch(r'\d+',identifier) or not re.fullmatch(r'finalpage/\d{4}-\d{2}-\d{2}/'+identifier+r'\.PDF',path,re.I):
        raise ValueError('financial_original_pdf_identity_invalid')
    url='https://static.cninfo.com.cn/'+path
    def download():
        remaining=deadline-time.monotonic()
        if remaining<=1:
            raise TimeoutError('financial_original_budget_exhausted')
        # Full periodic reports are often >200 pages. Include parser-queue time,
        # but never exceed this stock's remaining collection deadline.
        return read_pdf(url,timeout=min(60,remaining))
    # Keep successful documents; only the failed-attempt namespace changes.
    parsed=cached(hub,'cninfo:financial-pdf:serial-v2:'+identifier,365*86400,download,
                  attempt_version='outer-budget-v3')
    body=excerpt(parsed)
    compact=re.sub(r'\s+','',body)
    if stock.code not in compact and re.sub(r'\s+','',issuer['zwjc']) not in compact:
        raise ValueError('financial_original_pdf_issuer_mismatch')
    item=hub.material(stock.name+'：'+title,'巨潮资讯公司定期报告原文',url,'financial_report','A:'+stock.code,
        '最新取得的定期报告是财务基线，不是当日催化；公告日期为日期粒度，统计期间以原文为准。'
        'PDF文本解析不代表表格数字已逐项复核；未提供给模型的页面不可补写内容。\n'+body,
        published,reading=parsed['reading_status']+'；解析'+str(parsed.get('read_pages','未知'))+'/'+str(parsed.get('total_pages','未知'))+'页；入模为带页码节选')
    return [item],dict(status='ok' if parsed['reading_status']=='full_text' else 'partial',
                       retrieved=len(rows),read=1,source='cninfo_original',
                       parsed_pages=parsed.get('read_pages'),total_pages=parsed.get('total_pages'))


def government_candidates(text, rule, now):
    soup = BeautifulSoup(text, 'html.parser')
    pool = []
    seen = set()
    dated_links = 0
    for a in soup.select('a[href]'):
        title = a.get_text(' ', strip=True)
        url = urljoin(rule['url'], a['href'])
        parsed = urlsplit(url)
        if parsed.scheme == 'http':
            url = url.replace('http://', 'https://', 1)
            parsed = urlsplit(url)
        if parsed.scheme != 'https' or parsed.hostname != urlsplit(rule['url']).hostname or parsed.query or parsed.fragment:
            continue
        match = re.search(r'/(\d{8})/|/t(\d{8})_', parsed.path)
        try:
            date = datetime.strptime(next(x for x in match.groups() if x), '%Y%m%d') if match else None
        except ValueError:
            continue
        if date:
            dated_links += 1
        # URL day is used only to avoid fetching old pages; publication must come from article metadata.
        if not within(date, 14, now) or url in seen:
            continue
        seen.add(url)
        for index, words in enumerate(rule['groups']):
            if any(word in title for word in words):
                pool.append((index, date, title, url))
                break
    if not dated_links:
        raise ValueError('official_index_has_no_dated_articles')
    return sorted(pool, key=lambda row: (row[0], -row[1].timestamp()))


def government_article(hub, identifier, title, url, profile, deadline):
    rule = SOURCES[identifier]
    raw = cached(hub, 'primary:article:'+url, 86400, lambda: html(url, deadline))
    soup = BeautifulSoup(raw, 'html.parser')
    meta = {str(m.get('name', '')).lower(): m.get('content', '') for m in soup.select('meta[name]')}
    published = parse_date(meta.get('pubdate') or meta.get('publishdate'))
    if not within(published, 14, china_now()):
        raise ValueError('official_publication_date_missing_or_stale')
    original_title = meta.get('articletitle')
    if not original_title or re.sub(r'\s+', '', original_title) not in re.sub(r'\s+', '', title):
        raise ValueError('official_title_identity_mismatch')
    root = next((soup.select_one(selector) for selector in rule['selectors'] if soup.select_one(selector)), None)
    if root is None:
        raise ValueError('official_body_missing')
    for script in root.select('script,style'):
        script.decompose()
    article_tables = {id(table) for table in root.select('table')}
    paragraphs = [p.get_text('', strip=True) for p in root.select('p')
                  if not any(id(parent) in article_tables for parent in p.parents)]
    if not paragraphs:
        for table in root.select('table'):
            table.decompose()
        paragraphs = [root.get_text(' ', strip=True)]
    terms = list(dict.fromkeys(word for family in (profile or {}).get('families', []) for word in BODY_TERMS.get(family, [])))
    relevant = [p for p in paragraphs if any(word in p for word in terms)]
    if not relevant:
        raise ValueError('official_body_not_relevant_to_business')
    body = '\n'.join(dict.fromkeys(relevant))
    if len(body) < 60:
        raise ValueError('official_body_too_short')
    origin = meta.get('contentsource') or meta.get('source')
    source = rule['source'] + ('网站（页面来源：'+origin+'）' if origin and origin != rule['source'] else '')
    return hub.material(original_title, source, url, 'industry_observation', profile['key']+':行业关联',
        '政府行业统计/政策原文节选；与公司仅为行业关联，不证明该公司受益。\n'
        '发布日期与数据统计期/采集日不同；以下可能是周度或月度数据，不是今日现货报价。'
        '行业平均价不能当成公司售价，行业产量不能当成公司订单。不解析表格数字，仅使用正文明确叙述。\n'+body[:6500],
        published, period='统计期见原文，不以发布日期替代', reading='与业务词匹配的原文段落节选')


def government_observations(hub, stock, deadline, profile):
    tasks = government_tasks(profile)
    if not tasks:
        return [], dict(status='unsupported', reason='当前主营尚无通过验证的行业原始数据适配器')
    materials, coverage = [], {}
    for identifier in tasks:
        rule = SOURCES[identifier]
        failures, read, selected = [], 0, set()
        try:
            index = cached(hub, 'primary:index:'+rule['url'], 1800, lambda: html(rule['url'], deadline))
            candidates = government_candidates(index, rule, china_now())
            for group, _, title, url in candidates:
                if group in selected:
                    continue
                selected.add(group)
                try:
                    materials.append(government_article(hub, identifier, title, url, profile, deadline))
                    read += 1
                except Exception as error:
                    failures.append(dict(title=title, **failure(error)))
            coverage[identifier] = dict(status='partial' if failures else 'ok' if read else 'no_material',
                                         read=read, candidates=len(candidates), failures=failures)
        except Exception as error:
            coverage[identifier] = dict(status='failed', **failure(error))
    failed = any(s['status'] in {'failed','partial'} for s in coverage.values())
    return materials, dict(status='partial' if failed and materials else 'failed' if failed else 'ok' if materials else 'no_material',
                             read=len(materials), sources=coverage,
                             limitation='仅已适配的官方栏目近14天原文；周/月数据按统计期间解释，不代表公司经营或实时市场价格。')
