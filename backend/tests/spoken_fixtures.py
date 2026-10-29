"""Model-response fixtures for the explicit programme+script output contract."""
import json


def reply(script,report):
    quote=report.strip()[:100]
    return json.dumps(dict(programme=dict(mainline='本期变化及决策含义',
        choices=[dict(topic='本期关键变化',editorial_reason='用已有事实解释短线选择',report_quotes=[quote])],omitted=[]),script=script),ensure_ascii=False)
