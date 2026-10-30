# 新闻采集项目研读和公开入口测试

本轮目标是扩展重要事件的发现与正文能力，减少无关个股财报占位。不是再增加一批来源名称，也不把采集成功等同于报道真实或投资价值。所有实际测试均未调用LLM、TTS或付费搜索；生产调度仍暂停。本地Windows网络结果不等于腾讯云服务器结果。

## 研读结果

| 项目和已检查文件 | 可借鉴 | 不应直接搬入 |
|---|---|---|
| [daily-news sources.yaml](https://github.com/2learnsomething/daily-news/blob/master/sources.yaml)、skills/daily-news-ashare/SKILL.md和scripts目录 | 快讯、综合、深度、官方、研报、国际来源分层；明确早晚资料衔接 | sources.yaml多数是网站首页和策略描述，不是实现好的29个采集器；所读skill自己标记旧版。未经复核的回测胜率、资金规则不能当我们的分析依据 |
| [Open News googlenews_engine.py](https://github.com/alphap365/open-news/blob/main/open_news/feeds/googlenews_engine.py)、sources.py、duckduckgo_engine.py、core/strategies.py | 日期/地区受控的主题搜索；聚合链接到原媒体的解析；结构化字段与正文提取分离 | 默认多级回退、DDG HTML部分三次重试；description前500字符不是正文；dateModified不能代替首次发布时间；站点域名包含匹配不能替代严格host验证 |
| [NewsNow mktnews.ts](https://github.com/newsnext/newsnow/blob/main/server/sources/mktnews.ts)、fastbull.ts、jin10.ts | 直接公开入口、来源时间、重要标记；发现、快讯、文章流分开 | 列表的标题/hover不能算已读文章全文。金十旧失效路由保持不探测，本轮未请求jin10 |
| [Fundus US来源定义](https://github.com/flairNLP/fundus/blob/master/src/fundus/publishers/us/__init__.py)、techcrunch.py、rest_of_world.py、CN定义 | sitemap/RSS负责发现，出版社专用选择器负责正文与日期；TechCrunch版本化选择器 | Reuters/CNBC有适配器不证明我们的网络可访问；不重探已有失败路径。CN定义主要是人民日报入口，不能直接解决中国财经深度来源不足 |
| [xnews fixedfeeds.urls.ts](https://github.com/underloam/xnews/blob/main/src/sources/fixedfeeds.urls.ts)和src目录 | 来源注册、按公司/主题查询、来源轮询间隔 | 固定财经RSS多数是摘要/线索，不能因列有WSJ等就声称其全文可用 |
| [TrendRadar config.yaml](https://github.com/sansan0/TrendRadar/blob/master/config/config.yaml) | 增量监测、来源状态、日期过滤 | 热榜平台数据依赖NewsNow，不能算两个独立来源；热榜排名不是资本市场影响排序 |

## 2026年10月31日北京时间约07时07分实测

独立公开请求，HTTP零自动重试；请求时点以私有结果中的UTC时间为准。Rest of World的超时记录保留，未重新请求。

| 入口 | 本地观测 | 正文结论 | 处理 |
|---|---|---|---|
| MKTNews flash type=0 limit=50 | HTTP200，50条，带ISO时点及快讯内容 | 是快讯，不是扩展文章全文 | 已核验发现能力，尚未接生产适配器 |
| FastBull cn/news | HTTP200，参考列表选择器75条；正式财经标题匹配10条 | 抽读两篇，2475/2628字符，页面Unix毫秒时间可转换 | 新解析器已加入OverseasCollector；仍需服务器网络验收 |
| FastBull cn/express-news | HTTP200，50条列表记录带时点 | 本轮未验收每条扩展页 | 只记发现能力，不按正文计数 |
| Google News定向A/H市场搜索 | HTTP200，40条带日期结果 | 原始链接解析与正文尚未验证 | 仅发现候选，不进入正文证据；不能声称彭博原文可用 |
| Rest of World feed/latest | ReadTimeout | 未取得正文 | 记录本次网络失败，不宣称整个媒体永久失效，不自动重试 |
| TechCrunch news-sitemap | HTTP200，38条；财经标题匹配17条 | 两篇1293/3859字符，原始meta时间含时区 | 新sitemap与专用正文解析器已加入；正文测试第二篇只是解析样本，不是推荐选题 |

FastBull正文样本一为《美国经济增长超预期，欧洲能源危机加剧央行政策分歧》，原发布10月30日09:22北京时间；样本二为10月28日的宏观综述，不冒充10月31日新增。TechCrunch第一篇为Anthropic信用评级报道，原发布10月30日21:52UTC即北京时间10月31日05:52；第二篇为Applebee's数据泄露报道，后者仅检验不同结构正文，不等于符合本期财经选题。

来源获取后仍须核对报道的转述归属、事件时间、事实与观点。FastBull宏观综述不替代原始数据来源；TechCrunch转述FT也不是两份独立证据。

## 个股范围调整

新增company_news_scope.py，不写死四只股票。当前App名单决定公司专属入口；换自选股后规则跟随名单。

- 当前自选股的标题/披露主体保留。正文末尾提到自选股，不使另一公司的普通财报变成自选股专属新闻。
- 同行业的重要经营变量保留，例如有明确来水、电价、猪价、材料供需的同业对照，不声称供应商关系或公司直接受益。
- 可选profile.related_companies只接收有来源链接、角色、as_of和valid_until的明确公司关系。支持供应商、客户、竞争者、行业代表。只有行业词不自动变龙头。**当前profile采集器尚未自动生成这套完整公司关系表，此能力有缺口，不宣称已实现全行业龙头自动发现。**
- 涉及造假调查、违约、破产、重大事故等标题的新闻保留作风险线索；不因标题就声称已核实或已经形成重大舆情。社会传播强度仍需来源/传播证据。
- 普通非相关公司财报/公司稿不再凭正文完整、利润增速高获得节目席位。A/H收评、多公司行业变化、国际宏观和产业冲击仍保留。
- 在公开媒体首页发现阶段先挡明显无关财报；采集结果和分析输入再次检查，避免旧缓存重新混入。原始采集文本留在私有raw快照，collector及selection逐条记录排除原因。没有做全网公司实体识别，未识别文本不会被假称已验证无关。

真实旧快照的回放仅检查规则行为，不证明新一期选题完整；该批次不能再付费重跑。目录挤占正文、标题被当事实等上一轮问题仍待后续完整取材流程修复，不因减少无关财报而宣布已解决。

## 服务器检查步骤

新模块和解析器尚未部署；先随下一份经校验的合并源码包安装，不能对当前旧服务器直接运行不存在的模块。安装后：

```bash
cd /var/www/finance-daily/backend
sudo ./venv/bin/python -m app.reference_source_check
# 上一步只预览；下一步是公开网络采集，无模型费用。
sudo sh -c 'cd /var/www/finance-daily/backend && nohup ./venv/bin/python -u -m app.reference_source_check --run > /tmp/finance-reference-source-check.log 2>&1 < /dev/null &'
tail -n 100 /tmp/finance-reference-source-check.log
```

最多8次HTTP，包含两家各最多两篇正文样本。每个入口独立.started标记和结果；重跑不重新请求已有记录，也不删除失败标记。不会恢复调度、写App或生成报告。检查只是几条样本，不是完整新闻采集或全天稳定性证明。

本地完整响应/第三方正文保留在任务outputs/reference-source-probe-20261031，不提交GitHub。仓库只含解析器、模拟测试、检查工具和这份结论。

## 验证记录

630项完整离线回归通过，包含动态换股、正文提及不冒充公司主体、普通财报排除、同业经营变量保留、关系来源与有效期、来源host/paywall/时区、检查标记防重请求和精确失败路由暂停。真实两家四篇样本又用正式解析器离线回放，正文与日期均得到；这些结果不证明整期分析、预测或口播已验收。未调用真实模型。
