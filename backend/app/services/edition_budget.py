"""One durable reservation ledger. Dollar figures are estimates, never billing caps."""
from decimal import Decimal, InvalidOperation
import hashlib
import json

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


def model_estimate(price, input_bytes, output_tokens):
    # A conservative planning convention, NOT a tokenizer or billing guarantee.
    input_rate = max(number(price[k]) for k in ('input', 'cache_read', 'cache_write'))
    return (input_rate * input_bytes + number(price['output']) * output_tokens) / 1000000


def policy(config, routes):
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
    editorial_reserve = sum((model_estimate(prices['review' if s == 'review' else 'analysis'],
        config.edition_input_characters * 4, OUTPUTS[s]) for s in ('writing', 'review')), Decimal(0))
    return dict(model_prices=prices, search_price_usd=search_price, estimated_limit_usd=str(limit),
        protected_editorial_estimate_usd=str(editorial_reserve),
        max_model_reservations=MAX_CALLS, max_search_requests=config.research_web_search_max_requests,
        max_body_urls=config.research_body_max_urls, max_input_characters=config.edition_input_characters,
        total_input_characters=config.edition_total_input_characters,
        total_output_tokens=config.edition_total_output_tokens, audio_enabled=config.edition_audio_enabled,
        billing_boundary='accepted_estimate_only_not_provider_billing_cap',
        input_estimate='UTF8字节数按一字节一token规划；不是服务商token计数或账单保证')


class Budget:
    def __init__(self, state, save):
        self.state = state
        self.save = save

    def reserve(self, kind, *, stage=None, messages=None, output=0):
        state, p = self.state, self.state['policy']
        rows = state.setdefault('reservations', [])
        model_rows = [r for r in rows if r['kind'] == 'model']
        search_rows = [r for r in rows if r['kind'] == 'search']
        chars = byte_count = 0
        if kind == 'model':
            chars = sum(len(m['content']) for m in messages)
            byte_count = sum(len(m['content'].encode()) for m in messages)
            if (len(model_rows) >= p['max_model_reservations'] or chars > p['max_input_characters']
                    or chars + sum(r['input_characters'] for r in model_rows) > p['total_input_characters']
                    or output + sum(r['output_tokens'] for r in model_rows) > p['total_output_tokens']):
                raise ValueError('edition_model_budget_exhausted')
            fee = model_estimate(p['model_prices']['review' if stage == 'review' else 'analysis'], byte_count, output)
        elif kind == 'search':
            if len(search_rows) >= p['max_search_requests']:
                raise ValueError('edition_search_budget_exhausted')
            fee = number(p['search_price_usd'])
        else:
            raise ValueError('edition_reservation_kind_invalid')
        # Always protect remaining writing/review, including before any search.
        stages = {r.get('stage') for r in model_rows} | ({stage} if stage else set())
        remaining = Decimal(0)
        for task in ('writing', 'review'):
            if task not in stages:
                remaining += model_estimate(p['model_prices']['review' if task == 'review' else 'analysis'],
                    p['max_input_characters'] * 4, OUTPUTS[task])
        if sum((number(r['estimated_usd']) for r in rows), Decimal(0)) + fee + remaining > number(p['estimated_limit_usd']):
            raise ValueError('edition_estimated_budget_exhausted')
        row = dict(kind=kind, stage=stage, estimated_usd=str(fee), input_characters=chars,
                   input_bytes=byte_count, output_tokens=output, actual_usage='unknown_until_receipt')
        rows.append(row)
        self.save()  # Must succeed before any request; no refund for unknown outcomes.
        return row
