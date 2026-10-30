# v16 新闻来源和个股范围安装检查

源码db82d08，合并包finance-source-focus-20261031-v16-r2.zip，71个运行/文档文件。SHA256：

```text
97e034e4dfebb6badfbdce94e4ac0cace167979115ececa39858ec2f129099d0
```

630项离线回归通过。构建器对精确v15、v10及allocation基线进行冲突阻止、维护暂停、重复安装、数据库/.env/付费标记/其他项目保留演练。第一份本地v16构建因Windows沙箱临时目录权限未完成，不交付；交付的是非受限环境演练完成的v16-r2。没有连接或修改生产服务器。

## 安装

先用腾讯云文件管理上传这个zip到/tmp。以下命令在腾讯云Ubuntu终端执行，不在浏览器地址栏执行。校验或源码基线检查失败即停止，把输出返回，不修改manifest跳过保护。

```bash
echo '97e034e4dfebb6badfbdce94e4ac0cace167979115ececa39858ec2f129099d0  /tmp/finance-source-focus-20261031-v16-r2.zip' | sha256sum -c - &&
python3 -m zipfile -e /tmp/finance-source-focus-20261031-v16-r2.zip /tmp/finance-source-focus-upload-v16-r2 &&
sudo /var/www/finance-daily/backend/venv/bin/python /tmp/finance-source-focus-upload-v16-r2/finance-source-focus-20261031-v16-r2/install_upgrade.py &&
sudo /var/www/finance-daily/backend/venv/bin/python /tmp/finance-source-focus-upload-v16-r2/finance-source-focus-20261031-v16-r2/install_upgrade.py --apply --restart
```

应出现Service healthy、automation paused、scheduler stopped。不改变模型、凭据、App数据、nginx或其他项目，不恢复定时报表/采集。

## 只检查新增公开入口

先免费预览（不联网）：

```bash
cd /var/www/finance-daily/backend && sudo ./venv/bin/python -m app.reference_source_check
```

再执行一次公开网络测试（无LLM/TTS费用）：

```bash
sudo sh -c 'cd /var/www/finance-daily/backend && nohup ./venv/bin/python -u -m app.reference_source_check --run > /tmp/finance-reference-source-check.log 2>&1 < /dev/null &'
```

后台启动没输出正常。稍后查看：

```bash
pgrep -af '[a]pp.reference_source_check'
tail -n 120 /tmp/finance-reference-source-check.log
```

结果在backend/data/diagnostics/reference-source-check/summary.json。每家入口有独立结果和.started标记，重复执行不重复请求已有/中断记录。最多8次HTTP，不做全量新闻重采，不生成报告或口播。FastBull/TechCrunch只验收公开正文样本，MKTNews只记快讯，Google News只记目录；不会将搜索标题当事实证据。

具体研读、可用性、个股规则与剩余缺口见[source_reference_review_20261031.md](source_reference_review_20261031.md)。尤其动态关系表、完整事件发现/补读与节目质量仍未全部验收，不能据此宣布项目可恢复自动生成。
