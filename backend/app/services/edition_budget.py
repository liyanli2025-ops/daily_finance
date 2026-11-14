"""One durable reservation ledger. Dollar figures are estimates, never billing caps."""
from decimal import Decimal, InvalidOperation
import hashlib
import json

NORMAL_STAGES = ('agenda', 'assessment', 'writing', 'review')
MAX_CALLS = 5
OUTPUTS = dict(agenda=5000, assessment=4000, patch_assessment=4000, writing=10000, review=5000)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def number(value):
    try:
        result = Decimal(str(value))
    except (ValueError, InvalidOperation):
        raise ValueError('edition_price_missing') from None
    if not result.is_finite() or result < 0:
        raise ValueError('edition_price_invalid')
    return result


def request_input_pricing(body):
    """No cache discount is assumed. Explicit cache controls require full pricing."""
    def caching(value):
        if isinstance(value, dict):
            return 'cache_control' in value or any(caching(v) for v in value.values())
        return isinstance(value, list) and any(caching(v) for v in value)
    return 'unknown' if caching(body) else 'uncached_request_v1'


def model_estimate(price, input_bytes, output_tokens, *, input_pricing='unknown', future_input_tokens=0):
    # Known UTF8 bytes remain a conservative token planning convention, never a
    # tokenizer. Future model outputs already have a token allowance: do not
    # convert them to bytes and then pretend those bytes are all input tokens.
    if any(type(n) is not int or n < 0 for n in (input_bytes, output_tokens, future_input_tokens)):
        raise ValueError('edition_forecast_invalid')
    if input_pricing not in {'unknown', 'uncached_request_v1'}:
        raise ValueError('edition_input_pricing_invalid')
    input_rate = (number(price['input']) if input_pricing == 'uncached_request_v1'
                  else max(number(price[k]) for k in ('input', 'cache_read', 'cache_write')))
    return (input_rate * (input_bytes + future_input_tokens)
            + number(price['output']) * output_tokens) / 1000000


def policy(config, routes, *, request_pricing=None):
    prices = {}
    for task, route in routes.items():
        key = route.provider + '/' + route.model
        price = config.edition_price_table.get(key)
        if not isinstance(price, dict) or set(price) != {'input', 'output', 'cache_read', 'cache_write'}:
            raise ValueError('edition_model_price_missing:' + key)
        prices[task] = {k: str(number(v)) for k, v in price.items()}
    search_price = str(number(config.edition_search_price_usd))
    limit = number(config.edition_estimated_limit_usd)
    if limit <= 0:
        raise ValueError('edition_estimate_limit_missing')
    return dict(model_prices=prices, search_price_usd=search_price, estimated_limit_usd=str(limit),
        edition_forecast='remaining_stages_v1',
        request_input_pricing=request_pricing or {k: 'unknown' for k in routes},
        max_model_reservations=MAX_CALLS, max_search_requests=config.research_web_search_max_requests,
        max_body_urls=config.research_body_max_urls, max_input_characters=config.edition_input_characters,
        total_input_characters=config.edition_total_input_characters,
        total_output_tokens=config.edition_total_output_tokens, audio_enabled=config.edition_audio_enabled,
        billing_boundary='accepted_estimate_only_not_provider_billing_cap',
        input_estimate='已知UTF8字节按token规划；未来模型结果按输出token额度另留25%输入余量；非服务商账单保证')


def protection(policy, forecasts, reserved_stages=()):
    required = set(NORMAL_STAGES) if policy.get('edition_forecast') == 'remaining_stages_v1' else {'writing', 'review'}
    if isinstance(forecasts, list) and any(isinstance(r, dict) and r.get('stage') == 'patch_assessment' for r in forecasts):
        if policy.get('edition_forecast') != 'remaining_stages_v1':
            raise ValueError('edition_editorial_forecast_invalid')
        required.add('patch_assessment')
    if (not isinstance(forecasts, list) or len(forecasts) != len(required)
            or any(not isinstance(r, dict) or not required.issuperset({r.get('stage')}) for r in forecasts)
            or {r['stage'] for r in forecasts} != required
            or any(type(r.get(k)) is not int or r[k] < 0 for r in forecasts
                   for k in ('known_input_bytes', 'future_draft_allowance_bytes', 'output_tokens'))):
        raise ValueError('edition_editorial_forecast_invalid')
    remaining, rows = Decimal(0), []
    for row in forecasts:
        if row['stage'] in reserved_stages:
            continue
        task = 'review' if row['stage'] == 'review' else 'analysis'
        fee = model_estimate(policy['model_prices'][task],
            row['known_input_bytes'] + row['future_draft_allowance_bytes'], row['output_tokens'],
            input_pricing=policy.get('request_input_pricing', {}).get(task, 'unknown'),
            future_input_tokens=row.get('future_input_tokens', 0))
        rows.append(dict(row, estimated_usd=str(fee)))
        remaining += fee
    return remaining, rows


def search_batch_plan(policy, forecasts, count, reservations=()):
    if type(count) is not int or count < 0:
        raise ValueError('edition_search_batch_invalid')
    remaining, rows = protection(policy, forecasts,
        {r.get('stage') for r in reservations if r['kind'] == 'model'})
    search_count = sum(r['kind'] == 'search' for r in reservations)
    spent = sum((accounted(r) for r in reservations), Decimal(0))
    batch = number(policy['search_price_usd']) * count
    required = spent + batch + remaining
    return dict(model_stages=rows, spent_or_reserved_usd=str(spent),
        remaining_model_estimate_usd=str(remaining), search_batch_count=count,
        search_batch_estimate_usd=str(batch), required_estimated_usd=str(required),
        limit_usd=str(number(policy['estimated_limit_usd'])),
        fits_money=required <= number(policy['estimated_limit_usd']),
        fits_search_count=search_count + count <= policy['max_search_requests'],
        future_search_results_and_bodies_priced=False, guarantees_episode_completion=False,
        limitation='整批搜索和剩余必要模型阶段按当前资料预检；未知检索结果及新正文可能增加费用，后续仍逐请求复核。')


def accounted(row):
    # An unknown/failed response retains its original full reservation.
    return number(row.get('usage_priced_usd', row['estimated_usd']))


class Budget:
    def __init__(self, state, save, forecast=None):
        self.state = state
        self.save = save
        self.forecast = forecast

    def check_search_batch(self, count):
        if self.state['policy'].get('edition_forecast') != 'remaining_stages_v1':
            return  # Existing ledgers retain their reviewed policy.
        if self.forecast is None:
            raise ValueError('edition_editorial_forecast_missing')
        plan = search_batch_plan(self.state['policy'], self.forecast(), count,
                                 self.state.get('reservations', []))
        self.state.setdefault('search_batch_checks', []).append(plan)
        self.state['budget_forecast'] = plan
        self.save()  # A failed persistence cannot precede an external request.
        if not plan['fits_search_count']:
            raise ValueError('edition_search_budget_exhausted')
        if not plan['fits_money']:
            self.state['budget_stop'] = 'edition_initial_or_patch_batch_budget_exhausted'
            self.save()
            raise ValueError('edition_estimated_budget_exhausted')

    def record_usage(self, reservation, usage):
        reservation['actual_usage'] = {k: usage.get(k) for k in
            ('http_status', 'input_tokens', 'output_tokens', 'cache_read_tokens', 'cache_write_tokens')}
        # Anthropic input counts exclude cache buckets. Compatible providers may
        # count them inside input_tokens; do not assume their semantics here.
        keys = ('input_tokens', 'output_tokens', 'cache_read_tokens', 'cache_write_tokens')
        if (usage.get('http_status') != 200 or usage.get('transport_error')
                or usage.get('provider') not in {'anthropic', 'ofox_anthropic'}
                or any(type(usage.get(k)) is not int or usage[k] < 0 for k in keys)):
            return
        price = self.state['policy']['model_prices']['review' if reservation['stage'] == 'review' else 'analysis']
        total = sum((number(price[rate]) * usage[key] for rate, key in
            (('input', 'input_tokens'), ('output', 'output_tokens'),
             ('cache_read', 'cache_read_tokens'), ('cache_write', 'cache_write_tokens'))), Decimal(0)) / 1000000
        reservation['usage_priced_usd'] = str(total)
        reservation['usage_price_basis'] = '已返回完整token用量×已接受价格，非账户账单；原预留及失败计数仍保留'

    def reserve(self, kind, *, stage=None, messages=None, output=0):
        state, p = self.state, self.state['policy']
        rows = state.setdefault('reservations', [])
        model_rows = [r for r in rows if r['kind'] == 'model']
        search_rows = [r for r in rows if r['kind'] == 'search']
        chars = byte_count = 0
        if kind == 'model':
            chars = sum(len(m['content']) for m in messages)
            byte_count = sum(len(m['content'].encode()) for m in messages)
            dimensions = {
                'model_reservations': (len(model_rows)+1,p['max_model_reservations']),
                'request_input_characters': (chars,p['max_input_characters']),
                'total_input_characters': (chars+sum(r['input_characters'] for r in model_rows),p['total_input_characters']),
                'total_output_tokens': (output+sum(r['output_tokens'] for r in model_rows),p['total_output_tokens'])}
            blocked = {k:dict(required=n,limit=limit) for k,(n,limit) in dimensions.items() if n>limit}
            if blocked:
                state['budget_block'] = dict(stage=stage,dimensions=blocked,model_http_started=False)
                self.save()
                raise ValueError('edition_model_budget_exhausted')
            task = 'review' if stage == 'review' else 'analysis'
            fee = model_estimate(p['model_prices'][task], byte_count, output,
                input_pricing=p.get('request_input_pricing', {}).get(task, 'unknown'))
        elif kind == 'search':
            if len(search_rows) >= p['max_search_requests']:
                raise ValueError('edition_search_budget_exhausted')
            fee = number(p['search_price_usd'])
        else:
            raise ValueError('edition_reservation_kind_invalid')
        # New ledgers protect all remaining stages, including before any search.
        stages = {r.get('stage') for r in model_rows} | ({stage} if stage else set())
        if (p.get('editorial_forecast') == 'known_payload_v1'
                or p.get('edition_forecast') == 'remaining_stages_v1'):
            if self.forecast is None:
                raise ValueError('edition_editorial_forecast_missing')
            remaining, plan = protection(p, self.forecast(), stages)
            for future in plan:
                if future.get('fits_known_input') is False:
                    state['budget_block'] = dict(stage=future['stage'], dimensions={
                        'request_input_characters': dict(required=future['known_input_characters'],limit=p['max_input_characters'])},
                        model_http_started=False)
                    self.save()
                    raise ValueError('edition_future_input_capacity_exhausted')
            state['budget_forecast'] = dict(editorial=plan, remaining_model_estimate_usd=str(remaining),
                limitation='随正文和稿件更新；未知未来取材可能增加预留，预算不足则保留资料停止。')
        else:
            # Preserve the old policy for already-created ledgers and tests.
            remaining = sum((model_estimate(p['model_prices']['review' if s == 'review' else 'analysis'],
                p['max_input_characters'] * 4, OUTPUTS[s]) for s in ('writing', 'review') if s not in stages), Decimal(0))
        if sum((accounted(r) for r in rows), Decimal(0)) + fee + remaining > number(p['estimated_limit_usd']):
            state['budget_stop'] = 'edition_estimated_budget_exhausted'
            self.save()
            raise ValueError('edition_estimated_budget_exhausted')
        row = dict(kind=kind, stage=stage, estimated_usd=str(fee), input_characters=chars,
                   input_bytes=byte_count, output_tokens=output, actual_usage='unknown_until_receipt')
        rows.append(row)
        self.save()  # Must succeed before any request; no refund for unknown outcomes.
        return row
