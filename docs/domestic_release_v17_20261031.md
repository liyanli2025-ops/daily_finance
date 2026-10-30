# v17 国内扩源合并安装和无模型检查

合并包包含v16来源和个股范围修改，不必先装v16。源码be25489，74个运行/文档文件。接受经核验的v15、v16及原构建器确认的v10/分配修复文件指纹；未知改动停止。安装演练覆盖两版基线、冲突阻止、暂停与数据库/.env/旧扣费标记/其他项目保留、重复安装。

文件finance-domestic-sources-20261031-v17.zip，SHA256：

```text
2f780dc24b2082f84690827c210b0d5d8a7c41530f9ac5ff16cc90cc9ccbf9a0
```

先通过腾讯云文件管理上传到/tmp，再在Ubuntu终端执行：

```bash
echo '2f780dc24b2082f84690827c210b0d5d8a7c41530f9ac5ff16cc90cc9ccbf9a0  /tmp/finance-domestic-sources-20261031-v17.zip' | sha256sum -c - &&
python3 -m zipfile -e /tmp/finance-domestic-sources-20261031-v17.zip /tmp/finance-domestic-upload-v17 &&
sudo /var/www/finance-daily/backend/venv/bin/python /tmp/finance-domestic-upload-v17/finance-domestic-sources-20261031-v17/install_upgrade.py &&
sudo /var/www/finance-daily/backend/venv/bin/python /tmp/finance-domestic-upload-v17/finance-domestic-sources-20261031-v17/install_upgrade.py --apply --restart
```

预期Service healthy、automation paused、scheduler stopped；没有生产服务器回传前不宣称安装完成。若校验/基线失败，返回错误，不修改manifest跳过保护。

## 国内入口检查

先预览，不联网：

```bash
cd /var/www/finance-daily/backend && sudo ./venv/bin/python -m app.reference_source_check --group domestic
```

再后台执行一次公开采集检查，无模型费用：

```bash
sudo sh -c 'cd /var/www/finance-daily/backend && nohup ./venv/bin/python -u -m app.reference_source_check --group domestic --run > /tmp/finance-domestic-source-check.log 2>&1 < /dev/null &'
```

后台命令无输出正常。稍后查看：

```bash
pgrep -af '[a]pp.reference_source_check'
tail -n 120 /tmp/finance-domestic-source-check.log
```

结果backend/data/diagnostics/reference-source-check/summary-domestic.json；兼容summary.json为最后一次运行结果。三家各最多1列表+2正文，共最多9次HTTP，失败无重试，开始标记防重复请求。不生成分析/口播/音频、不写App、不恢复调度。媒体抽样不代表全天稳定、全量覆盖或事实独立核验。

新增入口是澎湃财经、钛媒体最新、财经网滚动。Google News和MKTNews仍只属于上一轮发现/快讯检查；这次不顺带重复海外测试。完整参考出处、正文样本与未接入第一财经头条的原因见[国内来源研读记录](domestic_sources_provenance_20261031.md)。

635项完整离线回归通过。整期选材、动态重要同业名单、关键补读、分析和口播质量尚未全部通过，不重跑旧付费trial。
