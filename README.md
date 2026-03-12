# 📊 财经日报 (Finance Daily)

一款面向个人投资者的智能财经助手 App，自动收集全球主要财经新闻，每日生成深度分析报告和配套播客音频，支持个股追踪和 AI 投资预判。

## ✨ 核心功能

### 1. 每日财经深度报告
- 🌍 自动采集全球主要财经新闻，重点关注中国相关报道
- 📈 对重大事件进行前因回溯，关联历史类似案例
- 💡 提供符合经济常识的深度分析，作为投资参考
- ⏰ 每天早上 6 点（可自定义）自动推送

### 2. 播客音频生成
- 🎙️ 将文字报告转换为 20-30 分钟的播客音频
- 📻 采用单人播报风格（类新闻联播）
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
| **AI 分析** | Claude API | 深度分析质量最佳 |
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
