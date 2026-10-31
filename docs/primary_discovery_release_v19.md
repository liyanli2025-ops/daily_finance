# v19：部署完整任务驱动的采集验收入口

基于用户已成功安装的v18原始包（SHA `7f509ba026ac0f3923140a32b8276ebf691263cf67543996130db2bdc7069a50`）。只更新6个运行/说明文件，不覆盖服务器测试文件、前端、nginx、数据库、密钥或其他项目。

运行逻辑见[模型主导采集](model_led_collection_20261031.md)。这个版本提供正式循环和受控试验入口，不代表资料质量已通过或已恢复自动化。

## 安装并免费准备

下载交付的 `finance-model-led-20261031-v19.zip`，通过腾讯云文件管理上传到 `/tmp`，按交付说明校验SHA后执行：

```sh
python3 -m zipfile -e /tmp/finance-model-led-20261031-v19.zip /tmp/finance-model-led-upload-v19 &&
sudo /var/www/finance-daily/backend/venv/bin/python /tmp/finance-model-led-upload-v19/finance-model-led-20261031-v19/install_upgrade.py &&
sudo /var/www/finance-daily/backend/venv/bin/python /tmp/finance-model-led-upload-v19/finance-model-led-20261031-v19/install_upgrade.py --apply --restart &&
cd /var/www/finance-daily/backend &&
sudo ./venv/bin/python -u /var/www/finance-daily/tools/run_primary_collection_once.py
```

前两步先检查，再应用并备份，保持维护暂停。最后一步仅从App读取实际名单、读取配置并生成试验输入，不搜索、不调用模型/TTS。输出包含实际模型/路由、输入SHA和2小时有效期；不要把任何.env内容或密钥发到聊天。

## 免费预检展示的试验上限

仅当随后明确执行 `--run --input-sha` 时：最多4次模型POST，每次最多80,000输入字符、3,000输出token；最多8次basic搜索、参考8积分；最多10个公开正文URL，每URL至多3个含跳转GET。字符不是token，不能据此承诺美元账单。沿用实际analysis路由与推理配置，零自动重试/整篇修稿/语音/发布。

候选目录和相同正文范围只在每次输入中提供一次，不把此前所有重复工具信封一遍遍塞进去；原始回执仍完整保存，不删文章或截去反证来满足预算。

这不是每天正式收集的默认预算，也不是文章数量目标。输入或请求不足以研究完整市场时如实保存缺口，不能称覆盖充分。

## 收费执行的保护（先审阅预检，再执行）

`--run`必须提供对应输入SHA。输入超过2小时、App名单/模型路由/共享研究要求变化时拒绝执行。固定试验marker `backend/data/diagnostics/model-led-primary-v1.started` 独占创建，断线或重复命令不再收费；不删除旧marker重跑。

收费runner是独立进程，保留生产维护暂停文件，在本进程临时启用搜索并将本试验搜索上限设为8，不更改.env或运行中的服务。模型使用单独的零重试HTTP调用，以便正式服务继续禁止模型请求；这是显式试验通道，不能用于恢复自动任务或无预算批量生成。每次模型请求仍写用量账本。

原始输入、工具/候选/正文范围、模型回复及事件/取舍底稿逐步保存到私有路径。资料以准备时点为截止、不是运行结束时的同步快照。结果保存在 `backend/data/radar/cache/model-led-primary-v1.result.json`，正文在结果中给出的episode工作区，沿用24小时清理；marker保留阻止重复收费。

后台执行的命令由预检后按实际输入指纹给出。当前安装命令不含收费参数，不会自动开始试验，也不跑上一轮Tavily接口样本。

## 验收标准

先看是否取得重要事件的可用正文、是否错配公司/市场、是否漏掉重要外盘/国际/行业事项、是否区分原披露/转述/猜测、是否合并同题但保留新增事实和反方，以及遗漏是否真实说明。`partial_materials_for_human_review`、`insufficient_body_evidence`和`failed_no_retry`均不能当合格节目。

没有新搜索、真实模型取材或整期音频验收通过的记录。模拟测试及安装演练不能代替这些质量验证。
