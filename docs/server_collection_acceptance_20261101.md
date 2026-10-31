# 服务器需要执行的免费验收

本轮需要服务器核对实际App数据库、提取依赖和运行兼容性。先做下列免费检查；不运行真实模型、收费搜索或TTS，不恢复生产调度。本地尚未运行这些回归测试，不能把下面的命令当成已通过结果。

## 1. 获取待验收版本

目标开发分支：`improve/reading-acceptance`。最终交付会如实说明GitHub推送是否成功；只有确认远端已有该分支后才从GitHub获取。代码在独立检出目录验收，不在正在运行的生产目录直接pull/覆盖。

若当前GitHub连接无写权限，交付中的Git bundle是同一份已提交修改，基线为仓库提交 `57e4f0a922a0293a6886726a8f0c2ef548308bcf`，不包含服务器.env、数据库或私有新闻。可以在已有该基线的仓库中获取bundle：

```bash
git fetch <已下载的bundle文件> improve/reading-acceptance
git worktree add --detach .review-collection FETCH_HEAD
```

若由有写权限的服务器账号发布到GitHub，可在读入bundle后执行：

```bash
git push origin FETCH_HEAD:refs/heads/improve/reading-acceptance
```

这是发布开发分支，不运行服务器程序。若远端同名分支已被其他人更新，普通push会拒绝，先检查差异，不使用force。GitHub权限问题不通过换共享身份或上传密钥解决。

## 2. 检查本地预算和正文依赖

进入隔离检出副本的 `backend`，使用项目现有Python虚拟环境：

```bash
python -m app.discovery_budget_check --watchlist-count 4
python -m app.reading_acceptance
```

第一条的4是给定规模，不读取App名单。应看到 `mode=progress_driven_collection`、`model_request_cap=null`、`report_model_calls_independent=8`（如服务器显式配置其他上限，按实际配置展示）、项目请求计数为0。

第二条只检查提取库是否能实际导入；退出码2代表依赖未就绪，回传原因，不反复联网试来源，也不直接改系统Python。

旧.env可以保留，`RESEARCH_REPORT_MODEL_RESERVE` 已不参与新计算。旧搜索上限若显式为4，实际仍是4；不要为了“看起来通过”修改为24。新的累计用量配置为保护边界，先查看实际值，再决定未来真实采集预算。

## 3. 运行一次回归测试

同一隔离目录中执行下面的一次命令：

```bash
PYTHONPATH=tests python -m unittest test_discovery_budget test_discovery_completion test_discovery_feedback test_primary_discovery test_primary_report test_model_gateway
```

这些用例采用本地状态和模拟传输，目标是核对预算、回执、缺口与暂停边界，不能证明真实网页/模型研究质量。它们不需要真实服务商密钥，不启动HTTP服务。使用隔离目录，避免已有生产文件干扰本地用例。

回传最后的通过/失败摘要与失败堆栈；不要发送.env、API key、完整原始HTTP响应或数据库。如果缺少依赖，回传模块名，不重复运行整套、不在生产目录直接安装。

## 4. 读取当前App名单做免费预检

这一项仅在隔离检出副本已明确连接到原App数据库的只读检查环境后执行；不要让新目录误建空数据库，也不要用WATCHLIST_STOCKS缓存假装当前App名单。

```bash
python -m app.primary_discovery_check
```

预期显示实际App自选股及对应预算，模型、搜索、TTS请求均0。数据库缺失或无法确认连接时停止，回传错误即可。该命令不会解除维护暂停、配置搜索账户或发请求。

## 5. 阅读已有一次取材的实际记录（可选）

仅当当前backend中已有真实 `episode-.../primary-discovery.json` 时使用：

```bash
python -m app.collection_review --episode <现有episode目录名>
```

输出候选标题/URL、正文读取区间、重要事件与范围缺口、停止原因和实际用量，不输出完整新闻正文，不重新取材。

## 后续真实验收

前述检查通过后，仍需另做一轮新日期、实际App名单的真实取材，审核是否漏重要事件、关键正文是否读足、背景/分歧是否可靠、缺口是否真实、实际用量和账单如何。该轮会消费模型和搜索费用，必须使用与这版默认预算一致的、已审阅的执行入口；本轮没有执行或授权自动执行这一收费步骤。

不要运行旧的固定4次模型试验来冒充新流程验收，不删除旧marker，不解除生产暂停，不生成报告或音频。当前源码不是已经过服务器验证的生产覆盖包；原v20基线和共享文件合并校验仍必须完成。
