# v14：旧版口播叙事恢复与新一期资料验收

范围：合并v13之后的正式口播要求、编排取舍一致性、采集起止时间/App名单绑定及免费新资料检查。构建器接受精确v13归档指纹，并保留已确认v10/分配补丁的基线兼容；遇到未知服务器文件继续停止。源码及文档更新，前端和密钥不变。

当前未安装到服务器，没有新一期采集或模型结果。安装与公开资料验证都不恢复调度。新资料准备通过后才安排正式新报告及口播，旧历史试验不重跑。

## 安装

把finance-fresh-episode-20261030-v14.zip上传到服务器/tmp，按发布记录核对SHA256后执行：

```bash
python3 -m zipfile -e /tmp/finance-fresh-episode-20261030-v14.zip /tmp/finance-fresh-episode-upload-v14 &&
sudo /var/www/finance-daily/backend/venv/bin/python /tmp/finance-fresh-episode-upload-v14/finance-fresh-episode-20261030-v14/install_upgrade.py
```

看到验证通过后：

```bash
sudo /var/www/finance-daily/backend/venv/bin/python /tmp/finance-fresh-episode-upload-v14/finance-fresh-episode-20261030-v14/install_upgrade.py --apply --restart &&
curl -fsS --max-time 10 http://127.0.0.1:8000/health
```

期望服务healthy、数据库connected、automation_paused=true、scheduler=stopped。安装器会私有备份，只操作财经项目；冲突停止，不手动删除基线校验。

## 一次公开采集与免费检查

以下命令以nohup后台执行，SSH重连后可继续查日志；同一轮只启动一次。模型调用为0，但会访问公开新闻和行情来源及写私有资料缓存。现有失败来源暂停策略保留。

```bash
sudo sh -c 'cd /var/www/finance-daily/backend && nohup sh -c "./venv/bin/python -u -m app.radar_check --hours 72 --full-news && ./venv/bin/python -u -m app.selection_check && ./venv/bin/python -u -m app.fresh_input_check && ./venv/bin/python -u -m app.radar_check --saved-summary && ./venv/bin/python -u -m app.research_input_check" > /tmp/finance-fresh-episode-v14.log 2>&1 < /dev/null &'
```

启动命令立即无输出是正常现象。查进度：

```bash
pgrep -af '[a]pp.radar_check|[a]pp.selection_check|[a]pp.fresh_input_check|[a]pp.research_input_check'
tail -n 100 /tmp/finance-fresh-episode-v14.log
```

没有进程只说明已退出，需要看日志确认成功或失败；不要仅因此重新启动采集。所有步骤以&&串联，失败后不继续。新资料准备诊断有效期两小时，后续模型请求前仍需重新检查时间与名单。

材料质量按来源、发布时间、实读范围、重复/背景比例、研究缓存及行情截止检查；不为每股凑消息，也不把技术采集时间当成交时刻。正文非空不等于完整或事实已核实。单期新样本通过只能证明这一期流程和内容表现，不能证明预测效果或普适性。

付费分析/审查/口播次数和实际输入预算将在这一轮资料核对后明确，不在本命令启动，也不合成音频或发布App。
