# 前端单独发布（2026-10-29）

用户已返回服务器health：healthy、database=connected、scheduler=stopped、automation_paused=true。该响应证明健康和暂停，不单独证明所有v4文件已安装。前端安装器会额外逐字节核对stocks路由和watchlist_preparation源码，版本不符先停止。

前端源码与静态页面分开发布。本地已导出的Expo页面补上现有PWA后处理，32个文件，ZIP约2.8MB。不重新调用模型、采集或TTS。页面仍沿用项目现有API地址，未更换服务器。

## 安装器范围

- 只更新`/var/www/finance-daily/mobile/dist`和`/var/www/finance-daily/web`，两者须已存在，并在实际`nginx -T`输出中作为root出现。目录/目标路径有符号链接时拒绝。
- 同时核对暂停健康、两份后端源码指纹、静态归档完整清单与逐文件SHA256；默认只验证。
- 全部替换项先备份到`/var/backups/finance-daily/frontend-<UTC时间>`，记录原文件是否存在；先写静态资源，再写两处index。写入异常时按清单恢复原文件、删除本次新引入文件。
- 保留旧哈希资源和目录内其他文件，支持尚未刷新页面的客户端。不删除目录、不改Nginx配置、不重启服务，不操作后端、App数据库、密钥、暂停标记或另一项目。

## 本地验证

`tools/build_frontend_upgrade.py`对临时目录重建两份旧前端，并演练只验证不写入、缺Nginx根拒绝、未暂停拒绝、模拟写入失败后恢复、重复发布、新旧资源保留、另一项目和暂停标记保留。

PWA后处理后再次运行此前手机/桌面Playwright模拟添加自选股流程，生产API和外站请求均拦截；Browser插件不可用，因此沿用普通Playwright回退。通过后才交付。不是线上访问或实际新增股票采集验收。

## 使用

构建：`python tools/build_frontend_upgrade.py --assets <已测试Expo导出目录> --output <新的独立发布目录>`。不覆盖已有发布目录。工具需要同目录的`install_frontend_upgrade.py`和`install_paused_upgrade.py`；产物将后者作为source_installer.py一并携带，仅复用受限路径和原子写入函数，不运行源码安装入口。

上传ZIP到/tmp并解压后，`sudo python3 <解压目录>/install_frontend.py`只检查；输出`Frontend validation passed`和`Validation only. No files changed.`后，再用相同命令加`--apply`发布。无需恢复调度或调用模型。

完成后应在日常使用的网址刷新自选股页面，核对资料补采状态及维护暂停行为；不点击付费生成按钮。实际发布结果尚待用户回传。
