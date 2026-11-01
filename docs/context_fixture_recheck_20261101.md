# v23测试样例修正与离线回放（2026-11-01）

## 服务器实际回传

用户已经安装v23三个源码文件，revision为`03c91e313091629b9b7291b185e7f99a0f656aff`，私有备份`20261101T074250740550Z`，维护暂停保留，服务没有重启。51个离线测试中50个通过，1个旧测试`test_model_selects_second_result_instead_of_first`因模拟回复用完而报`StopAsyncIteration`。14个新增分页用例全部通过。

命令使用`set -e`，测试失败后不会继续执行`replay_discovery_context.py`，因此目前没有这份实际底稿的分页回放结果。本次测试使用模拟模型/搜索/正文传输，未请求真实服务商。

## 代码定位与修正范围

该用例验证从两个搜索候选中选择第二个，并预置“搜索、读取、结束”三条模型响应。其结束事件只提供title/why_it_matters/evidence_ids/caveats，没有现行默认取材协议要求的lane和四项research_checks。

默认进展取材会调用`review_events()`：缺少lane或完整research_checks时产生`event_research_checks_missing`；`assess_finish()`之外的这项研究检查会阻止接受结束申请，所以控制器继续请求第4条响应。模拟响应仅有3条，最终产生回传错误。

本轮只更新该测试事件：lane为us_market，primary_facts带示例正文B1，background/disagreements/transmission明确为测试范围内not_applicable并说明不作研究结论。保持原有选择第二项、只读目标URL、三次模型及保留其他方向缺口等断言。生产源码、研究检查和预算均不变。

原测试文件SHA256：`0ebed4d056cd99cb25e8050a294d613cb003373d033c70b986fe9c4186a41c43`。

修正后SHA256：`a3a99d7d42dc3f2d872885668df122ef7e0decedfdf6651a2400eb092fbf9fae`。

## 服务器下一步

直接执行随交付提供的命令：只修改已经解压在`/tmp/daily-finance-context-paging-v23/backend/tests`的这一份临时测试文件。命令核对原/新文件哈希，可重复执行；遇到其他内容或软链立即停止。原ZIP继续保留作为旧样例依据。无需再上传或安装源码。

随后重新执行同一组51个测试，通过后再运行现有的离线底稿回放。全程模型/搜索/正文HTTP/TTS请求为0，服务和自动化状态保持原样。原result和started标记不清理、不重跑收费取材。

本环境只做源码核对、测试样例修改、文档和命令生成，以及GitHub备份；未运行测试、构建或回放。修正后的51个测试及实际底稿回放仍待服务器执行，不能预先声称已通过。

## 周末补充要求

本轮人工验收按用户补充的周末周期执行：行情参照最近已完成交易日，周末新增政策/公告/事件继续纳入；前几日仍有效的背景、月度综述与晨报可以辅助理解，同时保留发布时间、统计周期及市场时段。当前软件时窗仍为72小时；本次测试修正不改变自动时窗。

这条修正没有Skill调用方或接口变更。GitHub继续备份到`improve/reading-acceptance`，不合入主干。
