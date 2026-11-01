# 📊 财经日报 (Finance Daily)

> **最新验收回传（2026-11-01）**：首次自主取材发出2次模型、1次搜索、0次正文请求。搜索先HTTP400，随后模型的说明前缀触发JSON解析失败，内容覆盖未通过。已准备[解析/失效止损修复及独立搜索诊断](docs/discovery_failure_repair_20261101.md)，待服务器离线验收；保留旧失败与自动化暂停，不重跑整期或声明HTTP400已解决。

> **腾讯云服务器最新状态（2026-11-01）**：cec1e5d已安装，服务健康、数据库连接、自动化暂停；GitHub备份权限已通过。独立依赖目录下实际读取3个新网页成功，上传HTML已逐段/逐格审阅，文字未发现实质缺段；图片、附件、自主取材覆盖及报告/播客质量仍待验收。新增[进展驱动自主取材验收入口](docs/progress_collection_acceptance_20261101.md)，默认免费预览，不覆盖生产、不重启服务；明确指定预览指纹才消耗模型和搜索额度。旧固定4次试验不用于验证新默认流程。[合并更新记录](docs/server_reviewed_upgrade_20261101.md)保留安装依据。

> **接手修改请先读：[完整agent交接文档](docs/AGENT_HANDOVER.md)**（2026-10-31）。包含真实运行逻辑、线上/代码版本差异、目标、未完成问题、失败尝试、费用与部署保护、下一步验收。下方是项目功能说明，不代表当前所有能力已验收；生产自动化目前维护暂停。

> **后续开发增量（未部署）**：[通用正文离线验收与 v20 合并升级准备](docs/reading_acceptance_20261031.md)。支持任意本期响应快照的完整正文复核、可选提取库实际导入检查；不调用收费服务，不代表真实取材或播客质量已通过。

> **本轮主流程接入（未部署）**：[主动取材到报告输入](docs/primary_report_flow_20261031.md)。成功取材可导出同一期报告输入，接入既有写作/审查，保持证据ID、原时点和共享预算。本地3次新网页GET及报告输入预览已实际运行，未生成收费报告或音频，尚未验收整期内容。

> **资料质量增量（未部署）**：[推广提示与补查计划](docs/primary_material_quality_20261031.md)。5次新网页GET、1次保存响应离线修复；推广稿换源，7份正文进入免费报告输入预览，仍缺独立行业资料。未收费写稿、未测试、未部署。

> **通用取材能力增量（未部署）**：[实际回执驱动的补查循环](docs/discovery_feedback_loop_20261031.md)。每轮重算缺口、预算内自动补读、核对结束声明并按实际选材导出。已实际阅读保存长文并补齐后6,743字符；未运行测试或新日期自动取材实网验收，不代表能力验收通过。

> **通用取材继续改进（未部署）**：[补读分配、缓存复用与调用前检查](docs/discovery_reading_budget_20261101.md)。按实际取材顺序轮流补读并优先尾段，阅读额度耗尽时不买新搜索，公司不匹配与网页失败分开记录；默认搜索不可用在模型调用前停止。保存长文的尾段/中间补读已执行，未运行测试或新日期实网取材。

> **上一版任务额度方案（5+3分配已被下方进展驱动方案替代，未部署）**：[规模预算与缺口分批扩展](docs/discovery_adaptive_budget_20261101.md)。默认按研究范围和动态名单分配搜索/网页/补读/输入/时长，同次工具回复可申请扩展；整期模型仍8次，取材最多5次并为报告预留3次。只执行给定数量的本地预算预览，0收费调用，未运行测试或部署。

> **当前取材预算（替代上一版5次限制，未部署）**：[研究进展驱动与独立报告预算](docs/discovery_progress_driven_20261101.md)。默认取材没有固定模型轮次，以累计用量、时长、无进展和实际研究缺口收尾；重要事件检查原始事实、背景、分歧与传导，未完成材料阻止直接收费成稿。报告默认独立8次；[服务器免费验收步骤](docs/server_collection_acceptance_20261101.md)。本轮只执行本地预算预览，回归测试与实网质量未验收。

一款面向个人投资者的智能财经助手 App，自动收集全球主要财经新闻，每日生成深度分析报告和配套播客音频，支持个股追踪和 AI 投资预判。

## ✨ 核心功能

### 1. 每日财经深度报告
- 🌍 自动采集全球主要财经新闻，重点关注中国相关报道
- 📈 对重大事件进行前因回溯，关联历史类似案例
- 💡 提供符合经济常识的深度分析，作为投资参考
- ⏰ 每天早上 6 点（可自定义）自动推送

### 2. 播客音频生成
- 🎙️ 将已核验的报告改写为 20 分钟以内的播客音频，长度由有效信息决定
- 📻 单人、自然聊天式财经分析，用清晰投资主线串联判断、理由和条件性应对
- 🎧 支持 App 内直接播放、倍速调节

### 3. 个股/行业追踪
- ⭐ 支持 A 股和港股自选股管理
- 📊 展示技术指标（K线、MA、MACD、RSI、KDJ 等）
- 🤖 基于基本面 + 技术面 + 情绪分析的 AI 投资预判

## 🏗️ 技术架构

```
finance-daily/
├── backend/          # Python 后端服务
│   ├── app/
│   │   ├── main.py           # FastAPI 入口
│   │   ├── config.py         # 配置管理
│   │   ├── models/           # 数据模型
│   │   ├── services/         # 核心业务服务
│   │   │   ├── news_collector.py    # 新闻采集
│   │   │   ├── ai_analyzer.py       # AI 分析
│   │   │   ├── podcast_generator.py # 播客生成
│   │   │   ├── stock_service.py     # 股票数据
│   │   │   └── scheduler.py         # 定时调度
│   │   ├── routers/          # API 路由
│   │   └── utils/            # 工具函数
│   └── requirements.txt
│
└── mobile/           # React Native 移动端
    ├── app/                  # Expo Router 页面
    │   ├── (tabs)/          # Tab 导航页面
    │   │   ├── index.tsx    # 首页-今日报告
    │   │   ├── podcast.tsx  # 播客页面
    │   │   ├── stocks.tsx   # 自选股页面
    │   │   └── settings.tsx # 设置页面
    │   └── report/[id].tsx  # 报告详情页
    ├── components/          # 可复用组件
    ├── stores/              # Zustand 状态管理
    └── services/            # API 服务
```

## 🛠️ 技术栈

| 模块 | 技术选型 | 说明 |
|------|---------|------|
| **移动端** | React Native + Expo | 一套代码同时运行在 Android/iOS |
| **状态管理** | Zustand | 轻量简洁的状态管理 |
| **UI 组件** | React Native Paper | Material Design 风格 |
| **后端** | Python FastAPI | 高性能异步框架 |
| **定时任务** | APScheduler | 灵活的任务调度 |
| **数据库** | SQLite → PostgreSQL | MVP 用 SQLite，后续可迁移 |
| **AI 分析** | 按任务配置模型 | 分析、核验、提取和口播独立路由 |
| **语音合成** | Edge TTS | 免费、中文效果好 |
| **股票数据** | AKShare / Tushare | A股 + 港股数据 |

## 🚀 快速开始

### 环境要求

- Python 3.10+
- Node.js 18+
- Expo CLI

### 后端启动

```bash
cd backend

# 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env
# 编辑 .env 填入你的 API Keys

# 启动服务
uvicorn app.main:app --reload --port 8000
```

### 移动端启动

```bash
cd mobile

# 安装依赖
npm install

# 启动开发服务器
npx expo start
```

扫描二维码在手机上打开，或按 `a` 启动 Android 模拟器，按 `i` 启动 iOS 模拟器。

## ⚙️ 配置说明

### 环境变量 (.env)

```bash
# AI 服务（至少配置一个）
ANTHROPIC_API_KEY=your_anthropic_key  # 推荐，分析质量最好
OPENAI_API_KEY=your_openai_key        # 备选

# 股票数据（A股深度数据需要）
TUSHARE_TOKEN=your_tushare_token      # 免费注册获取

# 推送时间
DAILY_REPORT_HOUR=6
DAILY_REPORT_MINUTE=0
```

### 新闻源配置

默认配置了以下免费 RSS 源：
- 华尔街见闻
- 财联社电报
- 金十数据
- 东方财富研报
- 财新网
- 第一财经

可在 `config.py` 中自定义添加更多源。

## 📱 功能截图

> MVP 版本开发中，截图稍后补充

## 🗺️ 开发路线图

### MVP 版本 (当前)
- [x] 后端基础架构
- [x] 新闻采集服务
- [x] AI 分析报告生成
- [x] 播客音频生成
- [x] 股票数据服务
- [x] 移动端 UI 框架
- [ ] 完整功能测试
- [ ] 部署上线

### 后续迭代
- [ ] 推送通知
- [ ] 历史报告搜索
- [ ] 自定义关注行业
- [ ] 股票组合分析
- [ ] 投资收益追踪
- [ ] 社区分享功能

## 📝 API 接口

### 报告相关
- `GET /api/reports` - 获取报告列表
- `GET /api/reports/today` - 获取今日报告
- `GET /api/reports/{id}` - 获取报告详情

### 播客相关
- `GET /api/podcasts/today` - 获取今日播客
- `GET /api/podcasts/{id}/audio` - 获取音频文件
- `POST /api/podcasts/{id}/regenerate` - 重新生成播客

### 股票相关
- `GET /api/stocks/watchlist` - 获取自选股列表
- `POST /api/stocks/watchlist` - 添加自选股
- `DELETE /api/stocks/watchlist/{id}` - 移除自选股
- `GET /api/stocks/{code}/prediction` - 获取投资预判

## 🤝 贡献指南

欢迎提交 Issue 和 Pull Request！

## 📄 许可证

MIT License

---

**免责声明**：本应用提供的分析和预测仅供参考，不构成投资建议。投资有风险，入市需谨慎。

## 内容质量升级与现有环境迁移

**后续 AI 接手请先读：[项目状态、验收结果与下一步工作](docs/AI_HANDOFF.md)。** 该文档区分已提交代码和线上已安装版本，并列出真实数据验收、剩余缺口、费用及部署约束。

现有 App 的自选股表 `stocks` 是采集和分析的唯一标的来源，删除最后一只股票会清空分析范围；读取数据库失败会中止，不读取缓存标的替代。
模型通过 `ANALYSIS_*`、`REVIEW_*`、`EXTRACTION_*`、`PODCAST_*` 分别配置。未设置阶段型号时兼容显式的 `AI_MODEL`。不再默认过期型号，也不调用匿名免费服务。

`.env.example` 提供 DeepSeek Pro 分析/核验、Flash 提取/改写的配置方案。`REVIEW_PROVIDER=backup` 可显式使用另一家兼容服务核验。实际可用模型需用部署账号验证；更换型号不代表财经准确率已验收。

在现有服务器保留原 `.env` 和数据库，先在测试副本配置新的阶段字段；不要用示例覆盖真实密钥。正式验收需要实际 App 数据库与模型授权。

```bash
cd backend
python -m app.preflight
python -m unittest discover -s tests -v
```

预检不输出密钥，只报告模型配置、App 自选股可读性及音频依赖。测试使用临时数据库和模拟 HTTP 响应，不能替代实时采集与完整音频验收。
输出被截断、缺少证据、核验失败、音频缺句或超过20分钟均停止发布。新闻URL存在仅代表可追溯，不代表内容已独立证实。
