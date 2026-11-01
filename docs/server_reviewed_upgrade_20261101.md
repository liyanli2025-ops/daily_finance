# 腾讯云服务器实际版本合并更新

本次更新基于用户上传的 `SERVER-MANIFEST.json` 和11个文件核对，包括10个差异文件及依赖清单。服务器运行项目；GitHub单独备份同版源码，两者不互相作为安装前提。

## 核对结论

- config、ai_analyzer、episode_research、episode_workspace、model_gateway 五项仅 CRLF/LF 换行不同，不存在内容冲突。
- README、配置示例、primary_discovery、web_research、交接记录五项是服务器较旧内容。源码保留服务器的缓存复用、网页失败止损、暂停、名单核对和证据约束，并叠加通用收集与阅读改进。
- 服务器缺少 GitHub 基线已有的 search_objectives.py。仅打包 Git diff 会漏掉它，新包显式包含该文件及 requirements-extraction.txt。
- requirements.txt 与仓库仅换行不同。本包只核验它，不覆盖或安装依赖。
- 原文件缺失的 generic_extraction.py、AGENT_HANDOVER.md 在包中补入。测试代码保留在源码/Git备份，不写入生产目录。

这些是源码比较结论，不代表应用测试或真实取材已通过。开发环境未运行测试、编译、lint、安装演练或真实模型/搜索/TTS。

## 上传后首先执行

上传 `daily-finance-server-upgrade-v21.zip` 到服务器 `/tmp`，执行：

```bash
(
set -e
python3 -m zipfile -e /tmp/daily-finance-server-upgrade-v21.zip /tmp
/var/www/finance-daily/backend/venv/bin/python \
  /tmp/daily-finance-server-upgrade-v21/install_upgrade.py \
  --project /var/www/finance-daily
)
```

默认只读验证载荷、Python语法、实际服务器文件基线、依赖清单和既有暂停标记，成功显示 `Source validation passed`。不访问GitHub，不启动服务或修改生产文件。任何不匹配都停止，回传具体文件名，不跳过保护。

## 验证通过后应用

```bash
sudo /var/www/finance-daily/backend/venv/bin/python \
  /tmp/daily-finance-server-upgrade-v21/install_upgrade.py \
  --project /var/www/finance-daily --apply --restart
```

只操作已有 `finance-daily` 服务：先确认托管服务有效，备份受影响文件、现有配置及SQLite一致性快照，再停止该服务、应用文件并启动。健康检查必须同时满足数据库连接、维护暂停、调度器停止。应用或健康检查失败时自动恢复原代码并启动原服务；保留私有备份目录供人工核对。未做数据库迁移，回退不会用快照覆盖运行中的数据库。

不修改 `.env`，不删除任何试验marker或暂停标记，不调用模型/搜索/TTS，不自动安装提取库。显式旧配置仍有效，例如 `.env` 中的搜索上限4不会被偷偷改为24。

## 应用后的免费检查

```bash
cd /var/www/finance-daily/backend
venv/bin/python -m app.discovery_budget_check --watchlist-count 4
venv/bin/python -m app.reading_acceptance
venv/bin/python -m app.primary_discovery_check
```

预算检查的4是给定规模；最后一个命令才读取当前App真实名单。提取依赖检查退出码2表示未就绪，记录实际原因再处理，不代表应用需要重复安装。执行期间没有真实模型、搜索、取材HTTP或TTS；健康接口检查是本机现有服务查询。

安装后的版本、依赖可加载性、App名单和取材质量分别验收。完整模拟回归应在隔离副本运行一次；生产环境不批量运行测试。新日期真实取材仍需要审阅收费入口及实际预算后单独执行。

## GitHub备份与复现

开发分支 `improve/reading-acceptance` 保存相同功能源码和更新准备工具。当前连接账号VinkyDev推送曾返回403，未成功备份；没有写权限时不宣称GitHub已更新，不向聊天发送token。

`tools/prepare_server_reviewed_upgrade.py` 使用实际服务器快照生成本包，不再要求下载原始v20包。包内清单记载最终源码提交、服务器快照摘要及逐文件基线/新哈希；未审阅的新服务器差异会阻止安装。准备脚本只生成压缩包，不执行应用、测试、安装或联网。

旧 `daily-finance-update.bundle` 是有Git基线要求的增量Git备份格式，不能直接安装生产源码；之前的42文件包是核对材料，不再作为安装入口。本次更新没有Skill调用接口变更。
