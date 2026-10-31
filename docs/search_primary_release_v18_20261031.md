# v18合并安装与零网络诊断

本包合并此前尚未部署的来源、参与者讨论、主资料接入及阅读排序修改，不需要逐个安装前面的补丁。

- 文件：`finance-search-primary-20261031-v18.zip`
- SHA256：`7f509ba026ac0f3923140a32b8276ebf691263cf67543996130db2bdc7069a50`
- 源码提交：`6ed93c1`
- 源码/文档/失败URL清单97文件，734项离线回归通过。
- 精确注册基线及兼容版本的验证、冲突拦截、重复安装、配置/数据库/暂停标记/旧验收标记保留均在临时项目演练通过。另一个模拟项目保持原样。
- 只更新`/var/www/finance-daily`清单内文件并重启`finance-daily`；保留.env、模型、密钥、数据库、前端静态文件、Nginx及自动化暂停。未在用户服务器安装，也未执行付费验收。

## 1. 下载并上传

先从本次对话提供的本地文件链接下载ZIP，再通过腾讯云“文件管理”上传到服务器`/tmp`目录，文件名保持不变。服务器终端不能凭文件名读取你电脑里的下载文件。

## 2. 校验并仅验证安装条件

在腾讯云Ubuntu终端完整复制下方命令，不加提示符：

```bash
echo '7f509ba026ac0f3923140a32b8276ebf691263cf67543996130db2bdc7069a50  /tmp/finance-search-primary-20261031-v18.zip' | sha256sum -c - &&
python3 -m zipfile -e /tmp/finance-search-primary-20261031-v18.zip /tmp/finance-search-primary-upload-v18 &&
sudo /var/www/finance-daily/backend/venv/bin/python /tmp/finance-search-primary-upload-v18/finance-search-primary-20261031-v18/install_upgrade.py
```

正常结果包含`Source validation passed: 97 files`及`Validation only`。此步不修改项目。若出现指纹差异，保留完整错误供核对，不删除校验项或放行未知文件。

## 3. 应用合并更新

验证通过后执行：

```bash
sudo /var/www/finance-daily/backend/venv/bin/python /tmp/finance-search-primary-upload-v18/finance-search-primary-20261031-v18/install_upgrade.py --apply --restart
```

正常结果包括私有备份路径，以及`Service healthy; database connected; automation paused; scheduler stopped`。安装本身不调用模型或采集新闻。

## 4. 查看健康状态和实际搜索配置

```bash
curl -fsS --max-time 10 -w '\n' http://127.0.0.1:8000/health &&
cd /var/www/finance-daily/backend &&
sudo ./venv/bin/python -u -m app.primary_collection_check
```

最后一条仅查看本地配置和App自选股并生成检索计划，HTTP/模型/TTS请求均为0。回传输出中的`search.enabled`、`search.configured`、`watchlist_status`和`watchlist`即可；程序不会打印搜索密钥。

这一步用于确认用户真实服务器配置，不把“有配置”当联网验通。后续才决定服务器主动搜索入口和一次受控联合采集。此次不运行旧付费试验、报告生成或TTS，也不恢复调度。

本地材料回放范围及尚未通过项目见[本轮联合验收说明](search_primary_joint_check_20261031.md)。不要把29份正文和119条发言当作全新消息或充分覆盖证明。
