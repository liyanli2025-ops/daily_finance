# 分析与口播质量修正合并更新（2026-10-29）

## 范围

合并从已确认 v10 到当前源码的 backend/app 与 docs 改动：研究来源/阅读视图身份、正文阅读分配、费用输入展示压缩、条件性公告背景归类、经营变化原句定位、RSI数值分类、判断与推翻条件并列诊断、口播原句对照及免费审查回放。没有改变模型/密钥，未安装前端静态资源，不触碰其他项目。

真实报告试验已完成但质量未通过，本包不包含付费生成操作。报告证据使用与口播保真新规则尚未经过真实模型验证；离线测试不代表分析专业性或听感达标。

## 基线和安装行为

只从两个用户已经成功安装的不可变包恢复基线：
- finance-research-input-20261029-v10.zip，SHA256 94554a1b14e16fa70f91cb5290571902a9c9962964bfe272f07c7e9d63b7efb5
- finance-research-allocation-fix-20261029.zip，SHA256 c2f08e103293aea7a51a029d31c62a4b124c95354705de2edf674f57fca9e4e7

构建器 tools/build_quality_consolidated.py 校验两包及各文件，再计算当前源码差异。每个文件只允许已确认旧指纹或本包新指纹；遇未知修改停止，不能绕过。测试文件不部署。要求现有维护暂停标记。

安装器默认只校验；--apply --restart备份后更改清单内文件，仅重启受systemd托管的finance-daily；健康检查要求数据库连接、automation_paused=true、scheduler=stopped。异常回滚代码。配置、数据库、自选股、旧付费开始标记及其他项目保留。未在真实服务器代为安装。

## 用户操作顺序

下载 finance-quality-consolidated-20261029-v11-r2.zip 上传服务器/tmp，使用交付消息中的SHA256校验并解压到/tmp/finance-quality-consolidated-upload-v11-r2。
先运行解压目录 finance-quality-consolidated-20261029-v11-r2/install_upgrade.py（不带参数），通过后同脚本加 --apply --restart。

安装后只运行：

```bash
curl -fsS --max-time 10 http://127.0.0.1:8000/health
cd /var/www/finance-daily/backend && sudo ./venv/bin/python -u -m app.selection_check > /tmp/finance-v11-selection.log 2>&1 && sudo ./venv/bin/python -u -m app.research_input_check > /tmp/finance-v11-research.log 2>&1
```

两项CLI只回放已有新闻/研究缓存；若缓存过期、缺失或数据不足，返回对应缺口，不据此判来源永久失效，也不自动补采或调用模型。selection_check会更新自身诊断，不写App报告。截面可能仍为10月29日早间，不称当前实时信息。

不要运行旧run_real_report_once --run、programme_acceptance --run、trigger-report，不删除任何started标记，不恢复自动任务。本次安装不能证明模型输出质量合格。

## 下一步

先收集本次健康检查和免费回放结果。确认运行版本与输入后，必要的单次真实语义验收必须说明增量和预算；不启动自动审稿/整篇修稿/口播/TTS连环调用，不拿同一未修正输入重扣费。分析稿达到可用标准后，再验收口播和音频。已完成的真实试验与未通过原因见analysis_trial_review_20261029.md。
