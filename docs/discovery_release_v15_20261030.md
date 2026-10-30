# v15合并更新与免费回放

包括v14之后的全市场入口、事件占位、明确生成稿识别，以及全池发现目录和按字符预算初读。后端源码/文档更新；默认暂停、零重试、不自动整篇修稿。完整新资料与模型测试仍未完成。

先把finance-discovery-budget-20261030-v15.zip上传到服务器/tmp。校验指纹后验证安装包：

```bash
python3 -m zipfile -e /tmp/finance-discovery-budget-20261030-v15.zip /tmp/finance-discovery-budget-upload-v15 &&
sudo /var/www/finance-daily/backend/venv/bin/python /tmp/finance-discovery-budget-upload-v15/finance-discovery-budget-20261030-v15/install_upgrade.py
```

验证通过后应用并看健康：

```bash
sudo /var/www/finance-daily/backend/venv/bin/python /tmp/finance-discovery-budget-upload-v15/finance-discovery-budget-20261030-v15/install_upgrade.py --apply --restart &&
curl -fsS --max-time 10 http://127.0.0.1:8000/health
```

保持automation_paused=true、scheduler=stopped。只操作财经目录并私有备份；未知文件冲突停止，不放宽校验。其他项目、.env、数据库和前端静态文件保留。

安装后回放已有快照即可，不重新采集、不调用模型或音频：

```bash
cd /var/www/finance-daily/backend &&
sudo ./venv/bin/python -u -m app.selection_check --restore-market-events > /tmp/finance-discovery-v15.log 2>&1 &&
sudo python3 - <<'PY'
import json
from pathlib import Path
p=Path('/var/www/finance-daily/backend/data/radar/selection-replay.json')
d=json.loads(p.read_text())
for k in ('snapshot_collected_at','candidate_count','discovery_catalogue','initial_budget','market_coverage'):
    print(k+':',json.dumps(d.get(k),ensure_ascii=False))
print('仅回放已有资料，不代表当前新闻时效合格；未调用模型。')
PY
```

目录条目与正文初读份数分别报告。逾时旧快照可回放，但不能冒充新实时节目；正式付费前仍核对当前App名单、资料时效与总请求预算。安装包不更新独立tools验收脚本；旧单独验收脚本不要直接套用新目录，后续提供匹配版本的单次预览。
