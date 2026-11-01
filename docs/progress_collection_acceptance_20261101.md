# 进展驱动自主取材验收入口（2026-11-01）

## 当前依据与本轮范围

用户已在腾讯云轻量服务器安装 cec1e5d（v21），服务健康、数据库可连接、维护暂停保留。独立目录 `/tmp/finance-reading-deps.xiZUZG` 已导入 Trafilatura 2.3.1，正式服务尚未加载该依赖。

之后服务器对三个显式公开链接实际完成3次GET，原始HTML及完整提取结果已上传并离线审阅：统计局40个非表格段落、4表52行数据逐格一致；中新网4段正文完整；新浪16段内容完整，另1段责任编辑署名被剔除。未读图片及下载附件，复杂表头结构未验收。它们仅验证这三个样本的文字提取保真，不代表自主取材覆盖或报告质量过关。

新增 `tools/run_progress_collection_once.py`，直接调用默认 `discover()`，不传固定 `Limits`。实际App名单、七个研究范围、共享提示词、动态预算、补读反馈、重要事件研究检查、按进展收尾均沿用已部署代码。没有写入某篇新闻、预设事件或固定股票名单。

这是独立验收脚本，在上传目录运行即可，不安装或覆盖生产源码，不改 `.env`、正式venv、服务、App数据、调度。旧 `run_primary_collection_once.py` 是固定4次的历史试验，不能替代新入口；新入口不删除其marker，也不解除搜索账号/失败URL的停用记录。

## 用量与成功边界

默认操作仅本地预览：读取名单、检查导入、核对v21中22个已审阅源码文件、记录源码及配置指纹，不执行模型、搜索API、正文HTTP或TTS。

`--run --input-sha <免费预览的指纹>` 才执行自主取材，会消耗当前模型及Tavily账户额度。真实模型名称、路由、名单、各项上限均以服务器预览为准。字符不是token，预留输出不等于实际输出，均不是金额承诺。

按此前服务器的4只股票和默认配置，预算如下：

| 资源 | 初始 | 硬上限 |
| --- | ---: | ---: |
| 搜索调用 | 11 | 24 |
| 新URL读取尝试（含失败） | 22 | 64 |
| 单次模型输入字符 | 108000 | 160000 |
| 额外本地补读字符 | 44000 | 96000 |
| 取材时长 | 360秒 | 900秒 |
| 单次预留输出 | 3300 token | 3300 token |

累计输入不超过2,000,000字符，累计预留输出不超过120,000 token。当前3300的单次预留因此最多容纳36次请求；这是累计输出边界的数学结果，没有新增固定36轮配额，更不要求用完。若 `.env` 配了更小边界或紧急次数上限，仍执行该值。报告独立8次预算，本入口不调用报告。

每次模型POST前再次核对App名单；每次网络入口核对维护暂停、源码/脚本/配置指纹和总时长。暂停若被移除则停止后续请求，已发出的请求仍可能收费。模型与工具均不自动重试，模型不切备用服务，HTTP不自动跳转到模型服务的其他端点。公网GET另设 `3 × URL硬上限` 的尝试上限，含跳转和失败；默认最多192次尝试，不代表一定发满。

同一验收有进程锁及永久 `data/diagnostics/progress-collection-v1/started.json`，创建在所有收费前置检查之后。存在即拒绝重复执行；失败也保留，不能通过删marker、改试验名或清失败台账盲目重跑。新的阶段若需要再次取材，应先审阅这次结果与失败原因。

预览2小时内有效；再次免费预览若没有变化，会保留原截止值与指纹，不偷偷刷新资料时点。超时或源码/模型/名单/配置变化必须重新免费预览。底稿保留真实采集时间，不宣称截止时版本已独立验证。

## 阅读证据与输出

每个请求保存发送前的正文范围以及模型是否完整返回。底稿区分：

1. 网页全文已保存的字符数。
2. 工具已提供的精确区间，包括尚未进入下一模型请求的补读。
3. 对应完整模型响应的请求包含了哪些区间。

第3项不证明模型认真阅读或独立核实；失败请求的接收情况未知，保留预留用量。图片和下载附件未读，不能由HTML正文的区间覆盖推导整篇多媒体内容已读完。

主要私人产物在新episode目录：`primary-discovery.json`、`materials.json`、`acceptance-review.md`、`acceptance-review.json` 和原始响应。运行用量、状态、请求区间在 `data/diagnostics/progress-collection-v1/result.json`。仅有效完成且名单未变的取材可以导出 `report-input.json`；它仍须经过独立报告前完成度检查，不会自动收费成稿。

成功返回只能表示待人工审阅。需要检查：是否找到重要外盘收盘和已公布政策、A/H市场主线、行业及当前公司事项；选择/舍弃理由是否成立；事实/背景/分歧/传导的证据是否匹配；是否漏读结尾、误用预测/转载或用标题代正文。预算停止、延期任务和换源失败必须保留为缺口。

## 服务器操作

交付包解压后目录名为 `daily-finance-progress-acceptance-v1`，只需上传这一小包到 `/tmp`，不重新下载仓库。以下操作在用户自己的服务器执行。

第一步：解压、运行7个完全模拟网络/DB的离线用例、免费预览。`set -e` 会在失败时停止，不能跳过失败直接收费。

```bash
(
set -e
python3 -m zipfile -e /tmp/daily-finance-progress-acceptance-v1.zip /tmp
cd /var/www/finance-daily/backend
sudo env PYTHONPATH=/tmp/finance-reading-deps.xiZUZG \
  venv/bin/python -m unittest discover \
  -s /tmp/daily-finance-progress-acceptance-v1/backend/tests \
  -p test_progress_collection_runner.py
sudo env PYTHONPATH=/tmp/finance-reading-deps.xiZUZG \
  venv/bin/python /tmp/daily-finance-progress-acceptance-v1/tools/run_progress_collection_once.py
)
```

若临时依赖目录不存在，先停止并回传状态，不在这一步重装或修改正式环境。先审阅免费输出的模型、名单、边界和 `ready_to_run`；尚未准备好或上限与意图不符就先处理。本轮交付不代表用户已授权直接用满上述额度。

第二步：明确接受免费输出中的实际用量范围后，使用该次SHA。执行可能持续数分钟；保持终端连接，不因没有新日志而再次启动。下面是带占位符的收费命令，不要把占位符直接执行：

```bash
cd /var/www/finance-daily/backend
sudo env PYTHONPATH=/tmp/finance-reading-deps.xiZUZG \
  venv/bin/python -u /tmp/daily-finance-progress-acceptance-v1/tools/run_progress_collection_once.py \
  --run --input-sha '替换为免费预览中的input_sha256'
```

第三步：无论成功还是已有失败结果，都先离线导出，不重复收费。

```bash
sudo /var/www/finance-daily/backend/venv/bin/python \
  /tmp/daily-finance-progress-acceptance-v1/tools/run_progress_collection_once.py \
  --export-review /tmp/daily-finance-progress-review.zip
```

导出文件为600权限，包含底稿、正文、HTML和用量，不包含 `.env`、密钥、连接指纹、准备输入或生产数据库。输出包如已存在不会覆盖。下载后上传供离线审阅；第三方全文不提交GitHub。

## 本轮验证状态

本轮只进行源码与部署包清单审阅、产物打包和Git操作；未在本环境执行这7个用例、启动入口或调用项目模型/搜索/正文HTTP/TTS，未部署或重启服务器。7个离线用例覆盖累计输入/输出边界、可选紧急次数上限、不完整响应/取消保留计费记录、配置漂移在收费标记前拒绝、已开始验收不重跑。用例须在服务器实际运行，不能把已编写当作通过。

这是项目内部CLI，不被现有Skill调用，无Skill接口变更。
