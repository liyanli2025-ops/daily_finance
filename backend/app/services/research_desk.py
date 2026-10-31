"""A research dossier is distinct from an episode's short editorial selection.

The model supplies judgement; code checks scope, provenance and acknowledged
blocking gaps. A valid dossier is not proof of relevance, truth or forecast skill.
"""
import json
import re
from .research_hub import save_json,stock_key

AREAS=('a_market','hk_market','global','macro_policy','industries',
       'major_company_risk','watchlist','price_structure')
STATES={'body_checked','catalogue_checked','scoped_search_checked','missing','not_applicable'}

INSTRUCTIONS='''
## 研究底稿与节目选题分开
你的任务是替日内至数日交易的A/H投资者建立当期资料底稿，再选择值得讲的重点。
先检查全市场，不把自选股或初读正文当搜索边界。不要预先只找一两件事，也不为凑篇数加入普通公司财报。
按A股、港股、海外及跨市场、宏观政策、行业经营、重大公司风险、动态自选股、行情结构检查。
研究层保留相关事实、竞争解释和反证；节目层可简短。不要因节目简短就缩小取材。
判断值得深入，要说明：发生了什么新变化、改变了什么决策前提、影响谁、如何传导、价格是否支持、有何反证、何时验证。
从投资者的疑问出发：市场正在重新评估什么，哪条原先的判断需要改变，哪些风险或机会值得下一交易时段跟踪？不要把一串新闻摘要当分析。
优先调查市场主线与重要分歧、政策/利率/汇率/商品的跨市场冲击、行业订单/库存/价格/利润变化、重大公司事件与风险传染，再判断动态自选股的实际敞口。热度、财报数量和搜索排序本身不是重要性的证据。
同一事件以最有信息增量的材料为入口，补充材料用于新增事实或反方；公告与媒体报道可能互补，也可能只是转述，不能重复计成两个重大变化或两份独立证实。
早期线索可以保留为待观察假设，须说明线索来自什么、为何可能重要、还缺哪一环；不能把“报道少”说成“市场未定价”。不必等百分百确定才给倾向，也不能用倾向替代事实。
公司收入/利润同比增长不自动重要，须拆基数、并表、环比、指引、现金流及可查预期。政策区分表态/执行，财报旧信息不当新催化。
重要非自选公司需解释行业代表性或事件影响；宽泛行业词和宣传不能证明关联。自选股无新增消息可以接受，但注明检索范围和可用经营/价格背景。
价格反应、估值及经营是不同证据；不能凭涨跌证明原因、资金意图或未定价。多个同源技术指标不是独立证实。
标题/摘要可用于发现，不能写作已核实事实。核心问题和有力反方若仅有标题，先读正文；缺原始披露、同口径数据或重要跨市场事实时主动补查。
search_materials查当期完整池，read_material/read_materials补读；search_public仅是两个已接媒体的定向查询，不是全网搜索。
search_web只在配置并显式启用的外部搜索可用时工作，返回目录不是正文；read_public_url读取公开网页可见正文，不绕过付费或登录。
工具不可用、超时或预算耗尽，要留下缺口，不解释成没有新闻。不要为工具调用而调用；已足够的材料不重复花费。

## 美股与重要外盘是独立研究范围
美股及重要外盘不能只当A/H收评的背景，也不能只搜海外科技财报。全球重大变化即使尚无直接A/H传导证据，也可有独立信息价值；保留并注明关联待核，不硬套自选股，不因关联未证实就全部筛掉。
按当期重要性检查以下方向；这是发现问题的清单，不是每日篇数、国家或节目配额：
- 重要行情：美股主要指数、行业/风格与关键公司，必要时欧洲、日本等市场；同时留意国债收益率/利差、美元及主要汇率、原油/天然气、黄金/工业金属、波动率和信用风险。数字背后的异常变化、市场分化和跨资产冲突比逐项报点更重要。
- 政策与宏观：主要央行、通胀/就业/增长数据、财政与债务、关税/贸易/出口管制、监管和制裁；区分拟议、通过、生效和实际执行。没有可查的一致预期或此前状态，不编造“超预期”“市场早已消化”。
- 重要公司与产业：经营指引、资本开支、现金流、订单、融资/评级、并购、违约、产品与供应链变化；包括影响广的非自选公司，说明其代表性或事件影响，不收集普通财报填空。
- 重大舆情与市场分歧：机构公开观点、调查/做空报告、诉讼、治理争议及广泛传播但待核的说法。追到原报告、当事方回应和反证；热度不等于真实性，机构观点不当事实，同源转载不当多源证实。可能影响市场的未确认线索单列monitor，不写成定论。
- 国际事件与外溢：地缘冲突、能源/航运与供应中断、金融稳定风险等；区分实际事件、政治表态和情景推测，不按新闻标题自动推导行业受益/受损。
逐项对齐美国/当地交易日期、来源时区、北京时间、盘前/盘中/收盘/盘后和节目截止时点；注意节假日与夏令时，不把盘后跌幅当收盘跌幅，不把A/H收盘后发生的外盘消息倒写为当日A/H下跌原因。新消息与旧行情可比较，但不能冒充消息后的市场反应。
每个值得研究的外盘问题说明：新增变化与旧背景、直接受影响对象、可能向A/H传导的经营/估值/利率/汇率/风险偏好渠道、尚缺环节、竞争解释及下个可观察条件。已知事实与判断分开；实际价格反应与新闻叙事相反时保留反证，不编资金意图。
global覆盖记录的explanation要交代实际检查过的行情、政策宏观、公司产业、舆情/国际风险及其遗漏；只读一条联储声明或一份科技财报不能称外盘覆盖充分。未读、未搜、工具失败和重要缺口如实区分；不为覆盖标签增加无用请求，不宣称穷尽全网。

## 主动搜索为主，固定信源只做有目的的增量研究
主动搜索与已核对正文构成主资料；固定媒体不是平行重做一轮全市场采集，而是围绕主资料检查遗漏、新进展、原始依据、反证和有意义的细节。已有固定源池可以先检索复用；不要因它篇数多就让普通财报和重复叙事挤掉主线。
保留目录级查漏来发现主资料之外的新问题，不把固定源锁死在已选主题内。目录出现相同新闻可以是判重所需，不等于要把相同正文再次下载、再次送模型；仅凭目录不能确定内容无增量时，明确标为待比较。
“已覆盖”应具体到主体、事件、统计期间、指标/条款、来源与实际提供的文字范围；搜到标题不算核实，正文读过也不证明结论正确。不凭同公司、同主题或同标题就省略所有后续材料；新时点、新条款、公司回应、独立调查和有力反方仍可能有增量。
调用固定媒体补查或追加正文前，在reason说明已有依据、缺口和可能增加什么，只做以下有实质意义的补充：遗漏事件；更新/修订；原始披露/关键上下文；反证/不同解释；尚未确认但值得验证的早期线索。先检索本期资料池与已存文字，再考虑新请求；相同已存页面默认复用，来源或版本尚未比较时不宣称“无增量”。
固定源补充首先是素材采集，不是先列财务追问或强迫每条线索形成投资结论。收集可查的基础信息、文章正文里的采访细节、知情人士/业内人士说法、据报事项、爆料、公司回应，以及公开论坛/股吧/讨论串里的投资者观察、争论、猜测和不同解释。正文深处、问答、脚注、评论回复中的有用材料，不因没有进入新闻标题就忽略；论坛讨论也不必等媒体报道后才记录。
先记录具体说法本身：忠实摘录或明确标为转述，保留是谁说的/账号或匿名身份、原始链接/帖子或评论位置、发布时间与所述事件时间、上下文、对方给出的依据、回应/反方及是否已核。没有原话不加引号，身份未经验证不称“业内人士”。只有标题/片段、原帖未取得、时间未知也明确注明，不补编；仅搜索摘要不能升级为已核正文。
涉及业务、行业、政策或重大市场事件的具体未确认说法可以先作为线索入当期底稿，不因缺完整因果、基线或可量化影响而提前丢弃。保留原始说法与后续分析的区别；采集时不必为每条素材附完整主假设、反证和失效条件，分析阶段再判断重要性、可信度和关联。
区分公开披露事实、媒体转述、知情人士爆料、个人观察、猜测与情绪表达。情绪和重复喊涨喊跌不等于独立信息；重复转述可合并，但有新增细节、回应或不同论据的同题讨论保留。点赞、转发或多人复述不等于证实，不臆造传播规模，不把多次转载算多个独立爆料。与投资无关的闲聊、广告及无信息增量的刷屏不堆进正文。
仅收集可合法公开访问的内容，不要求进入私人群聊、取得非公开账号权限或绕过登录/付费限制；未实际读到的论坛不写成已覆盖。不能因论坛入口不可用就宣称没有讨论。
已有事实的纯转述、无新增内容的重复评论、普通无关财报不重复扩写或补读。真实交叉核验有价值，但必须比较事实、数据和上游来源，不以转载数量当独立验证。
不把“不太为人知”写成已证实传播程度或“尚未定价”；本系统不能保证发现隐秘信息。主动搜索不可用时记录真实能力和覆盖缺口，不假装完成搜索，也不静默用固定池数量冒充主资料合格。

每轮回复用一个JSON对象，禁止在外面另写报告：
{"action":"request_evidence","research":RESEARCH,"requests":[{"tool":"search_materials","query":"具体疑问","reason":"为何可能改变判断"}]}
或 {"action":"complete_research","research":RESEARCH,"report":"按原报告要求写的完整Markdown及原要求的元数据块"}
RESEARCH结构：
{"coverage":[{"area":"a_market","status":"body_checked","evidence_ids":["完整ID"],"explanation":"检查了什么、范围及仍缺什么"}],
 "watchlist_checks":[{"key":"A:当前代码","status":"catalogue_checked","evidence_ids":[],"explanation":"当前公司/行业/价格检查结果"}],
 "questions":[{"id":"Q1","title":"具体研究问题","selected":true,"priority":"high","status":"supported",
 "support_ids":["完整ID"],"counter_ids":[],"what_changed":"新增与旧背景分开",
 "why_it_matters":"对日内至数日的决策意义","mechanism":"有依据的传导或明确标为假设",
 "alternative":"最有力的竞争解释或尚未知","what_to_watch":"对象、期限、可观察变化及修正判断的条件"}],
 "omissions":[{"title":"未展开的材料或问题","reason":"低增量/重复/时效/无关联/缺证据等实际原因"}]}
coverage必须包含a_market,hk_market,global,macro_policy,industries,major_company_risk,watchlist,price_structure；不是要求八个节目主题。
status可为body_checked/catalogue_checked/scoped_search_checked/missing/not_applicable，后四种不能冒充读到正文；解释范围。price_structure可注明本期提供的行情而不造新闻ID。
每个当前自选股需有watchlist_checks，名称和行业不得写死。没有名单时为空。
questions数量按实际问题决定，不设节目篇数目标。status可为supported/needs_reading/needs_search/monitor/background/discarded；priority为high/normal。
交成稿时须有实际选题记录；没有选中的问题就不交一篇空洞的报告。未展开的重要线索保留在底稿，不因没选入节目而抹掉。
选中的高优先级问题若仍needs_reading或needs_search，不能直接交成稿。未来尚未发生的验证用monitor，不伪装成已经核验。
supported问题应有实际提供过正文的支持ID；纯价格问题可用basis=price_only，但仅在确有本期行情输入时使用。
引用原有完整[N:ID]，目录C编号先读取后再引用。研究回执会保存供检查，但不朗读给听众。
'''


def decode(text):
    text=text.strip()
    if text.startswith('```json') and text.endswith('```'):text=text[7:-3].strip()
    try:data=json.loads(text)
    except (ValueError,TypeError):raise RuntimeError('缺少结构化研究底稿，保留回复，不自动重试或发布') from None
    if not isinstance(data,dict) or data.get('action') not in {'request_evidence','complete_research'}:
        raise RuntimeError('研究回复动作无效，停止发布')
    return data


def validate(data,workspace,stocks):
    research=data.get('research')
    if not isinstance(research,dict):raise RuntimeError('研究底稿缺失')
    def text(row,key):
        value=row.get(key)
        if not isinstance(value,str) or not value.strip():raise RuntimeError('研究说明缺失：'+key)
    def ids(row,key,confirmed=False):
        values=row.get(key,[])
        if not isinstance(values,list) or any(not isinstance(x,str) or x not in workspace.documents for x in values):
            raise RuntimeError('研究引用不在当期池：'+key)
        if confirmed and any(not workspace.confirmed.get(x) for x in values):
            raise RuntimeError('研究将未提供正文的材料当作已读')
        return values
    def coverage(rows,field,expected):
        if not isinstance(rows,list) or any(not isinstance(row,dict) for row in rows):raise RuntimeError('研究覆盖记录无效')
        if len(rows)!=len(expected) or {row.get(field) for row in rows}!=set(expected):raise RuntimeError('研究覆盖对象不完整或重复')
        for row in rows:
            text(row,'explanation')
            if row.get('status') not in STATES:raise RuntimeError('研究覆盖状态无效')
            found=ids(row,'evidence_ids',row['status']=='body_checked')
            price=(field=='area' and row.get('area')=='price_structure' and getattr(workspace,'price_context_present',False))
            if row['status']=='body_checked' and not found and not price:raise RuntimeError('已读覆盖缺少正文依据')
            if row['status']=='scoped_search_checked' and not any(
                entry['request'].get('tool') in {'search_materials','search_public','search_web'}
                and entry['result'].get('status') not in {'failed','unavailable','disabled','budget_exhausted'} for entry in workspace.journal):
                raise RuntimeError('研究声称已搜索但没有成功工具记录')
    coverage(research.get('coverage'),'area',AREAS)
    coverage(research.get('watchlist_checks'),'key',[stock_key(stock) for stock in stocks])
    questions=research.get('questions')
    if not isinstance(questions,list):raise RuntimeError('研究问题记录缺失')
    names=set();blockers=[]
    for row in questions:
        if not isinstance(row,dict):raise RuntimeError('研究问题格式无效')
        for key in ('id','title','what_changed','why_it_matters','mechanism','alternative','what_to_watch'):text(row,key)
        if row['id'] in names:raise RuntimeError('研究问题编号重复')
        names.add(row['id'])
        if type(row.get('selected')) is not bool or row.get('priority') not in {'high','normal'}:raise RuntimeError('研究选择依据无效')
        status=row.get('status')
        if status not in {'supported','needs_reading','needs_search','monitor','background','discarded'}:raise RuntimeError('研究问题状态无效')
        support=ids(row,'support_ids',status=='supported');ids(row,'counter_ids',status=='supported')
        if status=='supported' and not support and not (row.get('basis')=='price_only' and getattr(workspace,'price_context_present',False)):
            raise RuntimeError('已支持研究问题缺少实际正文或行情')
        if row['selected'] and row['priority']=='high' and status in {'needs_reading','needs_search'}:blockers.append(row['id'])
    omissions=research.get('omissions')
    if not isinstance(omissions,list):raise RuntimeError('研究取舍记录缺失')
    for row in omissions:
        if not isinstance(row,dict):raise RuntimeError('研究取舍格式无效')
        text(row,'title');text(row,'reason')
    result=dict(research,blocking_questions=blockers,
        status='needs_evidence' if blockers else 'recorded_for_human_review',
        limitation='模型的研究与取舍说明；程序仅核对对象、工具记录和提供范围，不证明事实正确、重要性、独立性或预测有效。')
    save_json(workspace.path/'research-dossier.json',result)
    if data['action']=='complete_research':
        if not any(row['selected'] for row in questions):raise RuntimeError('报告缺少实际选题与判断依据')
        if blockers:raise RuntimeError('仍有选中的关键问题未补证据，停止成稿；不自动增加付费请求')
        report=data.get('report')
        if not isinstance(report,str) or not report.strip():raise RuntimeError('研究回复缺少完整报告')
        cited=re.findall(r'\[N:([^\]\s]+)\]',report)
        if any(identifier not in workspace.documents or not workspace.confirmed.get(identifier) for identifier in cited):
            raise RuntimeError('报告引用不存在或未提供正文的证据')
    return result
