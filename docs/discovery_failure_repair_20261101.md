# 首次进展驱动取材失败复盘及修复（2026-11-01）

## 实际失败顺序

用户在服务器运行免费指纹批准的一次取材，上传完整底稿。实际执行时间12:42:57—12:43:10，原取材截止12:34:16，生产暂停保留。

1. 第一次模型完整响应选择5项搜索：A股、港股、美股、政策、商品。
2. 只有第一项真正发往Tavily，返回HTTP400。其余4项被程序本地拦截，回执是 `search_route_failed_no_retest`，不是4次独立搜索失败。
3. 没有候选或正文可继续处理，控制器仍买了第二次模型响应。它先写一句说明，再给出有效JSON；旧解析器直接对整串 `json.loads`，报JSONDecodeError。
4. 最终模型2次、搜索HTTP1次、正文HTTP0次，没生成报告/音频或App内容。

服务商记录两次模型输入共21590 token、输出共526 token。6600是两次预留输出上限，不是实际输出；搜索HTTP400是否计入账户扣费，应以服务商账单为准。没有费用金额推算。

这是此前离线用例覆盖不足：应验证搜索调用合同，并在路径不可用且没有现存资料可处理时，在下次模型请求前停止。第二次模型请求本可避免。

## 已改代码

- JSON解析接受“短说明前缀 + 一个完整JSON对象”或完整代码围栏。嵌套结构按JSON解析，不用正则提取；多对象、重复键、尾随指令、缺损JSON仍拒绝，不收费重问。原始响应仍保留，完整工具包仍在执行前验证。
- 搜索路线已失败、没有已提供正文，且反馈没有任何可执行候选/补读任务时，立即记录 `search_unavailable_no_readable_candidates`。已有可读候选或正文仍能继续处理，不能把账号故障等同于全网没消息。
- 请求构造集中到 `search_request()`。绝对起止日期与相对 `time_range` 不再同时发送，其他检索目的、日期原值、基础搜索、关闭自动升级等保持。**这只是减少参数歧义，尚不能证明HTTP400的根因就是时间参数组合。**
- 后续失败回执保留请求参数、HTTP状态、已知错误字段/信号及错误摘要指纹，且传到取材底稿。不输出凭据、请求头或任意服务商错误原文。

已核对 [Tavily官方Search接口文档](https://docs.tavily.com/documentation/api-reference/endpoint/search)：日期范围与相对时间窗是检索提示，结果日期可能是发布或更新估计，不代表交易日或截止时版本。官方当前文档列出了本项目使用的日期字段，因此不能仅凭HTTP400就断言某一字段不受支持。旧错误原文未保存，无法离线还原具体拒绝理由。

## 本轮小包的用途

兼容用户已确认安装的v21实际源码，只替换两个运行文件：`primary_discovery.py`、`web_research.py`。安装器校验旧/新哈希并先备份；保留.env、依赖、数据库和所有暂停/试验marker。此次不重启服务；后续独立CLI读新源码，现有常驻服务保持暂停，其内存模块不宣称已重新加载。

包外层同时带11个新的离线用例和 `tools/check_search_contract.py`。该诊断入口默认：

1. 读取已经付费取得的两条模型响应，使用新解析器离线回放，不执行其中工具。
2. 展示同一条失败查询的旧/新请求参数和新指纹。
3. 模型、搜索、正文HTTP、TTS均0。

先把 `daily-finance-discovery-repair-v22.zip` 上传到服务器 `/tmp`，执行：

```bash
(
set -e
python3 -m zipfile -e /tmp/daily-finance-discovery-repair-v22.zip /tmp
sudo /var/www/finance-daily/backend/venv/bin/python \
  /tmp/daily-finance-discovery-repair-v22/install_upgrade.py \
  --project /var/www/finance-daily --apply
cd /var/www/finance-daily/backend
sudo env PYTHONPATH=/tmp/finance-reading-deps.xiZUZG \
  venv/bin/python -m unittest discover \
  -s /tmp/daily-finance-discovery-repair-v22/backend/tests \
  -p test_discovery_failure_repair.py
sudo env PYTHONPATH=/tmp/finance-reading-deps.xiZUZG \
  venv/bin/python /tmp/daily-finance-discovery-repair-v22/tools/check_search_contract.py
)
```

这些命令不调用收费服务，不清除旧失败，不重跑整期。若校验/用例失败，`set -e`立即停止；回传输出，不跳过保护。临时依赖目录若已消失，不在此轮擅自安装到正式venv。

## 后续单次搜索诊断

只有免费输出审阅后，用户明确执行 `--run-search --input-sha <本次指纹>` 才会发送**最多1次Tavily搜索HTTP**，不调用模型、不读取正文；可能消耗搜索账户额度。这是针对已审阅请求变更的显式复核，不是自动重试。诊断入口有独立永久开始标记，失败也不自动重跑。它不会删除旧搜索账号停用记录，即使返回200，也必须先审阅原因再决定如何恢复主取材路径。

原 `progress-collection-v1/started.json`、原始响应、用量与旧账号停用记录全部保留。旧独立取材脚本还绑定v21源码，且已有开始marker，不能拿它直接重跑；下一次整期取材的准备必须以新源码、明确恢复依据与新的预算审阅为前提，不靠改trial名绕开失败。

本轮在工作区只读附件、审阅代码和官方文档、修改/打包/备份；未执行应用用例、入口、真实搜索/模型/正文HTTP/TTS或服务器安装。11个新用例已编写而未执行；现场通过情况以用户回传为准。旧7个用例已有服务器OK回执，不代表这11个新用例已通过。

项目内部CLI不被现有Skill调用，无Skill接口变更。
