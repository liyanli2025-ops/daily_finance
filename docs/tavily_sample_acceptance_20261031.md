# Tavily 首次服务器小样本验收

用户服务器 v18 已安装；本轮密钥检查为 `configured=true`、`enabled=false`。这表示密钥字符串已读到，尚未验证账户、网络、搜索结果或正文质量。不要把开关改为 true 后直接恢复定时节目。

独立工具 `tools/run_tavily_acceptance_once.py` 兼容已部署 v18，不需要安装新源码包。默认仅预览；`--run` 临时在本进程打开搜索，结束或异常均还原，不修改 `.env`、运行中服务、App报告或自动暂停状态。

## 明确范围与费用

- 最多4次 Tavily Search basic POST，无自动重试，不使用 Tavily Extract/Research、Claude或TTS。账户配置更低上限时服从更低值。
- 分别抽查A股、港股、美股和App数据库第一只自选股；名单为空时最后一项改行业样本。只是链路抽查，不是全市场或完整自选股验收。
- Basic搜索参考每请求1积分，最多4积分；实际扣费以账户账单为准。[官方计费说明](https://docs.tavily.com/documentation/api-credits)。普通网页正文通过现有匿名读取器取得，每个查询最多一个URL，每URL至多3个含跳转GET，总计至多12个，不绕过登录或付费墙。
- 账户/搜索请求失败后停止后续查询；已停用的精确URL跳过，同一URL本轮不重复读。正文失败保留原因，不伪装为没有相关新闻。
- 开始标记 `backend/data/diagnostics/tavily-acceptance-v1.started` 以独占方式创建；断线或重复命令不会再次扣搜索积分，不删除标记重跑。
- 结果 `backend/data/radar/cache/tavily-acceptance-v1.json` 逐步保存，原文工作区保持24小时生命周期；终端只显示摘要。没有把搜索摘要冒充正文，也没有将小样本完成等同质量通过。

## 操作

将独立Python文件上传到服务器 `/tmp/run_tavily_acceptance_once.py`，先按交付时提供的SHA校验，再执行：

```sh
sudo sh -c 'cd /var/www/finance-daily/backend && nohup ./venv/bin/python -u /tmp/run_tavily_acceptance_once.py --run > /tmp/finance-tavily-acceptance-v1.log 2>&1 < /dev/null &'
```

后台命令不立即输出是正常的。查看：

```sh
tail -n 100 /tmp/finance-tavily-acceptance-v1.log
```

`completed_for_human_review` 只表示查询样本已跑完。需人工查看返回文章的日期、重要性、是否自动快讯/软稿/重复，以及正文摘录是否真实可用。搜索有结果而正文失败，应修读取适配或来源准入；不能据此判断搜索无效。此次没有测试宏观/大宗全覆盖、所有自选股、讨论源、生产搜索调度或分析写稿。
