# 搜索复核成功后的取材续验（2026-11-01）

## 已有现场证据

用户已安装v22的两个源码文件，11个新离线用例全部OK；两条原模型响应在新解析器下都可离线读取。随后用户明确执行一次搜索诊断：13:11:54结束，Tavily HTTP200、返回6条，模型/正文/TTS均0，维护暂停保留。

同一查询及其他参数保留，诊断请求去除了同时发送的 `time_range`。成功支持修订请求在该时刻可用；旧HTTP400没有保存服务商错误原文，不能据此断言400的唯一原因。未读取正文，6条搜索目录质量和自主覆盖尚未验收。

旧诊断入口只保存了数量，未保存6条结果明细。这些明细无法从数量恢复，本轮不重新执行该诊断。已修改诊断脚本，未来成功时保留带时间的标题、URL、摘要及日期提示。它们仍是目录，不当正文证据。

## 新入口如何续验

`tools/continue_progress_collection.py`复用现有进展驱动入口，兼容已部署v21+v22源码，不新增生产运行文件、不修改.env、不改服务或正式venv。

默认只免费预览。它核对原失败的输入/开始标记/结果，以及成功搜索诊断的输入/开始标记/HTTP200结果，确认账号、源码、配置、原查询及修订参数相符。只接续本次“首次HTTP400、无候选/正文、随后JSON错误”的已审阅失败；有已存正文的其他失败不能误用此入口重建。

旧结果、开始标记和账号停用文件不删除、不覆盖。续验记录放在原任务下的 `continuation-after-search-check` 子目录；它是带修复与成功复核依据的一次续验，不是改trial名称盲目重试。它按真实用量扣除原失败与单次搜索诊断，预览展示的预算是**剩余预算**。

当前已知用量：模型2次、累计输入35266字符、预留输出6600 token；失败搜索1次、成功诊断1次；正文0。配置未变时，剩余为：

- 累计模型输入最多1,964,734字符。
- 累计预留输出最多113,400 token；当前单次3300时最多容纳34次新请求，非固定轮次要求。
- 新搜索最多22次，和前两次合计不超过原24次。
- 新URL读取仍最多64次，额外本地补读仍最多96000字符。
- 时长扣除此前两段实际运行时间，排除等待用户操作的时间；精确秒数以免费预览为准。
- .env若配置了更紧边界或可选紧急次数上限，取更紧的剩余边界。预算不足就停止，不偷偷重置或扩充总量。

基于HTTP200证据，对匹配的搜索账号只在这个独立进程中允许使用修订请求。其他来源的停用记录照常生效；原账号停用记录若出现新的失败或任一证据改变，后续请求会停止。普通服务和旧入口仍暂停，不把本次诊断当成全局恢复。

准备与显式执行分别绑定原始输入、路由、实际App名单、两份脚本、源码/配置及复核文件指纹；每次模型/网络入口继续检查。正文区间、完整响应范围、未解决任务继续保留；底稿导出包含本段及加上历史用量后的累计数。没有报告、音频或App发布。

## 一次上传，先免费检查

将 `daily-finance-revalidated-collection-v1.zip` 上传到服务器 `/tmp`，执行：

```bash
(
set -e
python3 -m zipfile -e /tmp/daily-finance-revalidated-collection-v1.zip /tmp
cd /var/www/finance-daily/backend
sudo env PYTHONPATH=/tmp/finance-reading-deps.xiZUZG \
  venv/bin/python -m unittest discover \
  -s /tmp/daily-finance-revalidated-collection-v1/backend/tests \
  -p test_search_revalidated_continuation.py
sudo env PYTHONPATH=/tmp/finance-reading-deps.xiZUZG \
  venv/bin/python /tmp/daily-finance-revalidated-collection-v1/tools/continue_progress_collection.py
)
```

本段没有安装、重启或收费请求。7个新用例检查预算扣减、账号/指纹绑定、新失败撤销许可和其他来源保护，尚未在本环境运行。临时依赖目录不存在、用例或复核失败时停止，回传输出，不跳过校验或删除旧marker。

## 明确执行及导出

接受免费预览展示的实际剩余用量后，使用该次SHA，以下占位符需替换才执行：

```bash
cd /var/www/finance-daily/backend
sudo env PYTHONPATH=/tmp/finance-reading-deps.xiZUZG \
  venv/bin/python -u /tmp/daily-finance-revalidated-collection-v1/tools/continue_progress_collection.py \
  --run --input-sha '替换为本次免费预览的input_sha256'
sudo venv/bin/python /tmp/daily-finance-revalidated-collection-v1/tools/continue_progress_collection.py \
  --export-review /tmp/daily-finance-continued-review.zip
```

真实执行消耗模型与搜索额度，字符、token预留都不是金额承诺。预览有效2小时，失效或配置/名单变化需重新免费准备。执行可能持续数分钟，不因暂时没输出重复启动。中断或失败先导出，续验开始标记不删除。导出目标如已存在不覆盖，包里不包含.env、密钥、准备输入或生产数据库。

本轮只审阅现场回执、修改/审阅源码及打包/备份；未运行应用测试、入口、项目收费模型/搜索或正文HTTP，未部署服务器。CLI不被现有Skill调用，无Skill接口变更。
