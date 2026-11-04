"""Purpose-specific publication windows; no claim to be an exchange calendar."""
from .news_selection import within_window

OWNER = 'finance-purpose-window-v1'
PURPOSES = {'discovery', 'latest_close', 'released_policy', 'company_event', 'commentary'}


def policy(cutoff):
    weekend = cutoff.weekday() >= 5
    return dict(owner=OWNER, cutoff=cutoff.isoformat(), weekend=weekend,
        hours=dict(discovery=96 if weekend else 72, latest_close=96 if weekend else 72,
                   released_policy=168 if weekend else 72, company_event=168 if weekend else 72,
                   commentary=168),
        limitation='周末按用途放宽发布日期；不是交易所日历。行情须另核最近完成交易时段，背景不可充当最新消息。')


def window(cutoff, purpose):
    if purpose not in PURPOSES:
        raise ValueError('discovery_time_purpose_invalid')
    return dict(owner=OWNER, purpose=purpose, hours=policy(cutoff)['hours'][purpose],
                cutoff=cutoff.isoformat())


def validate_window(value, cutoff):
    if not isinstance(value, dict) or value.get('purpose') not in PURPOSES:
        raise ValueError('discovery_source_window_invalid')
    if value != window(cutoff, value['purpose']) or type(value.get('hours')) is not int:
        raise ValueError('discovery_source_window_invalid')
    return value


def receipt_windows(receipts, identifier, cutoff):
    values = []
    for receipt in receipts:
        result = receipt.get('result', {})
        if (receipt.get('request', {}).get('tool') == 'read' and result.get('status') == 'ok'
                and result.get('material', {}).get('id') == identifier and 'source_window' in result):
            value = validate_window(result['source_window'], cutoff)
            if value not in values:
                values.append(value)
    return values


def eligible(item, cutoff, windows):
    return any(within_window(item, cutoff, value['hours']) for value in windows) if windows else within_window(item, cutoff, 72)


def read_purpose(request, candidate):
    if 'purpose' in request:
        purpose = request['purpose']
        if purpose not in PURPOSES:
            raise ValueError('discovery_time_purpose_invalid')
        return purpose
    if request['relation'] == 'direct':
        return 'company_event'
    if request['relation'] in {'industry', 'counter'}:
        return 'commentary'
    purposes = [link.get('purpose') for link in candidate.get('discovered_by', [])]
    return next((purpose for purpose in ('latest_close', 'released_policy', 'discovery') if purpose in purposes), 'discovery')
