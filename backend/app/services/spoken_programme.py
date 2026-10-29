"""Validate an editorial handoff from the existing speech-writing call. No models."""
import json
import re

FORMAT_VERSION='spoken-programme-json-v1'

CONTRACT='口播交付为严格JSON对象，不输出JSON外的文字：\n{"programme":{"mainline":"一条主线，最多160字","choices":[{"topic":"选题，最多100字","editorial_reason":"为何值得本期展开，最多200字","report_quotes":["报告中逐字摘录的依据，每条2—240字，1—3条"]}],"omitted":["合并或舍弃的话题及简短理由，最多6项，每项160字"]},"script":"完整口播纯文本，以[SECTION_BREAK]分主题"}\nchoices为1—3个值得展开的问题，不要求每只自选股占位；有技术上的决策价值也可选，不以是否有公司新闻决定。programme是简短可审阅的编排摘要，不是推理过程，不进入语音。先作取舍，再重组script，不能把报告的章节顺序和全部指标照搬。只保留改变判断的数值，报告中的“只讲结构、不编消息、不能混淆口径”等编辑说明改为必要的分析限定或省略，不念给听众。关键事实、反方和条件不能因精简被改义。\n'


def _text(value,limit):
    return isinstance(value,str) and 1<=len(value.strip())<=limit


def parse_response(raw,report):
    text=raw.strip()
    if text.startswith('```json') and text.endswith('```'):text=text[7:-3].strip()
    try:value=json.loads(text)
    except (TypeError,ValueError):raise RuntimeError('口播缺少完整编排摘要或JSON格式错误；保留回复，不自动重试') from None
    if not isinstance(value,dict) or not isinstance(value.get('script'),str) or not value['script'].strip():
        raise RuntimeError('口播交付缺少script正文')
    plan=value.get('programme')
    if not isinstance(plan,dict) or not _text(plan.get('mainline'),160):raise RuntimeError('口播交付缺少主线')
    choices=plan.get('choices');omitted=plan.get('omitted')
    if not isinstance(choices,list) or not 1<=len(choices)<=3:raise RuntimeError('口播选题必须为1至3项')
    if not isinstance(omitted,list) or len(omitted)>6 or any(not _text(item,160) for item in omitted):
        raise RuntimeError('口播舍弃说明格式错误')
    from .spoken_editing import report_body
    source=re.sub(r'\s+',' ',report_body(report)).strip()
    for row in choices:
        if not isinstance(row,dict) or not _text(row.get('topic'),100) or not _text(row.get('editorial_reason'),200):
            raise RuntimeError('口播选题摘要不完整')
        quotes=row.get('report_quotes')
        if not isinstance(quotes,list) or not 1<=len(quotes)<=3:
            raise RuntimeError('口播选题缺少报告原句')
        for quote in quotes:
            if not isinstance(quote,str) or not 2<=len(quote)<=240 or re.sub(r'\s+',' ',quote).strip() not in source:
                raise RuntimeError('口播选题引用不在报告正文中')
    return plan,value['script']


def delivery_leaks(script):
    patterns=(r'(?m)^\s*(?:其他[^\n。]{0,16}[，,：:]\s*)?只(?:讲|给)结构[，,、\s]*不编消息[。.!！]?\s*$',
              r'(?m)^\s*(?:以下|下面)(?:是|为)[^\n。]{0,16}(?:口播稿|播客脚本)[：:。]?\s*$')
    return [match.group().strip() for pattern in patterns for match in re.finditer(pattern,script)]
