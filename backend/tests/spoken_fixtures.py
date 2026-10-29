"""Model-response fixtures for the explicit programme+script output contract."""
import json


def reply(script,report):
    quote=report.strip()[:100]
    return json.dumps(dict(programme=dict(mainline='本期变化及决策含义',
        choices=[dict(topic='本期关键变化',editorial_reason='用已有事实解释短线选择',report_quotes=[quote])],omitted=[]),script=script),ensure_ascii=False)


def review_reply(report,script):
    """Transport/anchor fixture only; not a semantic correctness example."""
    return json.dumps(dict(passed=True,issues=[],checks=[dict(facet=facet,status='preserved',
        report_quote=report[:100],script_quote=script[:100],reason='仅验证测试数据的引用检查流程')
        for facet in ('facts','judgment','qualifiers')]),ensure_ascii=False)
