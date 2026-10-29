# 宏观主题人工修稿后的口播验收准备

分析原试验macro-transfer-20261029-v1已付费完成但仍需编辑，不重跑。新增完整人工底稿见macro_transfer_edited_report_20261029.md，摘要/核心观点/decision_notes见macro_transfer_edited_metadata_20261029.json。仅编辑原材料支持的内容，保留偏谨慎的方向；修正融资成本泛化、AI需求范围、上涨识别定价原因、消息前价格与预期等问题。不将人工修稿伪装为模型自动通过。

## 本次范围

试验macro-spoken-20261029-v1，使用正式spoken_prompts及programme交付格式；只把上述完整底稿转成一个自然口播主题，不作为整期20分钟节目。编排可以压缩数字和重复边界，但必须保留主线、理由、有用安排及真正改变含义的反方/条件。不要只验收JSON格式，要人工判断是否仍像读报告、反复讲核验规则或缺乏决策含义。

默认免费，输入4447字符，最多4000输出token。显式--run且输入指纹匹配才发送一次POST，零自动重试，不自动审查、修稿、TTS、App发布或恢复调度。局部effort=none沿用此前独立口播试验的费用控制，不修改生产配置；实际协议由现有网关转换。字符不等于token，不承诺总费用。

底稿SHA256：08490408c4a0f7038621c98c48d7a6876b2358b9d1b22fbd7e7f922fe59e6db4。
输入SHA256：42cb64598123febd7d70595c45d3a52f8d99f9e4d3282751fbab592775f92d7a。
包：finance-macro-spoken-20261029-v1.zip。
包SHA256：ce13ddd232a0b06c14172ff53f22ad9872695602f707344fed10f3182481a5c0。

## 保护与验证

默认预览绑定服务器已完成分析的input_sha256和原回复正文指纹；要求维护暂停，核对口播源码、运行器与固定输入。绑定不符停止，不能重新生成分析解决。结果保存在staged-programme/macro-spoken-20261029-v1.json，.started永久防止重扣费。

离线演练通过免费加载、原稿记录缺失阻断、模拟单POST、编排/原句解析和重复调用拦截。本轮真实模型请求0、音频0。没有修改生产源码，不需要再次部署或重启服务。

## 服务器预览

上传包至/tmp后，校验交付指纹，解压到/tmp/finance-macro-spoken-upload-v1，运行finance-macro-spoken-20261029-v1/run_macro_spoken_once.py，不带--run。期待free_preview、manual_edit=true、http_requests_performed=0。任何不匹配先排查，不删除旧记录。

付费执行需要另外显式--run --input-sha256并使用预览对应指纹。尚未在服务器预览，尚未生成真实口播。即使后续口播合格，也不宣称自主分析、实时采集、全流程或音频验收通过。
