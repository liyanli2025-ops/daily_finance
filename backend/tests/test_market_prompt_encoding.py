import json
import unittest

from app.services.prompt_reading import compact_market,restore_market,_json_line


class MarketEncodingTests(unittest.TestCase):
    def sample(self):
        rows=[]
        for i in range(17):
            rows.append('技术家族：'+json.dumps(dict(symbol='sh'+str(i),as_of='2026-10-28T13:19:00',
                source_quote_time='2026-10-28T13:04:03',source_url='https://example.com/dated',
                metrics=dict(return_20d_percentage_points=-39.5+i,volume_vs_prior20=None,
                    close_above_prior20_high=False,excess_20d_percentage_points=1.1,
                    sample=dict(benchmark_adjustment_comparable=True)),
                flags=[dict(close_above_prior20_high=True,volume_vs_prior20=.99)],
                f0='original key that must never collide'),ensure_ascii=False))
        return '行情限制：不是同一时点，缺失不是零。\n'+'\n'.join(rows)+'\n缺口：港股宽度不可用。\n'

    def test_all_values_keys_types_and_timestamps_survive_round_trip(self):
        text=self.sample();encoded=compact_market(text);decoded=restore_market(encoded)
        self.assertLess(len(encoded),len(text)*.8)
        self.assertIn('source_quote_time',encoded)
        self.assertIn('2026-10-28T13:04:03',encoded)
        self.assertIn('缺口：港股宽度不可用。',decoded)
        for original,restored in zip(text.splitlines(),decoded.splitlines()):
            if _json_line(original):self.assertEqual(_json_line(original)[1],_json_line(restored)[1])
            else:self.assertEqual(original,restored)
        self.assertEqual(compact_market(encoded),encoded)

    def test_plain_text_invalid_json_and_small_objects_are_unchanged(self):
        for text in ['普通报价 13:19，涨幅1%。',"{'python_repr': 'not_json'}",'bad {"long_field_name": 1} trailing words',
                     '{"long_field_name":1}']:
            self.assertEqual(compact_market(text),text)
            self.assertEqual(restore_market(text),text)

    def test_coverage_summary_keeps_errors_counts_dates_and_financial_availability(self):
        from app.services.research_hub import coverage_brief
        raw=dict(financial=dict(status='ok',read=2,period='2026-06-30'),
            profile=dict(status='failed',reason='identity_mismatch'),
            primary_notices=dict(status='partial',read=1,failures=['failed article'],
                latest_publication='2026-10-28T10:00:00',limitation='repeated instructions'),
            industry_observations=dict(sources=dict(nea=dict(status='failed',read=0,body_errors=['a','b']))))
        reduced=coverage_brief(raw)
        self.assertEqual(reduced['financial'],raw['financial'])
        self.assertEqual(reduced['profile'],raw['profile'])
        self.assertEqual(reduced['primary_notices']['failures_count'],1)
        self.assertEqual(reduced['primary_notices']['latest_publication'],'2026-10-28T10:00:00')
        self.assertEqual(reduced['industry_observations']['sources']['nea']['body_errors_count'],2)
        self.assertIn('limitation',raw['primary_notices'])

