# 无历史快照时的公开正文读取检查

## 服务器真实状态

用户已成功安装源码cec1e5d，安装回执确认服务健康、数据库连接、自动化暂停、调度停止。该版本已通过仓库专用SSH授权推送GitHub并核对远端提交。当前App名单为牧原股份、宁德时代、长江电力、华海诚科四只A股。

服务器正式环境缺少通用提取库。用户已按requirements-extraction.txt将Trafilatura 2.3.1及依赖安装到独立目录 `/tmp/finance-reading-deps.xiZUZG`，仅通过该目录的PYTHONPATH验证导入ready=true；不是正式服务已加载它。服务器没有找到episode原始网页快照，无法执行旧HTML离线回放。

## 通用检查入口

新增 `tools/check_public_reading.py`，接受1至3个显式公开文章URL。默认只给本地计划，`--run-public`才通过现有read_public读取：最多9次fetch尝试（包含重定向及失败）、最多60秒预算、单篇沿用2MiB边界，无重试。仍执行公网地址、TLS、访问类型、来源时间、失败路径暂停和同URL缓存复用保护。

每个URL在data/diagnostics/public-reading-check-v1中写独占开始标记，重复或并发执行会跳过，既有失败不会因运行新脚本而复活。必须保留维护暂停，不修改.env、不启动服务、不读写App数据库，不调用模型、搜索API、TTS或发布。DNS失败也计fetch尝试，计数不是实际HTTP响应数量。

成功取得的HTML按现有逻辑保存到新episode/public-responses；非200或非HTML等在取回正文前拒绝的响应只记录失败原因。保留实际新截止时点，不将时钟改回文章发布日期。存储全文、提供1800字符片段和模型读完是三件事；本工具根本不调用模型。

取得快照后自动执行现有离线replay，完整文字和元数据保留在原工作区的reading-review目录，终端仅输出状态、标题、正文字符数、通用提取是否被使用、失败原因和私有报告目录。通用提取加载成功或非空正文，不代表全文完整、时间正确、事实准确或内容有价值，仍需审阅。

## 本轮样本与命令

样本URL只作为命令参数，不写入收集与阅读规则：统计局PMI发布用于检查通用容器/表格，港股和美股报道用于检查不同页面布局。所有页面仍需现场核对是否在72小时窗口及实际提取质量，不预填合格结果。

```bash
cd /var/www/finance-daily/backend
sudo env PYTHONPATH=/tmp/finance-reading-deps.xiZUZG \
  /var/www/finance-daily/backend/venv/bin/python \
  /tmp/check_public_reading.py --run-public \
  --url 'https://www.stats.gov.cn/sj/zxfbhjd/202610/t20261031_1965718.html' \
  --url 'https://www.chinanews.com/cj/2026/10-30/10723632.shtml' \
  --url 'https://finance.sina.com.cn/stock/usstock/c/2026-10-31/doc-iniwzyfm4338275.shtml'
```

先把交付的check_public_reading.py上传到/tmp。无需覆盖生产源文件、安装新主程序包或重新下载项目。整个命令只有公开网页GET，没有模型或搜索API费用。0篇通过时退出码2，回传结果诊断，不删除marker重复跑。

## 后续验收

本工具截至交付尚未运行，开发环境未执行测试、编译、lint或真实财经网页请求。网页读取之后仍需验收自主检索、换源、阅读覆盖、重要事件选择，以及报告和播客。旧4次模型试验入口不适用于新默认预算，不重跑旧marker。阅读依赖仍处于独立验收目录，待实际读取及兼容性通过后再接入正式服务。

统计局样本来自[原始发布页](https://www.stats.gov.cn/sj/zxfbhjd/202610/t20261031_1965718.html)，另外两条来自此前公开页面检查记录。样本不是投资建议或完整重要事件清单。新入口是项目内部命令行工具，未被平台Skill调用，不涉及Skill接口变更。
