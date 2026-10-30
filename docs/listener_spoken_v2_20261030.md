# 新版口播单次验收 v2

用户已回传v13口播素材分离、后台口吻检查及费用配置检查通过。尚未返回本轮安装器/独立健康JSON，不替其编造线上检查结果。相关新代码可用；自动任务未被本轮恢复。

本次得到用户同意，准备macro-spoken-listener-20261030-v2；不是重试旧付费输入。复用同一份人工修订历史报告，报告SHA保持08490408c4a0f7038621c98c48d7a6876b2358b9d1b22fbd7e7f922fe59e6db4。只变更为v13正式口播规则，输入4062字符，最多4000输出token，一次显式POST、零重试。没有附上人工口播示范让模型照抄，没有重新分析。

包finance-listener-spoken-20261030-v2.zip，SHA256 79dd08e3942ae2f27ca28fdea2ad1e9044e0c0a2ebe67816ddaf07aadc5ea855。
输入SHA256 172d03acfffa55729d33c46dfebb3e90880b15c749b9a7dbb165ec26fe7bbdee。

默认免费预览，绑定分析原稿、固定输入和生产源码。源码指纹与v13包核对通过；离线模拟原稿绑定、一次POST、重复拒绝通过。真实模型请求0；不会覆盖旧macro-spoken-20261029-v1结果或标记。

上传/tmp解压后先运行run_macro_spoken_once.py免费预览，正确后才执行--run --input-sha256加本次指纹。后台日志可写/tmp/finance-listener-spoken-v2.log。结果为backend/data/diagnostics/staged-programme/macro-spoken-listener-20261030-v2.json，.started保留防重复收费。

人工验收不再调用Claude：看开头是否有具体变化、是否形成连续主线、数字是否过密、后台规则是否仍被念出、是否保留事实与关键反方以及有用应对。相同历史底稿用于比较表达，不代表实时采集、自动分析或完整节目通过。没有音频、自动审查、重写、发布或恢复调度；实际费用以账户为准。
