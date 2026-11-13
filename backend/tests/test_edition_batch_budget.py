"""Money boundary regression: pure local arithmetic and configuration copies."""
import copy
from decimal import Decimal
from types import SimpleNamespace
import unittest

from app.edition_preflight import scenario_config
from app.services.edition_budget import (Budget, OUTPUTS, NORMAL_STAGES, model_estimate,
    request_input_pricing, search_batch_plan)

PRICE = dict(input='2', output='10', cache_read='.2', cache_write='4')


def policy():
    return dict(edition_forecast='remaining_stages_v1', model_prices=dict(analysis=PRICE, review=PRICE),
        request_input_pricing=dict(analysis='uncached_request_v1', review='uncached_request_v1'),
        estimated_limit_usd='.50', search_price_usd='.008', max_search_requests=24,
        max_model_reservations=5, max_input_characters=65000, total_input_characters=325000,
        total_output_tokens=30000)


def forecasts():
    # Four known-stage estimates total .424; one search fits, 12 do not.
    return [dict(stage=s, known_input_bytes=23000, future_draft_allowance_bytes=0,
        output_tokens=6000) for s in NORMAL_STAGES]


class BatchMoneyTests(unittest.TestCase):
    def test_whole_batch_rejected_before_any_reservation(self):
        run = dict(policy=policy(), reservations=[]); saved = []
        b = Budget(run, lambda: saved.append(copy.deepcopy(run)), forecasts)
        self.assertTrue(search_batch_plan(run['policy'], forecasts(), 1)['fits_money'])
        with self.assertRaisesRegex(ValueError, 'edition_estimated_budget_exhausted'):
            b.check_search_batch(12)
        self.assertEqual(run['reservations'], [])
        self.assertEqual(run['budget_forecast']['search_batch_count'], 12)
        self.assertEqual(len(saved), 2)

    def test_all_four_stages_in_initial_plan(self):
        plan = search_batch_plan(policy(), forecasts(), 12)
        self.assertEqual({r['stage'] for r in plan['model_stages']}, set(NORMAL_STAGES))
        self.assertEqual(Decimal(plan['required_estimated_usd']), Decimal('.520'))
        self.assertFalse(plan['guarantees_episode_completion'])
        self.assertFalse(plan['future_search_results_and_bodies_priced'])

    def test_conditional_stage_protected_before_patch_search(self):
        rows = forecasts() + [dict(forecasts()[0], stage='patch_assessment')]
        plan = search_batch_plan(policy(), rows, 1)
        self.assertIn('patch_assessment', [r['stage'] for r in plan['model_stages']])
        self.assertFalse(plan['fits_money'])

    def test_search_count_blocks_entire_batch(self):
        p = policy(); p['max_search_requests'] = 11
        run = dict(policy=p, reservations=[])
        with self.assertRaisesRegex(ValueError, 'edition_search_budget_exhausted'):
            Budget(run, lambda: None, forecasts).check_search_batch(12)
        self.assertEqual(run['reservations'], [])

    def test_ledger_save_failure_prevents_batch_start(self):
        def fail(): raise OSError('disk full')
        with self.assertRaises(OSError):
            Budget(dict(policy=policy()), fail, forecasts).check_search_batch(1)

    def test_unknown_failed_reservation_still_counts(self):
        p = policy()
        rows = [dict(kind='model', stage='agenda', estimated_usd='.2')]
        plan = search_batch_plan(p, forecasts(), 12, rows)
        self.assertEqual(Decimal(plan['spent_or_reserved_usd']), Decimal('.2'))
        self.assertNotIn('agenda', [r['stage'] for r in plan['model_stages']])
        self.assertFalse(plan['fits_money'])

    def test_above_reservation_receipt_blocks_next_batch(self):
        plan = search_batch_plan(policy(), forecasts(), 1, [dict(kind='model', stage='agenda',
            estimated_usd='.01', usage_priced_usd='.4')])
        self.assertEqual(Decimal(plan['spent_or_reserved_usd']), Decimal('.4'))
        self.assertFalse(plan['fits_money'])

    def test_invalid_forecast_cannot_be_free(self):
        for rows in (None, [], forecasts()[:-1], [dict(stage='writing')], [None] * 4):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                search_batch_plan(policy(), rows, 1)

    def test_missing_callback_cannot_start_new_ledger(self):
        with self.assertRaisesRegex(ValueError, 'forecast_missing'):
            Budget(dict(policy=policy()), lambda: None).check_search_batch(1)

    def test_legacy_ledger_not_repriced(self):
        p = policy(); p.pop('edition_forecast')
        run = dict(policy=p); before = copy.deepcopy(run)
        Budget(run, lambda: self.fail('legacy batch check saved')).check_search_batch(12)
        self.assertEqual(run, before)


class RequestPricingTests(unittest.TestCase):
    def test_uncached_request_uses_input_price_not_cache_write(self):
        self.assertEqual(model_estimate(PRICE, 100000, 5000, input_pricing='uncached_request_v1'), Decimal('.25'))
        self.assertEqual(model_estimate(PRICE, 100000, 5000), Decimal('.45'))

    def test_cache_controls_anywhere_require_conservative_pricing(self):
        for body in (dict(cache_control={}), dict(messages=[dict(content=[dict(cache_control={})])])):
            self.assertEqual(request_input_pricing(body), 'unknown')
        self.assertEqual(request_input_pricing(dict(messages=[dict(content='normal')])), 'uncached_request_v1')

    def test_future_output_token_units_not_multiplied_by_four(self):
        self.assertEqual(model_estimate(PRICE, 0, 0, input_pricing='uncached_request_v1',
            future_input_tokens=12500), Decimal('.025'))

    def test_invalid_pricing_and_counts_rejected(self):
        for kwargs in (dict(input_pricing='free'), dict(future_input_tokens=float('nan')),
                       dict(future_input_tokens=True), dict(future_input_tokens=-1)):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                model_estimate(PRICE, 10, 1, **kwargs)

    def test_output_caps_and_model_call_count_unchanged(self):
        self.assertEqual(OUTPUTS, dict(agenda=5000, assessment=4000, patch_assessment=4000, writing=10000, review=5000))
        self.assertEqual(policy()['max_model_reservations'], 5)


class ScenarioTests(unittest.TestCase):
    def config(self):
        class Config(SimpleNamespace):
            def model_copy(self, update):
                value = copy.deepcopy(self); value.__dict__.update(update); return value
        return Config(edition_estimate_accepted=True, research_web_search_enabled=False,
            api_key='private-not-exported', edition_audio_enabled=True)

    def scenario(self):
        return dict(model_prices={'ofox_anthropic/anthropic/claude-sonnet-5.5': PRICE},
            search_price_usd='.008', estimated_limit_usd='.5')

    def test_preview_copy_cannot_accept_or_enable_production(self):
        original = self.config(); before = copy.deepcopy(vars(original))
        result = scenario_config(original, self.scenario())
        self.assertFalse(result.edition_estimate_accepted)
        self.assertFalse(result.research_web_search_enabled)
        self.assertEqual(result.api_key, original.api_key)
        self.assertEqual(vars(original), before)

    def test_scenario_cannot_set_permissions_or_credentials(self):
        for key in ('edition_estimate_accepted', 'research_web_search_enabled', 'api_key'):
            with self.subTest(key=key), self.assertRaises(ValueError):
                scenario_config(self.config(), dict(self.scenario(), **{key: True}))

    def test_unknown_or_nan_price_rejected(self):
        for value in ('NaN', '-1', None):
            scenario = self.scenario(); scenario['search_price_usd'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                scenario_config(self.config(), scenario)
