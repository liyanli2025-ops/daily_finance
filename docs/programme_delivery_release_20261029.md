# v9合并交付与下一次验收

## 这次交付什么

合并v8之后的两项真实取材修复：锂盐文章的邻近需求限定不再被远处低基数说明挤掉；综合早餐优先读已有股、债、汇表现并跳过明确课程广告。原文不增加、预算不提高、未知上下文不冒充已读。

加上新版programme口播的单次验收入口 app.programme_acceptance。编排与口播在同一次写稿请求完成。正式生产和这个工具共用prepare_script，先清理及分段，再保存准确正文；编排不进入语音。没有新增任何自动收费步骤。

526项后端测试通过（16.980秒），其中8项验证新工具免费准备、固定报告与暂停、输入及源码变化拦截、原始回复保留、超时、路由拒绝与稳定试验标记防重复；均为模拟HTTP。未调用真实Claude或TTS。

本地当前正式提示词重建4722字符，输入SHA为927379a4e6c012bb3e03f4b6853db9105a766b39a5e62134d948cc5342f2e12d。不是token数或账单。正式服务器仍需免费预检，不用这个数字替代服务器检查。

## 下载并安装

部署包名：finance-programme-delivery-20261029-v9.zip。将其上传腾讯云文件管理的 /tmp；其他项目文件不操作。具体SHA见交付消息，不跳过校验。

Ubuntu终端（先完成部署包SHA校验，再执行）：

```bash
python3 -m zipfile -e /tmp/finance-programme-delivery-20261029-v9.zip /tmp/finance-programme-delivery-upload-v9 &&
sudo /var/www/finance-daily/backend/venv/bin/python /tmp/finance-programme-delivery-upload-v9/finance-programme-delivery-20261029-v9/install_upgrade.py &&
sudo /var/www/finance-daily/backend/venv/bin/python /tmp/finance-programme-delivery-upload-v9/finance-programme-delivery-20261029-v9/install_upgrade.py --apply --restart
```

校验遇到未知服务器版本会停止，不删除或修改manifest来硬装。安装器私有备份，只替换列明文件，保留.env、数据库、暂停标记、前端静态目录及其他项目。发布器新增精确v8基线，来自已交付zip与Git原始文件指纹，不接受任意差异。

## 安装后的免费检查

```bash
curl -fsS --max-time 10 http://127.0.0.1:8000/health; printf '\n'
cd /var/www/finance-daily/backend && sudo ./venv/bin/python -u -m app.programme_acceptance
```

health应为healthy/database connected/automation_paused true/scheduler stopped。第二条仅核对已有报告记录、固定人工修正版、暂停及当前正式提示词，打印free_preview、输入指纹和HTTP=0；不采集、不生成报告/口播、不调用模型，也不恢复定时任务。不要运行旧v7口播工具，它与旧付费结果永久保留。

## 什么时候才需要一次模型调用

免费检查通过后，若决定验收新版实际写稿，需要明确使用--run并填写该次免费预览输入指纹。这是另一项收费动作，本轮未执行，不因安装或免费检查而自动启动。最多一次POST，局部effort none，8000输出token上限、零重试、零自动审查/修稿/TTS/发布。不承诺最高实际账单；输入与输出都可能计费。

试验稳定ID programme-report-20261029-v1，结果在backend/data/diagnostics/staged-programme/。无论超时、格式失败、源码变化，已有.started不能删除以重扣；修改提示词也不绕过该次试验标记。

人工验收要同时看编排与整期正文：是否真正舍弃次要内容、主线有没有推进、已有判断与最强反方是否保留、是不是仍在讲模型与纠错纪律、是否按原版通勤节目自然讲清交易意义。JSON正确与逐字引用只是格式和来源定位，不代表分析或听感合格。

使用的仍是10月29日07:32历史人工修正版报告。因此这一次只能检验当前口播编排和写作，不能证明新版上游选材、全池补查、实时分析、预测胜率或音频通过。上游需另用新合格材料评估，不能拿本次结果替代整条链路验收。
