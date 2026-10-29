# v13口播听感更新：从已确认v12升级

2026-10-30。本包包含正式口播文风、素材与显式编辑备注分离、编排引用限制及后台口吻拦截。此前582项离线测试已通过；人工示范见macro_listener_sample_20261029.md。真实模型新文风和音频仍未验收，不能把人工示范当自动产出。

服务器已确认安装v12，费用开关为零重试、禁自动整篇修稿，自动任务暂停。构建器以v12不可变包54fd66764715cb8edbbfed206a6fb13529f7c317f22326815eaeb9787a504022恢复精确指纹，不接受任意服务器差异。配置、模型、密钥、数据库、自选股、付费标记及其他项目保留。前端不在本次更新范围。

## 构建记录

源码9ecceb7，44个运行/文档文件，不部署测试文件。包SHA256：0648cff8973271df55c233aeaf8de8e3a42b31a6be5725fd04ed53490f9ab32b。
本地演练通过v12及旧基线安装、未知冲突和缺少暂停阻断、重复安装、配置/数据库/旧付费标记/其他项目保留。没有真实服务重启或模型调用；线上重启仍由安装器健康检查确认。

## 上传与安装

将finance-listener-flow-20261030-v13.zip上传到/tmp。先用交付消息的SHA256校验，再执行：

```bash
python3 -m zipfile -e /tmp/finance-listener-flow-20261030-v13.zip /tmp/finance-listener-flow-upload-v13 &&
sudo /var/www/finance-daily/backend/venv/bin/python /tmp/finance-listener-flow-upload-v13/finance-listener-flow-20261030-v13/install_upgrade.py &&
sudo /var/www/finance-daily/backend/venv/bin/python /tmp/finance-listener-flow-upload-v13/finance-listener-flow-20261030-v13/install_upgrade.py --apply --restart
```

未知文件差异停止，不能绕过。安装前私有备份，只重启finance-daily；运行时健康检查要求数据库连接、automation_paused=true、scheduler=stopped。

## 免费运行检查

```bash
cd /var/www/finance-daily/backend && sudo ./venv/bin/python - <<'PY'
from app.config import settings
from app.services.spoken_editing import spoken_input
from app.services.spoken_programme import delivery_leaks
sample = '判断：需求未明。\n## 编辑说明（不朗读）\n后台备注。\n## 应对\n反弹延续时调整判断。'
parts = spoken_input(sample)
assert '需求未明' in parts['analysis']
assert '反弹延续' in parts['analysis']
assert '后台备注' not in parts['analysis']
assert '后台备注' in parts['editor_notes']
assert delivery_leaks('这是报道中有归属的说法。')
assert not delivery_leaks('据报道，机构减持了部分债券。')
assert settings.model_http_retries == 0
assert settings.report_auto_repair_enabled is False
print('口播素材与备注分离：通过')
print('后台口吻检查：通过')
print('自动重试：0；自动整篇修稿：关闭')
print('本次仅本地检查，未调用模型、采集或语音。')
PY
```

这些检查不代表听感通过。不要重新运行旧macro-spoken --run、恢复调度或启动音频。旧包固定输入和源码指纹不应改写绕过限制；新文风验证需要新固定输入与明确预算。

## 后续顺序

确认本包安装及免费检查，然后在明确预算下做一次正式口播文风验证。保留事实/关键反方/期限，同时检查叙事、报数密度、后台话语和行动含义。稿件听感合格后再做音频试听，不重复付费重跑分析，不将单主题验收当作整期端到端通过。
