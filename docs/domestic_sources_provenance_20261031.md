# 国内新闻入口补充和来源出处

## 哪些来自GitHub参考

不能把以前所有媒体入口都归因于这次研读。GitHub提供的是采集实现或设计参考，新闻内容实际来自媒体自己的公开网页/接口。

| 入口或能力 | 本轮明确参考 | 实际获取方式 | 当前状态 |
|---|---|---|---|
| FastBull、MKTNews | NewsNow server/sources/fastbull.ts、mktnews.ts | FastBull公开列表和文章HTML；MKTNews公开JSON快讯 | v16已有FastBull正文适配，MKTNews仅诊断 |
| TechCrunch、Rest of World | Fundus US出版社定义及专用解析器 | 新闻地图/订阅发现，再读公开文章HTML | TechCrunch v16可读，Rest of World本地超时不重试 |
| Google News定向搜索 | Open News googlenews_engine.py、sources.py | Google News搜索RSS | 目录已测；原始链接和正文未完成验收 |
| 来源分类和采集流程 | 2learnsomething/daily-news sources.yaml和skill | 只作设计参考 | 不能声称其29个来源都是可用接口；未搬其资金规则或胜率 |
| 先前财联社、第一财经、21世纪、界面等 | 项目此前已有适配器与公开页面适配；不全部来自这批GitHub项目 | 公开首页/列表、公开页面state和正文 | 不能事后编造某个GitHub项目是全部旧适配器出处 |
| 本次澎湃财经、钛媒体、财经网 | 下列RSSHub路由源码 | **直连媒体公开JSON列表，再读公开文章HTML，不调用公共RSSHub代理** | 两篇/家正文与日期样本已测，新增适配器 |

本轮参考文件：

- [RSSHub thepaper/channel.ts](https://github.com/DIYgod/RSSHub/blob/master/lib/routes/thepaper/channel.ts)、[utils.tsx](https://github.com/DIYgod/RSSHub/blob/master/lib/routes/thepaper/utils.tsx)：财经频道25951及移动文章公开state。
- [RSSHub tmtpost/new.ts](https://github.com/DIYgod/RSSHub/blob/master/lib/routes/tmtpost/new.ts)、[util.ts](https://github.com/DIYgod/RSSHub/blob/master/lib/routes/tmtpost/util.ts)：最新列表入口。我们没有采用其API main字段补正文，改读网页可见正文，避免把summary或潜在预览当全文。
- [RSSHub caijing/roll.ts](https://github.com/DIYgod/RSSHub/blob/master/lib/routes/caijing/roll.ts)：滚动JSON及正文选择器。HTTPS列表已单独实测。
- [RSSHub yicai/headline.ts](https://github.com/DIYgod/RSSHub/blob/master/lib/routes/yicai/headline.ts)、utils.ts：头条频道接口。本次未接入此列表，原因是最新条目停在10月29日且夹杂更早置顶，不能用列表顺序当新鲜度。
- 虎嗅路由明确标记antiCrawler，未测试或接入其私有/会员接口。没有为扩大来源数量绕过访问限制。

## 本地实测

2026年10月31日北京时间约07:39开始，零自动重试，无LLM、TTS或付费搜索。真实响应留在私有outputs/domestic-source-probe-20261031，不向GitHub上传第三方正文。

| 入口 | 发现结果 | 正文样本 | 注意 |
|---|---|---|---|
| 澎湃财经频道 | POST公共频道接口HTTP200，10条 | 《五大上市险企前三季度净利润承压，保险主业表现如何？》1172字符，10月30日22:28:48；《百亿私募三季报重仓路径曝光》2075字符，22:32:47 | 记者与原来源保留；历史持仓不推成当日资金流；body必须两端均见于公开可见HTML，缺正文不回退summary |
| 钛媒体最新列表 | GET公共JSON HTTP200，30条 | 南方电网/华为与电网设备行业2649字符；非洲铁矿/铝土矿供应链4180字符；均10月30日17:34 | 这两篇分别来自“预见能源”“万联万象”，是作者投稿，不冒称钛媒体记者调查；带观点的机制要归属作者 |
| 财经网滚动 | GET公共JSON HTTP200，100条 | 半导体设备商订单/业绩1066字符，10月30日（日精度）；跨国企业中国机会6099字符，17:53:14 | 前篇标注转载证券时报，不作为两份独立证据。日精度是区间，不伪造发布时间00点；大量普通财报仍需排除，不整池接纳 |
| 第一财经头条 | GET新公开接口HTTP200，30条 | 一篇债市互换便利正文可读，但原发布10月26日19:48:35 | 最新列表条目10月29日，含旧置顶；HTTP成功不等于实时能力。当前既有第一财经适配器保留，不用这个旧头条列表重复替换 |

正式新增解析器domestic_discovery.py，用既有PublicNewsCollector的时间窗口、负面路由台账、严格host/path、预算与选题范围。澎湃列表显式paywalled=false，钛媒体列表排除付费专栏和推广；正文另拒绝付费标记/LD限制。财经网只允许审核过的财经/产业子域名，不跟任意外链。

还修复了上一版范围筛选的一处过宽判断：多家险企、半导体设备商的行业综述和私募持仓综述虽然含“财报/利润”，不应当作一个无关公司的例行财报排除；新增回归用例。普通个股的高增速仍不自动变重要。

## 局限和下一步

这些样本说明国内新增入口能提供市场/产业材料，不证明全市场重要新闻已覆盖，也不证明文章所有事实准确。来源名单不是独立信源数；普通公司稿、作者推广、重复转载仍会存在。动态行业重要公司关系表、主编选题排序、目录挤正文和关键论点补读仍需继续修，保持生成暂停，不重跑旧付费trial。

新增app.reference_source_check --group domestic。默认只预览，--run最多9次公开HTTP（三个列表，各最多两篇正文样本），有稳定开始标记防止重复请求，不恢复调度、不写App。腾讯云结果尚未取得。

验证：635项完整离线回归通过；另外12项国内正文/公司范围针对性检查通过。六个新媒体正文样本均用正式解析器回放取得正文、原日期与作者/转载信息。测试数量不代表选题或预测质量通过。
