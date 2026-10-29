from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.services.relative_strength import build, compact
from app.services.technical_radar import prompt
from app.services.prompt_reading import compact_market, restore_market
from test_relative_strength import row


class DailyRelativeContextTests(unittest.TestCase):
    def test_latest_positive_day_remains_visible_beside_negative_medium_window(self):
        sample = row('sh000688', kind='index')
        sample['metrics'].update(return_1d_pct=2.4475, return_5d_pct=-4.4927, return_20d_pct=-22.949)
        at = datetime(2026, 9, 29, 18)
        data = dict(collected_at=at.isoformat(), instruments=[sample], watchlist=[], limitation='测试序列', coverage={}, breadth={})
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder)/'technical.json').write_text(json.dumps(data), encoding='utf-8')
            with patch('requests.get', side_effect=AssertionError('no network')):
                text = prompt([], folder, at)
            restored = restore_market(compact_market(text))
        metrics = next(json.loads(line)['metrics'] for line in restored.splitlines() if line.startswith('{') and '"metrics"' in line)
        self.assertEqual(metrics['return_1d_pct'], 2.4475)
        self.assertEqual(metrics['return_20d_pct'], -22.949)
        self.assertIn('不得把20期下跌写成昨日下跌', text)

    def test_compact_relative_values_keep_absolute_and_excess_in_distinct_columns(self):
        benchmark = row('sh000300', kind='index', middle=100, end=90)
        stock = row('sh123456', kind='watchlist', middle=100, end=95)
        raw = build([benchmark, stock])
        original = next(item for item in raw['comparisons'] if item['symbol']=='sh123456')
        context = compact(raw)
        encoded = next(item for item in context['comparisons'] if item['symbol']=='sh123456')
        for period in ('recent5', 'prior5', 'latest20'):
            values = encoded[period]
            self.assertEqual(encoded['instrument_returns_pct'][period], original[period]['instrument_return_pct'])
            self.assertEqual(values[1], original[period]['excess_return_percentage_points'])
        self.assertLess(encoded['instrument_returns_pct']['recent5'], 0)
        self.assertGreater(encoded['recent5'][1], 0)
        self.assertIn('instrument_returns_pct单独给出', context['value_columns'])
