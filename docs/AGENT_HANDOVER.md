# Finance Daily 完整交接：接手前必读

更新日期：2026-10-31（北京时间）。本文核对的代码基线为 **`bca040a`**；本文之后的纯文档提交不代表新增运行能力。仓库：<https://github.com/liyanli2025-ops/daily_finance>，分支`master`。

本文是给下一位修改程序的agent的当前入口，兼顾目标、实际逻辑、已做尝试、失败证据和下一步。原[AI_HANDOFF.md](AI_HANDOFF.md)保留为逆序工作日志；其中多处“最新”“尚未部署”是当时的状态，不能通篇视作现在状态。发生冲突时，先看本文的当前状态，再查对应日期记录与实际代码，服务器状态最终以用户最新回传为准。

## 0. 接手90秒摘要

1. **交付目标**：给一位A股/港股日内至数日交易者，每天早6点、收盘后16—18点提供准确、信息充分、敏锐、专业且好听的个人播客，20分钟以内。重要美股、其他外盘、政策、国际事件也要独立研究。不是一个自动摘抄新闻的产品。
2. **用户最大的痛点**：改了许多轮，仍反复漏重要事件、普通财报和重复稿占位，稿件像检查说明书。付费试验失败、上传小包过多已经显著损害信任。不能继续以测试数量、新闻数量或补丁数量回应成品质量。
3. **线上仍处于维护暂停**：最后确认`healthy / database connected / scheduler stopped / automation_paused true`。不得为测试移除暂停标记或恢复早晚自动任务。用户服务器上还有别的项目，不能影响它。
4. **线上最后确认部署v20**，对应2026-10-31正文链路修复包；此后`f24230c`检索目的/执行账本和`bca040a`通用提取尚未部署。GitHub最新代码≠服务器代码≠内容已验收。
5. **核心架构缺口**：主动搜索为主的新流程已经有隔离取材器与导入入口，旧`scheduler`仍调用不带`primary_news`的固定源兼容路径。自动“搜索→补充→分析→口播→音频→发布”没有完整接通和验收。
6. **最近一次真付费取材失败**：4模型POST、6搜索、9正文URL尝试、0可用正文，最后证据校验失败。之后只免费复核旧缓存、修改查询目的和正文读取，没有重新取得一整期合格资料。
7. **刚完成的有效进展**：真实Trafilatura 2.3.1对38份已存HTML回放，新准入30、旧25、旧通过项无回退。新增5项分别涉及正文提取、日期精度和短讯处理；不是所有收益都来自算法。没有验证服务器联网或任意新网页。
8. **下一步**：合并未部署改动与可选依赖，先完成不调用LLM的实际读取/材料质量验收；随后一次预算清楚的新鲜完整资料研究试验，再看报告和口播。不要再跑已失败的旧trial。
9. **没有可信总完成百分比**。工程基础明显改善，但核心成品质量、普适取材、最终音频和持续预测效果没有通过。以第13节的验收阶段报告进度。

## 1. 用户到底要什么

### 1.1 稳定要求

- 主要服务A股、港股短线，但重要美股、海外公司、政策宏观、商品/汇率/利率、信用风险及国际事件要覆盖；没有已证实A/H传导也可保留重要全球事件，不硬套自选股。
- 自选股从App数据库动态读取，用户会随时增删，不固定任何股票或行业。最近线上样本是牧原股份、宁德时代、长江电力、华海诚科，仅为历史样本。
- 全市场主线与重要分歧优先；个股新闻聚焦自选、确有关系的公司、行业重要股票、引发重大舆情或市场影响的公司。非自选公司可以讲，但须解释代表性或影响。
- 信息收集不限于新闻：经营数据、原披露、财报、研报、产业供需/价格/库存/订单、技术面、媒体细节、公开投资者观察都可用。财报主要是背景，更新少，不能挤掉新变化。
- 允许有理论依据的主观研判和前瞻，标清对象、期限、理由、竞争解释、观察与修正条件。不是要求每个观点都有事实一样的确定性，也不是只能说“证据不足，观望”。
- 分析要有资深投资者的鉴别力，但不需扮演或反复自称“20年经验”。要说明什么变化值得关心、如何影响判断、接下来怎么看，而不是堆指标或报新闻。
- 口播自然、有吸引力、重点突出，不能直接念分析报告，不能反复讲“材料没给”“模型如何算”“这里不编”。后台说明留后台；必要的不确定性要让人听懂。
- 长度由信息价值决定，不强求20分钟，也不能为节省token把必要研究压成几篇。研究范围与节目篇幅必须分开。

### 1.2 用户已明确纠正过的方向

**主动搜索为主，固定源为辅。** 用户认可聊天中按完整研究任务主动搜索的结果，认为显著好于旧固定源新闻池。固定源尤其要补媒体正文中的采访/知情人士说法、爆料、据报、基础观察，以及论坛投资者讨论、争议和猜测；不能主要再扫一遍官方政策与普通财报，也不是先列一串财务追问。

具体素材先忠实收集：谁、何时、哪里、什么说法、上下文、给出的依据、回应/反方、核实状态。不要在采集阶段要求每条先有完整投资逻辑才留下；分析阶段再评估可信度和意义。公开说法不等于事实，机构观点不等于事实，多人转述不等于独立证实。

**当期知识工作集，不是永久新闻库。** 用户希望本期AI可查本期资料，而非只看预选几篇；不希望新闻、原PDF、论坛全文无限积累。财报等可按需更新或多次参考，仍保留报告期与发布时点。

**省钱应省重复与失败调用。** 用户不是禁止Claude；必要且范围清楚的真实验证可以提出来。不能以未经解释的硬篇数、盲目裁剪证据代替成本设计，也不能因追求“全离线”永远不验收真实能力。

## 2. 仓库、线上环境与版本事实

| 项目 | 已知情况 |
|---|---|
| 后端 | Python，FastAPI，Pydantic，SQLAlchemy/SQLite，APScheduler |
| 前端 | `mobile/`为Expo/React Native/Expo Router，发布成Web静态产物；`web/`还有Web入口/发布内容 |
| 主要使用方式 | iPhone主屏幕网页图标，不是已确认的原生iOS安装包 |
| 服务器项目根 | `/var/www/finance-daily`，Ubuntu，Python 3.12虚拟环境`backend/venv` |
| 线上数据库/配置 | `backend/data/database.db`、`backend/.env`，均私有，不提交GitHub |
| 服务 | systemd `finance-daily`；最后已切至服务管理并设置开机启动，维护标记保留 |
| 实际监听检查 | 用服务器`127.0.0.1:8000`；曾见配置日志`port=8888`，systemd显式8000可覆盖，不可只凭配置打印判断 |
| Nginx静态目录 | 曾回传`/var/www/finance-daily/mobile/dist`和`/var/www/finance-daily/web`；音频alias指向`backend/data/podcasts/` |
| 最新已确认安装 | `finance-reading-pipeline-20261031-v20.zip`，5文件；备份`/var/backups/finance-daily/20261031T080810944699Z` |
| 最新运行源码提交 | `bca040a`；未部署。上一步`f24230c`也未部署 |
| 最近离线回归 | 805项通过，跳过1项可选真实库测试；隔离依赖目录下另跑10项提取测试均通过。只证明相应程序边界 |

### 2.1 模型和搜索实际情况

- 用户最后运行日志的模型字符串是`anthropic/claude-sonnet-5.5`，Ofox服务，`api.ofox.io`，Anthropic Messages路由。它是用户服务商实际配置/回执，不在本文断言它等于官方同名产品能力或推荐模型。
- 旧`api.ofox.ai`连接失败；`.io`成功。Ofox旧`anthropic/claude-sonnet-4.6`明确410停用。不要改回旧域名/旧模型。
- 曾有402支付/额度错误，用户已充值并强调省钱。历史余额不是当前余额，不要擅自重新查余额或测试模型。
- 旧备用为硅基流动`deepseek-ai/DeepSeek-V3`；旧凭据/端点有401/410。当前不能当可靠自动回退。旧播客代码确有备用DeepSeek与匿名服务/模板降级链；新网关要求显式路由、不静默降级。硅基流动还出现在独立TTS后备逻辑中，不能把它与DeepSeek文字生成混为一谈。
- `analysis/review/extraction/podcast`四类文字任务可分别路由；没设阶段模型时沿用明确主配置。阶段路由存在不等于所有阶段都实际执行或质量通过。
- Tavily负责搜索目录，Claude负责理解与工具选择；**调用Ofox Claude不自动得到网页搜索能力**。聊天环境的搜索工具不能自动拿给服务器使用。
- Tavily线上已配置，真实查询有返回；最后生产`enabled=false`、`configured=true`，隔离试验仅在自身进程临时开启。密钥有效不等于结果相关、正文可读或覆盖充分。
- 当前没有由本地agent直接登录生产服务器的凭据；此前部署与验收由用户在服务器终端执行。不要宣称已代替用户完成线上运行。

## 3. 实际运行逻辑：必须分清三条路径

### 3.1 目前保留的旧自动流程

入口：[main.py](../backend/app/main.py)、[scheduler.py](../backend/app/services/scheduler.py)。

```text
FastAPI启动 → 初始化数据库与SchedulerService
  有backend/data/.automation-paused → 不启动定时器
  无标记 → 启动早/晚报、采样、追踪等定时任务

旧早/晚报方法 → 读取当前App名单/签名
  → NewsCollectorService.collect_all(hours=...)，未传primary_news
  → 固定RSS/媒体/政策/自选/研究/行情雷达和短期缓存等兼容采集
  → 市场候选/跨界材料、时窗/质量过滤
  → AIAnalyzer：组装目录与初读、研究背景、行情和时点
  → complete_with_research：研究与补读 → 报告 → 报告审查
  → PodcastGenerator：编排/口播 → 独立口播核验 → TTS/混音/时长校验
  → 保存App报告、音频地址与状态
```

早报旧方法交易日采24h、非交易日168h；晚报8h加午间缓存。研究/外部工具另有72h等窗口，不是所有入口统一同一个范围。交易日识别仍主要依靠周末和硬编码2024—2026假期，不是已验证的全球交易所日历。

同日同版已有数据库成品可跳过；有生成锁/模型调用预算。分析失败不使用模拟新闻兜底，TTS失败可以留下报告并标播客失败。旧`_generate_mock_*`及模板函数名可能还在，不等于正常生产会调用，不要仅凭名字判断已发布假稿。

**暂停的边界要核实**：main启动不启定时器、模型网关拦请求；但main手动触发端点仍可创建任务，方法可能先执行公开采集再在网关停止。不要将暂停理解成任何入口绝不访问公开网络。新agent应审计所有入口的前置暂停校验，避免修改后用整期触发端点试探。

此外，部分scheduler方法内部捕获异常；接口的`started`、`任务完成`或同步`success`不总能证明报告已保存。验收须查任务结果/诊断/DB成品/音频实际状态。`/health`也不是内容验收，database字段主要根据引擎是否存在；安装器另做数据库验证。

还需审计两个静态代码可见的边界，尚未做线上触发测试：手动重合成若命中已核验脚本可跳过LLM网关，TTS本身是独立网络/可能收费路径；不能假定模型暂停就保护全部语音请求。main手动生成端点未见应用层鉴权，公网是否可达、代理层是否有保护尚未核实，恢复自动化前应明确入口控制。不要为验证风险实际触发付费任务。

### 3.2 新增的主资料导入与增量补充路径

入口：[search_primary_collection.py](../backend/app/services/search_primary_collection.py)、[news_collector.py](../backend/app/services/news_collector.py)。

```text
显式主资料包（实际正文、来源、日期精度、观察时间、检索收据、动态名单）
  → prepare：验证身份/时间/正文范围，保留拒绝理由和缺口
  → collect：核App名单、资料与检索时钟
  → collect_all(primary_news=已准入主资料)
  → 追加公开参与者素材、技术面、分时/样本宽度
  → 不再平行跑旧通用媒体/RSS/政策扫库和历史媒体补回
```

`prepare`不是主动搜索。`collect`也不会自动启用Tavily。资料包是显式契约，不应把AI自己写的一段无出处文字伪装正文导入。导入只验证结构与范围，不验证事实。

当前`LANES`为A股、港股、美股、国际政策、商品、行业、公司事件七个取材方向；研究底稿另有八个area，见第5节。声明覆盖不等于实际覆盖，不能混用两套字段。

### 3.3 模型主导的取材器与隔离收费试验

入口：[primary_discovery.py](../backend/app/services/primary_discovery.py)、[run_primary_collection_once.py](../tools/run_primary_collection_once.py)。

```text
完整共享投资研究需求 + 本期截止 + 实际App名单 + 工具/资源边界
  → 模型选择search(query, lane, purpose, scope)
  → Tavily返回候选目录，非正文
  → 模型选择read(candidate_id)，不是机械读首条
  → 公开读取/精确URL缓存复用，记录实际给出的文字范围
  → read_more补读后部，不重复下载
  → 模型finish：事件、重要性、来源ID、未覆盖方向/股票与舍弃理由
  → 校验引用必须是实际提供过正文的ID，保存待人工验收底稿
```

模型只收资料，不自动分析报告、口播、TTS或写App，也没有接到旧scheduler。默认`discover`遵守生产模型暂停；试验runner有隔离传输/预算控制，不能借此全局解锁模型。

默认准备输入是免费的，`--run`及匹配SHA才尝试执行。现有`model-led-primary-v1`已经执行失败，marker仍在，不能删除或改名伪装新试验。新试验必须基于修复后的流程、新资料、明确目的和新预算。

**尚待接好**：取材器的结果如何转换成主资料契约、传入增量补充、研究报告和正式发布；同一条链共享名单签名、时点、证据与全程费用账本。不要简单把所有阶段串成更多Claude调用，先设计必要阶段与可复用材料。

## 4. 正文、信源与材料状态

### 4.1 搜索与正文是两种能力

[web_research.py](../backend/app/services/web_research.py)中的Tavily搜索默认关闭、basic深度、不自动升级、不自动重试。目录和snippet只用于发现；搜索排序不是主编判断。

新[search_objectives.py](../backend/app/services/search_objectives.py)区分`latest_close / released_policy / company_event / commentary / discovery`。基础收盘/已发布政策的严格检索带完整年份和绝对窗口，排除社交/视频；探索/评论不全局禁讨论。标题提示只是启发式，盘中滚动稿可能后部已有更新，不能按标题全删。实际执行账本指出没搜过的行业/股票，不允许靠声明覆盖。

正文读取顺序：同URL本期/近期可接纳缓存 → 已审阅发布者适配器 → 未匹配页面的可选通用提取。HTTP200也可能是验证壳、导航页、付费预览或空正文。已知发布者的访问限制失败不落到通用提取绕过。

通用HTML读取不支持任意PDF/文档/视频/社交页面；这些需要专用读取。不要把HTML失败直接解释成“全网没有这条新闻”。换独立可访问来源是可能方案，但须在预算内，不能反复撞同失败URL。

### 4.2 刚加入的Trafilatura

[generic_extraction.py](../backend/app/services/generic_extraction.py)只提取已取得HTML的正文候选，不联网、不开账号、不猜发布日期；关闭评论、保留表格，剔除脚本/隐藏节点。不以隐藏JSON正文冒充公开可见内容。

可选依赖：[requirements-extraction.txt](../backend/requirements-extraction.txt)，Trafilatura固定2.3.1，dateutil约束<3。本地只装在任务独立目录，未改全局Python/服务器venv。生产尚未安装，版本/依赖兼容要验证；预检字段`generic_extractor_installed`只检查安装，不保证能运行。缺库诊断是`web_source_generic_extractor_unavailable`。

同38旧HTML回放：34文章候选、3论坛、1研报摘要；旧准入25、新30、0回退，另4文章时间缺失。新增5项有3项正文+日期字段、1项苹果日期格式、1项真实短讯范围处理，不能一概称算法提升。短讯不算完整深度报道；PMI发布/解读不等于两个独立事件。完整说明：[generic_extraction_replay_20261031.md](generic_extraction_replay_20261031.md)。

这批样本原本已成功下载，有选择偏差；并没有保存v19全部9个失败URL的原始响应，不能用本回放证明它们都修好。解析算法仍可能漏段、混页脚、破坏表格对应关系，需实样审阅。

### 4.3 来源能力台账应怎么看

| 来源/类型 | 已做过什么 | 不应推断什么 |
|---|---|---|
| 财联社、见闻、证券时报、上证报、第一财经、21世纪、每经等 | 有列表/公开网页/专用适配；部分本地及历史服务器正文验证 | 不是所有栏目、日期、链接都能读，也不代表每天选择有价值 |
| 澎湃、钛媒体、财经网 | 借鉴RSSHub路由实现发现，抽样原页读正文/日期，保留投稿/转载归属 | 不等于主要只抓RSS，也不等于旧池问题自然解决 |
| 界面、经济观察网、SMM、TrendForce | 非官方产业内容扩展，有公开样本；部分无日期/图片/订阅页不准入 | 同站存在可读与不可读页面；数量不代表产业信息充分 |
| 官方披露/统计/政策 | 财报、公告、经营发布、统计局、央行等可补原依据 | 官方信息不能独占节目；统计口径不能直接推导某公司受益 |
| 美财政部/Fed/EIA、BBC/Guardian等 | 有本地公开正文样本；服务器历史财政部可读，BBC/Guardian曾失败 | 本地网络不等于服务器网络，无窗内新增不等于接口坏 |
| TechCrunch、FastBull/MKTNews等 | 有公开列表或文章样本；MKTNews验证到快讯而非长文 | 项目里有适配器不等于全部上线；快讯/图表/摘要不能混成全文 |
| WSJ/Bloomberg/Reuters/AP/FT/CNBC等 | 部分直连曾401/403/计量预览，保留失败记录；可有其他媒体转述线索 | 不能说已直读原文；转述必须保留上游归属和证据等级 |
| 公众号 | 有有限公开样本/定向发现尝试 | 未实现10万+公众号全量采集，未开付费全量接口；不能靠搜索转载声称全覆盖 |
| 股吧/集思录/淘股吧/TradingView | 公开目录、帖子、可见回复或观点样本；逐条发言ID、账号、时间和位置 | 不等于已核身份、全帖/全站、代表性情绪比例或真实内幕 |
| 雪球/财富号失败样本 | HTTP200验证脚本/无正文，精确路径暂停 | 不绕验证；也不能断言整个网站永久不可用 |

详细证据分见第15节文档。固定源的目录发现仍可查漏，不应只围绕已选主线；但再次下载/送模要有信息增量。现有语义判重、动态行业重要公司发现仍不成熟。

### 4.4 公开参与者素材的局限

[community_sources.py](../backend/app/services/community_sources.py)、`discussion_briefing`按目录/帖子/显示名轮转，主帖和回复分开，引用内容与本人说法尽量分开，支持补读。曾回放64条发言、另扩展目录发现53个不同帖子链接；不是64条新闻、53个读过的帖子，也不是独立用户样本。

轮转可缓解单一帖子/账号集中，不能证明后续发言更有价值。需要人工来源评价、不同论据与可核实细节，而非追求论坛条数。身份未知不叫业内人士，点赞/重复转述不当证实；市场未定价、报道少都不能从样本少直接推出。

### 4.5 失败路径不要复活

先读[known_unavailable_sources.md](known_unavailable_sources.md)和[backend/public_source_failures.json](../backend/public_source_failures.json)，再查`source_health.py`、源级`blocked/`台账。

用户明确：已测失效API不反复试。失败区分精确URL、适配器、网络、时效、权限、预算，不因单篇失败封整站；也不能改几个参数绕开负结果台账重复请求。新的地址/解析/权限变更有证据时才安排有界复验。源失败记录不能随24h材料清理消失。

## 5. 研究、证据与编辑流程

主要代码：[ai_analyzer.py](../backend/app/services/ai_analyzer.py)、[episode_research.py](../backend/app/services/episode_research.py)、[research_desk.py](../backend/app/services/research_desk.py)。

研究area为`a_market,hk_market,global,macro_policy,industries,major_company_risk,watchlist,price_structure`。底稿记录覆盖、动态自选检查、问题、重要性、机制、竞争解释、支持/反方ID、观察条件和舍弃理由。它是工作记录，不能当作“八方面研究都成功”的标签。

`complete_with_research`当前最多3次分析回复：初始+最多2轮取材；最后一轮必须成稿或留下未完成，不再追加工具。已有工具包括本期池搜索/分段读取/批量读取、两个媒体定向搜索、显式启用的通用搜索、公开URL和讨论补查等。`search_public`不是全网搜索。

旧固定28篇上限已取消，改完整候选目录+字符预算初读+可补读。当前默认新闻输入预算34000字符，含目录、说明与阅读块。目录可能占很大比例；曾305目录占16867字符，使初读只有8份。**8不是新篇数上限，但实际正文覆盖确实变少**，不能用“理论可补读”掩盖模型没有补读。

目录C编号只能用于发现；读后取得真实证据ID再引用。`EpisodeWorkspace`区分prepared文字范围、工具返回范围、模型完成回复确认范围和引用。prepared不等于读过全文；模型收到文字不等于注意到或核实。当前检索主要是词项/中文二元组，不是成熟语义RAG。

同ID/URL/标题等确定性判重及研究问题分组可以减少重复入口，但不可靠等同于跨媒体同事件语义去重。相同公司不同事项不能全删；原公告与媒体转述可能重复，也可能互补。要按新增事实、时点、条款、独立采访、回应与反方比较。

报告审查仍是独立模型任务。`report_auto_repair_enabled=false`只关闭自动整篇修稿，**没有关闭首次报告审查，也没有关闭生产口播核验**。验证失败保存原回复/检查点，不修补截断JSON后当完整成品发布，不自动降低证据要求换成过关。

在本次核对的tracked文件中未发现独立`SKILL.md`财经分析包。实际分析依赖代码内协议/提示词、可重复计算和模型推理；不能向用户承诺“某成熟skill保证专业准确”。外部项目skill只是参考，需看其真实实现和验收。

## 6. 技术面、模型与预测：实现和缺口

- [technical_analysis.py](../backend/app/services/technical_analysis.py)：已完成日线的均线、Wilder类RSI/ATR/DMI/ADX、MACD、布林带、波动、VWMA、量价与带确认日的摆动结构等；预热不足不造值。相关指标按家族理解，不能当多票独立证据。
- `technical_radar / timed_market / stock_service`：验证日期、OHLC、复权/单位和来源。实时裸报价、已完成复权日线不可直接拼成同口径收益；盘中未完成K线不能假装收盘。
- `weekly_context`：周级参考，不是已验收的全球独立周历；本周未结束不能当完整周线。
- `intraday_context / microstructure`：分时点观测与尾点确认，个股同标的相邻区间相对量速。未核指数量基准则不计算，不以跨股票不同量单位比大小。仍非完整多日分钟OHLC。
- `market_breadth`：新浪hs_a目录+腾讯逐股带日期报价，沪深京样本宽度；2026-10-28 11:56线上例5575报价、5569可比、跨度59秒。不是交易所独立全集或同瞬间快照；港股宽度仍缺。午休时钟不齐保留not_aligned。
- `relative_strength`：同市场基准的相对收益、相邻5期变化、有限ETF代理样本排名。ETF代理不是全行业排名或资金流。
- [market_model.py](../backend/app/services/market_model.py)：单因素OLS，`r_stock=alpha+beta*r_market+residual`；120期估计+20期时间顺序留出+5近期，至少146个对齐收盘。与“个股等于指数”的朴素基线比留出RMSE。它是成熟市场模型的有限诊断实现，不是经验证的预测策略。
- 5期残差算术合计单位是**百分点**，不是复利收益、赚钱或独立超额回报；高样本内R²不等于胜率；留出误差稍小不保证未来；没有公司事件绑定就不说发现了未定价利好。模型和技术面共享价格，不叫双重独立验证。
- `backtest_service / signal_tracker / lessons_memory_service`保留旧复盘能力，未完成本轮新研究判断的连续前瞻验收。不能用旧信号胜率或合成边界样本为当前分析背书。
- 自动报价型自选评级被跳过，不再凭价格默认写“中性、置信度0%”。前端无预测要表示资料/分析状态，不把缺值包装成判断。

仍需推进：港股宽度、独立交易日历、多日分钟线、动态公司—行业代理关系、数据充分性与漂移检查、判断日志与后续条件评估。缠论/威科夫/波浪等未被可靠接入，不能靠流派名称或模型看图文字冒充已实现。

## 7. 口播与音频：已经改过什么，还卡在哪里

正式要求见[original_spoken_requirements_20261030.md](original_spoken_requirements_20261030.md)，实际提示词在[spoken_editing.py](../backend/app/services/spoken_editing.py)，编排协议在[spoken_programme.py](../backend/app/services/spoken_programme.py)。旧版生成方式曾回溯，保留自然单人财经分析的目标，不恢复天气寒暄、无依据仓位或模板兜底。

当前生产流程：完整报告正文/摘要/观点 → 一次模型交`programme`与`script` → 编排原句锚点/格式/后台口吻检查 → 独立口播忠实度模型核验 → 缓存已核验脚本 → Edge TTS优先及可能的硅基流动TTS后备 → ffmpeg/pydub混音与实际音频解码/20min时长校验。

编排说明不朗读，`[SECTION_BREAK]`用于分段停顿。清洗不应删反证、归属、条件或改变数字。重合成时可复用与报告/昵称/策略等匹配的已核验脚本，避免再次写稿收费。旧fallback函数虽保留，当前AI脚本/核验失败时停止，不发布未核模板。

**仍有硬限制要评估**：当前编排choices 1—3项、脚本<=4000字符，写稿max_output_tokens=8000，独立口播核验4000。用户只明确20分钟以内，没有要求每期3主题或4000字。曾说明这些限制，但没有完成必要的重新设计与新资料听感验收。不要声称已取消，也不要简单把上限拉大就算改好。

真实试验曾改善开场与主线，但还存在重复总结、数值密集、解释模型、强调不能推断过多、条件空泛、编辑说明溜入口播。历史单主题人工修正报告写得顺，不等于自主全市场分析合格。多次只验文字没有实际音频，**整期听感、发音、节奏、音色与长度尚未通过**。

## 8. 本期工作集、缓存和文件

| 路径（相对backend） | 内容与边界 |
|---|---|
| `data/database.db` | App主库：名单、报告等；私有，不替换不上传 |
| `data/.automation-paused` | 生产维护暂停标记；不删除 |
| `data/episodes/episode-*` | 当期材料、元数据、检索/读取范围、回执；成功清工作副本、失败有限恢复期 |
| `data/radar/`、`cache/` | 新闻/技术/分时快照、selection-replay、搜索取材检查；有TTL，不是永久真实库 |
| `data/research/` | 业务画像、披露/研报等短期研究材料；保留原日期/报告期，非全部当催化 |
| `data/diagnostics/` | 私有初稿/审查/修稿/口播检查点、用量、trial开始标记；部分正文诊断24h可清理 |
| `data/reports/`、`data/podcasts/` | 成品；与临时正文分开，不能被材料清理扫掉 |
| 源缓存的`blocked/`与失败JSON | 持久负结果，不随正文TTL复活 |
| `/var/backups/finance-daily/` | 私有部署前备份；新agent应核实回滚内容，不盲目整目录覆盖 |

`material_lifecycle`只清本项目拥有的临时目录/特定文件，检查路径与符号链接；不要扩大为整个data递归清空。资料TTL为24h不意味着财报只能看24h以内，也不保证暂停状态有后台清理任务一直运行，清理依赖实际触发入口。

缓存复用须标明原观察时间和远端版本未重新核对。重新导出旧资料不能刷新原检索时钟；更不能把缓存标题/摘要升级为正文。短讯、研究摘要、RSS文字、公开声明、visible_body/full_text是不同范围，标签也不能保证内容真的完整。

资料与失败检查点可能过期，换机器clone不会拥有本机outputs或线上data。不要因找不到文件就推断任务没跑；先核文件/marker/进程和日志是否覆盖，再决定如何导出。需要导出时不带.env、数据库全量、密钥或账户凭证，也不公开提交第三方全文。

## 9. 费用、停止条件与并发

| 范围 | 当前机制 | 必须留意 |
|---|---|---|
| 正式单期模型 | `model_max_calls_per_report=8`默认；scheduler由`budgeted_generation`包裹，包含该上下文内模型尝试 | 请求数不是美元上限，独立入口需核共享预算 |
| 默认重试 | `model_http_retries=0`；用户线上已验证 | 直接调用内部函数/自写transport可能绕开上下文预算，必须显式限额 |
| 自动整篇修稿 | `report_auto_repair_enabled=false` | 首次报告审查、口播核验仍可能收费；不能说已全关Claude检查 |
| 网关输入 | 当前单请求10万字符保护，检查实际messages | 字符不等于token/美元，输出/思考/缓存计费另核 |
| 新闻初读 | 默认34000字符含目录与说明 | 不应用来暗改研究覆盖；补读工具与完整池要真的有效使用 |
| 通用搜索 | 默认关闭，配置默认每期4请求，basic | Tavily独立计费；有返回不代表正文或研究价值 |
| `discover`普通默认 | 6模型、4搜索、12正文URL、48000输入字符/3000输出token、240s | 是内部默认，不同于下一行试验预算 |
| 已失败v19隔离试验 | 最多4模型POST、8 basic搜索、10正文URL、30公开GET（含跳转）、每模型80k字符/3000输出、零重试 | 实际4/6/9/0正文；已经消耗过，marker保留 |
| 公开正文/论坛 | 同URL复用、失败台账、时限、字节/主机保护 | 公共GET无模型费，但仍有时间/请求成本，不可无界扫描 |

网关记录模型、任务、HTTP状态、输入/输出/缓存token、耗时，不输出密钥或服务商错误正文。未知用量保留null；token账本不是最终账单。任何金额上限若只计算输出token必须标明不含输入，不能向用户承诺总价。

新取材器在连续3次没有得到正文后停止后续模型，最后轮不再执行没有后续模型处理的工具。保护已写代码，不代表失败路径在服务器新资料上验证过。不要放宽证据ID校验来让`finish`通过。

暂停时不做常规模型请求；需要真实验证先给范围、上限、复用内容和产物，再执行一次。不要对每个小改动都做整期4次Claude；也不要无视用户已有明确授权重复问同一许可。当前用户此次授权是**整理文档与推送**，不含新的模型/搜索试验或恢复生产。

## 10. 关键尝试与踩坑记录

| 阶段/尝试 | 观察与问题 | 已改/经验与剩余边界 |
|---|---|---|
| 10月23日服务排障 | systemd failed，但8000由手工root shell子进程占着；健康不代表systemd接管 | 已切到服务管理。以后先查PID、cwd、cgroup，勿盲kill端口上任意Python |
| 旧模型/网络 | .ai连不上，.io可用；旧Sonnet4.6停用、备用401/410、余额402 | 显式路由、错误分类；不猜模型、不反复试旧接口、不静默降级 |
| v2/v3审查 | 截断输出、情绪bearish枚举问题、审查失败；曾自动修稿重复费用 | 正常停止原因、枚举/审查处理、检查点改进；不补截断JSON当成真完整结果 |
| 早期优先加质量闸 | 反复拦错报告，却未先解决有效资料，用户多次指出 | 安全闸保留，但当前优先取材与成品；不能只增加拦截而没有可用输出 |
| 自选只有融资自动稿 | 三公司各一融资快讯和一公告，缺实质公司/行业信息 | 扩媒体/原披露/行业/研究；融资买入额不是净买入，自动稿不自动有短线价值 |
| 财报研报扩充 | 半年前研报、宽泛业务词误配汽车/电价，旧材料当催化 | 新旧分层、业务语境和来源关系；旧研报可作背景但不能充当当天新增 |
| 巨PDF读取 | 一份196页可读，11.9秒；不证明该PDF都是本期必要信息 | 保留页码/节选范围，按需阅读；页数和全文提取成功不等于分析专业 |
| 扩六国内+海外源 | 有111/114正文等历史结果，海外本地与服务器不一致 | 来源成功是底座，不能用数量掩盖选题偏差；官方源过重是用户明确不满 |
| 新闻249与28初选 | 新167+历史105=272，去重23后249；不是去掉249条；28是初读 | 要讲清各阶段分母。去重前149全文标签不等于249完整独立全文 |
| 初选28混软稿 | 养老/培训/沙龙、普通财报、同篇多次占位；水电费误联水电 | 窄规则修正、主体/问题分组。关键词只能缓解明确错误，不能替代主编判断 |
| 10月28日文字验收 | 修稿复核仍6分；输入累计687061 token；finance155872字符、market40910 | 重复上下文和审查成本很高；增加输入预检/读取范围/缓存，停自动修稿，不把省字当覆盖目标 |
| 断连与日志覆盖 | 前台任务随会话消失；重复nohup用`>`覆盖旧失败日志 | 后台持久运行、结果/marker核状态。日志不更新不等于结束，running状态也可能已无进程 |
| 审查误报/真错混合 | 昨收与盘中涨幅口径被误报；“反弹前”时点真错；跌很多不能识别驱动 | 原句/事实锚点、局部编辑。审查分数不是判决；主观倾向可保留，驱动不明不能硬推原因 |
| OLS局部试验 | 模型能指出残差、胜率、基线混淆；口播却像教模型 | 保留诊断、后台解释与听众稿分离；合成样本不是真公司，不用R²当胜率 |
| 人工修正版口播 | 多次局部样稿更顺，但都用同一旧报告、甚至人工修正内容 | 只能证明部分表达迁移；下一轮必须新资料，不能继续针对旧案例调到好看 |
| 10月30日新资料 | 285/308候选，28初选仍漏A/H收评/重要海外，普通个股新闻很多 | 原池问题与选材问题并存，改统一市场入口。不能全归因于没源或全归因于排序 |
| 取消28→目录+8 | 完整目录305条，但初读8，牧原重复占位，未读标题参与论证，模型一次成稿未补读 | 取消篇数不等于覆盖改善。目录不替代正文，补读协议必须实测；不能将用户关心的重要事件挤成标题 |
| 聊天主动搜索样本 | 用户认可，明显比服务器固定池强；样本有20阅读项、后续29文档且重叠 | 无同预算同查询逐HTTP对照，不能证明Tavily天生差或29条全新。要比较执行与实际资料，不凭界面感受换产品 |
| 外部项目研究 | 学daily-news、Open News、NewsNow、Fundus、TrendRadar、open-aggregator等 | 借鉴分层发现、时间/主体验证、正文提取、事件组织。sources.yaml/skill提示不是现成全部可用API |
| 公开参与者素材 | 集思录等少数发言有价值，但过度集中 | 增目录/帖子/发言轮转与逐条补读；未证明代表性、身份或预测价值 |
| Tavily最初抽查 | A股返回旧稿、港股指数介绍页、美股台湾收评、牧原返回山东药玻；4正文全失败 | 任务词机械、读首条、query无主体与用途校验。不是模型不能搜索，是研究与读取链路未接好 |
| v19模型主导真试验 | 4模型/6搜索/9读/0正文；最后ValueError | 原码`discovery_unprovided_evidence`；免费重判为`discovery_body_claim_without_evidence`，可能是覆盖或事件空依据，不能没看原回复就说伪造ID |
| v20免费复核 | 财联社A/H、见闻3条各返回1800字符；全是cached_only | 修同URL缓存复用有用，但不是3篇新抓或读完全文；eligible_untried=11也不等于11条新未读 |
| 后续检索目的修复 | 17候选仅3缓存；社交/盘前/会前预测/商品PDF混杂；没搜行业和四股 | 区分purpose、时间参数与执行账本，未部署未付费重跑，不能说覆盖已解决 |
| 通用提取本轮 | 38旧HTML 25→30，0回退，4文章缺时间、4专用类型不升级 | 正文提取与准入分开；缺时区保留日精度，跨窗口待核。尚未服务器验证 |
| 多次部署冲突 | reviewed baseline与服务器文件不符；git diff有时为空、git版本本来不同 | 不能盲跳校验、直接git pull/reset、凭一个哈希就认定安全。审阅实际文件/基线后才增兼容版本 |
| iPhone新旧界面不一致 | Safari新页面、主屏图标仍旧，含中性0%旧UI | 静态发布目录、浏览器/主屏缓存与产物版本都要核；只更新TS源码或后端不会更新用户界面 |

## 11. 当前问题分级与真正难点

### P0：决定能不能交付

1. **研究执行质量与覆盖**：完整需求如何变成合理搜索，识别最新交易日、原披露/已发布政策、重要海外与动态公司关系；搜索不足要真实留缺口。关键词规则不可靠承担最终重要性判断。
2. **可读正文与时间证据**：服务商目录成功不意味着原站可达；不同网络、动态渲染、权限、元数据、短讯/PDF/论坛都影响准入。通用提取减少逐站修补，但仍需新样本验收。
3. **新路径没有端到端接生产**：目前容易用隔离取材结果误称播客流程上线，或一解除暂停又跑旧固定采集。需要一个可跟踪、可停止、名单/时点/预算一致的状态链；手动入口、脚本缓存命中的TTS及代理鉴权也需纳入暂停与费用边界审计。
4. **内容质量未过**：即使材料充分，专业分析、主观倾向、机制/反证、具体观察条件和自然口播仍要检验。格式JSON、审查得分、805测试不能解决这一点。
5. **成本不透明与重复**：整段证据反复进写作/审查、默认生产口播复核、失败重试/独立脚本绕预算，都会继续烧钱。要有可核实际用量与可恢复阶段，而非提高上限。

### P1：穿插处理，不应替代P0

事件级增量/晨晚复用、动态重要公司关联、更多独立产业/参与者来源、技术缺口、预测条件的前瞻记录、音频听感与iPhone缓存、生产任务状态可靠性。

### 不应许诺轻易解决的部分

全网穷尽、稳定读付费媒体、低样本论坛代表性、识别真正“市场未定价”、高预测胜率和个股涨跌因果。这些不能靠再加一段提示词保证；可以做有范围、有证据、可回看的有限产品。

## 12. 下一位agent应该按这个顺序推进

### A. 先统一基线，不新增付费

1. 读本文，检查Git HEAD/工作区；保留用户已有变更。
2. 以最后v20安装事实为基线，核对`f24230c`和`bca040a`未部署差异、依赖、调用方/打包清单。检查新模块有没有漏包。
3. 读失败台账和旧试验结果，确认哪些响应有本地快照、哪些根本没有，避免又重试旧URL。
4. 汇总成一个审阅明确的变更/安装/验收方案，不再一两文件就让用户上传。依赖安装先核兼容，不污染其他项目，不要求用户把密钥发聊天。

### B. 验收实际资料入口，先不调用LLM

- 使用新输入和当前名单，公开访问或已授权搜索有明确限额；完整保留查询、候选、来源、失败原因、实际读到的段落/日期/类型。
- 同一个问题对照候选质量、正文覆盖和时点；区分本地与服务器。观察此前漏的美股收盘、已发布政策、A/H市场主线、重要公司/行业，不只复测两个已成功源。
- 先确认通用提取可用、关键正文能读，再启动模型。新URL是否能读要实证；旧失败URL无变更依据不重复碰。
- 产物给人看得懂：值得展开的事件、为何重要、实际文字和来源、反方、遗漏。普通财报/软文/同题重复是否占位要人工审。

### C. 一次有界、新鲜的完整研究试验

- 用户明确要求验证普适性：用新完整采集，不能再拿人工修正旧报告当上游分析验收。
- 预先说明阶段、最多模型/搜索请求、输入/输出保护、无自动重试/整篇修稿、是否写App/TTS。不要直接复用旧4次失败预算。
- 用实际执行账本与已读范围判断重要缺口。已承认关键选题待补证据则补读/保留未完成，不能拿标题顶替；不要求每个方向凑篇数。
- 对最终报告人工评估：事实/单位/时点、主线重要性、推理深度、倾向与反证、短线条件。先修实质错误，再进入口播。

### D. 一期真正的播客交付

将合格报告编排成自然口播，复核后台说明、冗长防御语句、数字负担、主线推进与具体观察；评估4000字符/3选题限制是否适合需求。再有限合成音频，实际听、核时长/发音/停顿/混音及iPhone播放。用户验收后才讨论恢复调度，并连续几期记录判断及条件结果。

## 13. 里程碑验收方式（替代虚假百分比）

| 阶段 | 过关证据 | 当前状态 |
|---|---|---|
| 服务与保护 | 项目专属服务、备份、数据库、暂停、无重复调用 | 已有线上证据；新变更上线仍要复核 |
| 新取材读取底座 | 新鲜服务器资料、关键方向候选/正文/时点可查，费用在界内 | 未通过；最近仅旧HTML/缓存回放 |
| 内容覆盖与选题 | 全市场/外盘/行业/动态自选的有意义问题、合理舍弃、关键缺口处置 | 未通过；旧池与新目录均发现明显问题 |
| 自主报告 | 非人工修正输入，事实与推理人工验收，可检验判断 | 未通过；局部改善不代表整期通过 |
| 自然口播 | 与合格报告一致、主线推进、信息密度和听感好 | 有局部样稿，未完整通过 |
| 真音频与App | 实际音频<=20min、可听、可播、版本一致 | 新链未通过 |
| 连续运行与效果 | 多期新资料、费用稳定、漏项/真错复盘、预测期限和失效条件跟踪 | 未通过，自动化继续暂停 |

“健康”“模型HTTP200”“有全文标签”“审查通过”“完成805测试”分别只证明那一层，不能互相替代。

## 14. 运维、免费排查与安装交接

### 14.1 安全的服务器检查示例

以下只在用户Ubuntu服务器终端运行，**不是本机浏览器地址**；不要连同提示符/日志一起复制。

```bash
curl -fsS --max-time 10 -w '\n' http://127.0.0.1:8000/health
sudo systemctl status finance-daily --no-pager
sudo journalctl -u finance-daily --since '15 minutes ago' --no-pager -o cat -n 120
```

当前预期暂停健康状态，不应把scheduler stopped修成running。若怀疑进程冲突，先查进程命令、cwd、cgroup并确认所属项目再操作，不给全局kill或重启整台机的建议。

已部署版本含默认免费能力预览：

```bash
cd /var/www/finance-daily/backend
sudo ./venv/bin/python -u -m app.primary_collection_check
```

它只展示配置/名单/计划，不代表执行搜索。`app.selection_check`、`app.research_input_check`等用于缓存回放，要核模块当前版本与数据TTL；没有快照不等于没有新闻。不要看到`--run-public`便当绝对免费：不同工具可能含Tavily或公开请求，先读入口和预算。

后台运行要用持久任务和独立日志，先确认marker/进程，避免重复收费。`pgrep`没输出可说明指定进程不在，但最终状态仍需读结果；`status=running`可能是异常退出未更新。不要用同一个`>`路径覆盖唯一旧错误日志；需要保留完整traceback与阶段回执。

### 14.2 打包与前端

工具：`build_paused_upgrade / build_model_led_release / build_reading_repair`等，以及[install_paused_upgrade.py](../tools/install_paused_upgrade.py)。

安装器默认只读验证、SHA manifest限制范围、应用前私有备份、保持.env/数据库和维护暂停。`--apply --restart`才修改指定项目源文件并重启财经服务。`Source validation passed`不是已应用，`Service healthy`也不是采集/报告/音频验收。

遇到`Server file differs from reviewed baseline`，先读具体文件和版本差异；git diff空仅表示相对当前仓库HEAD无改动，不证明等于安装器审阅基线。不要随意删manifest条目、放开所有哈希或直接reset。旧测试文件漂移与运行文件漂移要分别审阅。

线上长期用ZIP增量更新，服务器git HEAD不一定代表真实文件版本。旧包不可同名重建。历史不可变文件：

| 包 | SHA256 |
|---|---|
| v18 search-primary | `7f509ba026ac0f3923140a32b8276ebf691263cf67543996130db2bdc7069a50` |
| v19 model-led | `2c17a1768c7fefd33f5782a63c566a97573262b6ec3e34b8337228cf9ea26e25` |
| v20 reading-pipeline | `133dd38ec86f85377ec5c396c93bc4fc2a380b22a1c59dabc56230913aba7804` |

源码包不会自动编译/发布前端，也不会自动安装新可选提取依赖。前端需独立构建、检查产物、更新实际Nginx目录；保护其他项目，不凭前端未刷新改后端数据。主屏图标可能有旧缓存，和Safari分别核对。不要为刷新缓存让用户随便清数据库或删整个站点数据。

### 14.3 本地开发回归

此前Windows工作目录是任务下`work/daily_finance`，本地私有证据在同任务`outputs/`。其他agent不一定有该路径。项目数据/环境密钥没有随Git仓库提供。

普通后端回归示例（在`backend`目录）：

```bash
python -I -X utf8 -u -c "import sys,unittest;sys.path.insert(0,'.');r=unittest.TextTestRunner().run(unittest.defaultTestLoader.discover('tests'));sys.exit(not r.wasSuccessful())"
```

Windows沙箱曾使asyncio本地回环/临时文件测试挂起，提升权限后离线回归可完成；先区分沙箱限制与真实死锁，不随意删测试。常规环境缺Trafilatura时跳过真实库用例，不能据此说库已安装验收。无需为本次纯文档交接重复付费或跑全套模型。

## 15. 代码导航、证据文档和交接物

### 15.1 按要改的环节定位

| 环节 | 主要文件/目录 |
|---|---|
| 启动、配置、API | `backend/app/main.py`、`config.py`、`routers/{stocks,reports,podcasts}.py` |
| 定时生成/旧兼容流程 | `services/scheduler.py`、`news_collector.py`、`radar_sampler.py` |
| 主动取材/导入 | `primary_discovery.py`、`search_primary_collection.py`、`research_desk.py` |
| 搜索目的与公开正文 | `search_objectives.py`、`web_research.py`、`generic_extraction.py` |
| 固定媒体/官方/海外 | `public_news_sources.py`、`domestic_discovery.py`、`media_sources.py`、`overseas_sources.py`、`policy_sources.py`、`primary_sources.py` |
| 讨论 | `community_sources.py`、`discussion_briefing.py`、`discussion_contributions.py` |
| 动态名单与准备 | `watchlist_repository.py`、`watchlist_preparation.py`、`watchlist_sources.py`、`company_news_scope.py` |
| 研究材料/PDF/画像 | `research_hub.py`、`research_documents.py`、`research_relevance.py`、`research_reading.py` |
| 排序/去重/初读 | `news_assignment.py`、`news_selection.py`、`news_workspace_brief.py`、`news_quality.py`、`material_identity.py` |
| 工作集与引用 | `episode_workspace.py`、`episode_research.py`、`evidence*.py`、`prompt_reading.py` |
| 行情/技术 | `technical_analysis.py`、`technical_radar.py`、`relative_strength.py`、`market_model.py`、`microstructure.py`、`market_breadth.py` |
| 写作/审查 | `ai_analyzer.py`、`editorial_policy.py`、`analysis_grounding.py`、`review_feedback.py`、`prior_report_context.py` |
| 口播/音频 | `spoken_editing.py`、`spoken_programme.py`、`spoken_fidelity.py`、`podcast_generator.py`、`podcast_script_cache.py`、`audio_mixer.py` |
| 费用/状态/失败 | `model_gateway.py`、`model_usage.py`、`report_diagnostics.py`、`source_health.py`、`material_lifecycle.py` |
| 前端与发布 | `mobile/app/`、`mobile/services/`、`mobile/stores/`、`mobile/dist/`、`web/`、`tools/build_frontend_upgrade.py` |

表内services均指`backend/app/services/`。不要直接把该目录的模块函数当无副作用免费工具执行，先读入口。

### 15.2 优先读的专题记录

- 当前读取：[generic_extraction_replay_20261031.md](generic_extraction_replay_20261031.md)、[reading_pipeline_repair_20261031.md](reading_pipeline_repair_20261031.md)、[search_objectives_20261031.md](search_objectives_20261031.md)。
- 资料对照与选择：[same_day_collection_audit_20261031.md](same_day_collection_audit_20261031.md)、[whole_pool_discovery_20261030.md](whole_pool_discovery_20261030.md)、[market_pool_audit_20261030.md](market_pool_audit_20261030.md)。
- 主辅与研究：[research_desk_upgrade_20261031.md](research_desk_upgrade_20261031.md)、[search_primary_supplement_20261031.md](search_primary_supplement_20261031.md)、[model_led_collection_20261031.md](model_led_collection_20261031.md)、[search_primary_joint_check_20261031.md](search_primary_joint_check_20261031.md)。
- 来源与外部项目：[source_reference_review_20261031.md](source_reference_review_20261031.md)、[news_collection_methods_20261031.md](news_collection_methods_20261031.md)、[domestic_sources_provenance_20261031.md](domestic_sources_provenance_20261031.md)、[participant_sources_20261031.md](participant_sources_20261031.md)、[discussion_discovery_20261031.md](discussion_discovery_20261031.md)、[known_unavailable_sources.md](known_unavailable_sources.md)。
- 分析真错/误报：[editorial_acceptance_20261028.md](editorial_acceptance_20261028.md)、[real_report_edit_20261028.md](real_report_edit_20261028.md)、[market_model_probe_result_20261029.md](market_model_probe_result_20261029.md)、[input_budget_progress.md](input_budget_progress.md)。
- 原版要求与口播：[original_editorial_basis_20261029.md](original_editorial_basis_20261029.md)、[original_spoken_requirements_20261030.md](original_spoken_requirements_20261030.md)、[listener_spoken_v2_result_20261030.md](listener_spoken_v2_result_20261030.md)、[spoken_integrity_progress.md](spoken_integrity_progress.md)。
- 动态名单/技术：[watchlist_preparation_progress.md](watchlist_preparation_progress.md)、[microstructure_progress.md](microstructure_progress.md)、[relative_strength_progress.md](relative_strength_progress.md)。
- 旧阶段总览：[repair_roadmap.md](repair_roadmap.md)、[AI_HANDOFF.md](AI_HANDOFF.md)。旧日期的“未验收”可能已被下一节覆盖，追溯时按时间读。

### 15.3 历史外部参考的取舍

用户提过ChainKnowledgeGraph和IMA腾讯财经研报库：产业图谱适合提供有来源、需更新的关系候选，不适合直接当当日事实或收益映射。IMA公开页面/Agent接口存在不代表用户已加入、获得该具体共享库权限或可以直接批量读取；用户已明确不会配置，只让参考思路。没有把共享库当可用生产源，不应再要求用户为了当前任务注册/购买不必要服务。

学习过daily-news、Open News、NewsNow、Fundus、xnews、TrendRadar、open-aggregator；阅读文件、具体可借鉴点与拒绝照搬之处在来源专题文档中。没有整套移植这些项目；其中一些是skill/网址目录而非完整采集器。直接源仍要本项目网络和内容验收。Trafilatura是最近实际接入的通用提取依赖。

### 15.4 GitHub之外的私有证据位置

若继续使用同一工作机，任务outputs中可能有：`finance-fresh-review-v14.zip`相关展开材料、`finance-material-review-20261029`、`finance-research-review-20261029`、`primary-joint-review-20261031/primary.input.json`、`research-round-20261031/`、`primary-updates-20261031/`、`generic-extraction-final-replay.json`和离线测试日志。文件可能已清理，不假定全部存在。

线上关键失败结果曾在：

```text
backend/data/radar/cache/model-led-primary-v1.result.json
backend/data/diagnostics/model-led-primary-v1.started
backend/data/radar/cache/saved-body-check-v1.result.json
backend/data/diagnostics/saved-body-check-v1.started
backend/data/episodes/episode-3dd2qyno
```

最后旧取材截止为2026-10-31 15:36:17.610077。17候选中仅S1财联社A股2130字符、S3见闻3425字符、S8财联社港股3309字符有匹配缓存，其他无匹配缓存不等于全网没消息。3条返回1800字符片段，不等于全读全文。原聊天20阅读项、后来29文档重叠，不能相加；10人工检索说明不是逐HTTP日志。

若新agent没有这些私有材料，先沿用本交接的已知结论并核用户服务器可导出的安全诊断，不通过反复收费重建旧试验。GitHub提交代码与说明，不提交密钥、生产数据库、完整第三方文章或讨论串。

## 16. 接手后的交付沟通约定

每次汇报分别说：改了什么、用什么证据检验、用户实际能获得什么、还有哪层没验收、是否产生费用/部署变更。内容问题用内容证明，程序保护用程序证明。明确承认旧方案失效的地方，不能把用户的批评变成再加一个正则就算解决。

完成能独立处理的合并工作后，再给用户具体的一次安装与验收步骤；命令需匹配实际已上传文件和模块。不要让用户反复追问“然后呢、怎么装、怎么验证”，也不要给尚未上传的包路径、过期SHA或已执行trial的重跑命令。

当前接手起点是：**暂停线上自动化，保留旧付费证据；正文底座和取材约束已有改进但未部署；下一阶段用新鲜实际资料证明覆盖和价值，再完成自主报告及真正音频。**
