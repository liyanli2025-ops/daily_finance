# 分析、口播与费用控制合并部署 v12

本包接续服务器已确认安装的v11-r2，合并后续已推送改动。不包含模型验收或音频生成，自动任务保持暂停。此前578项离线测试通过，不等于真实分析/口播质量通过。

## 改动

- 每个逻辑模型调用默认零自动重试；报告审查不通过默认留稿待编辑，不整篇付费修稿再审。单次失败也可能计费；整期仍有多个模型阶段。
- 截断时留存可见正文，明确不可发布，不保存隐藏思考或认证头。
- 报告、摘要、判断元数据、口播同步归因与期限：经营解释不冒充股价原因，历史相对弱势不冒充持续卖压，短线反弹不强制套用中期趋势确认条件。
- 元数据引用的N:前缀只对精确命中本期已知ID做无损规范化，未知引用仍拒绝。

不改密钥、模型、数据库、自选股、前端或其他项目；只重启finance-daily。安装前私有备份，精确指纹校验遇未知改动停止。保留旧付费试验标记。v11-r2归档SHA256为143ec09bcfb285ebc6208f31760804a7b7f7f5267ee0ab163316a8427e8bd8a8；由构建器核对归档与内层各文件，不直接信任服务器自报的新指纹。

## 安装顺序

下载交付的finance-editorial-cost-20261029-v12.zip，用腾讯云文件管理上传到/tmp，先核对发布消息中的SHA256。然后在服务器Ubuntu终端执行：

```bash
python3 -m zipfile -e /tmp/finance-editorial-cost-20261029-v12.zip /tmp/finance-editorial-cost-upload-v12 &&
sudo /var/www/finance-daily/backend/venv/bin/python /tmp/finance-editorial-cost-upload-v12/finance-editorial-cost-20261029-v12/install_upgrade.py &&
sudo /var/www/finance-daily/backend/venv/bin/python /tmp/finance-editorial-cost-upload-v12/finance-editorial-cost-20261029-v12/install_upgrade.py --apply --restart
```

## 免费验证

```bash
curl -fsS --max-time 10 http://127.0.0.1:8000/health
printf '\n'
```

应为healthy、database connected、scheduler stopped、automation_paused true。然后：

```bash
cd /var/www/finance-daily/backend && sudo ./venv/bin/python - <<'PY'
from app.config import settings
print('失败后自动重试次数:', settings.model_http_retries)
print('自动整篇修稿:', settings.report_auto_repair_enabled)
assert settings.model_http_retries == 0, '存在显式配置覆盖，先核对，不运行生成'
assert settings.report_auto_repair_enabled is False, '存在显式配置覆盖，先核对，不运行生成'
print('费用配置检查通过；未调用模型。')
PY
```

不要打印.env。安装保持配置不变；若旧环境显式设置了这些新开关，检查会提示，而不会偷偷覆盖偏好。

已通过的selection_check/research_input_check不为本次提示词和费用开关再次采集或重复运行；本包不改变上游取材算法。此次只需回传安装、健康和上述两项开关结果。不要执行旧--run试验、trigger-report、恢复调度或TTS。

## 后续

安装不代表质量验收。下一次真实验证应使用不同主题、明确输入及一次请求预算，先看分析是否改善，再决定是否付费转口播；不得重跑宁德旧试验来凑通过。完整音频与每日流程仍待验收。
