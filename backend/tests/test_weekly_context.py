from datetime import date,datetime,timedelta
import unittest

from app.services.weekly_context import weekly_context


def bars(start='2026-01-05',days=200):
    first=date.fromisoformat(start);rows=[]
    for i in range(days):
        day=first+timedelta(days=i)
        if day.weekday()<5:
            price=100+i
            rows.append(dict(date=day.isoformat(),open=price,close=price+1,high=price+2,low=price-1,volume=10))
    return rows


class WeeklyContextTests(unittest.TestCase):
    def test_current_wednesday_week_is_excluded(self):
        rows=bars(days=3)
        result=weekly_context(rows,datetime(2026,1,7,16),'A')
        self.assertEqual(result['status'],'unavailable')
        self.assertEqual(result['skipped'][0]['reason'],'unfinished_or_unconfirmed_week')

    def test_friday_market_completion_is_distinct_and_ohlcv_is_exact(self):
        rows=bars(days=5)
        result=weekly_context(rows,datetime(2026,1,9,15,40),'A')
        self.assertEqual(result['metrics']['close'],105)
        self.assertEqual(result['metrics']['last_week_sessions'],5)
        self.assertEqual(result['as_of'],'2026-01-09')
        self.assertEqual(result['latest_ohlcv'],dict(open=100,high=106,low=99,close=105,volume=50))
        with self.assertRaisesRegex(ValueError,'uncompleted'):
            weekly_context(rows,datetime(2026,1,9,15,40),'HK')
        self.assertEqual(weekly_context(rows,datetime(2026,1,9,16,40),'HK')['status'],'ok')

    def test_truncated_left_edge_not_used_as_complete_week(self):
        rows=bars(start='2026-01-07',days=10)
        result=weekly_context(rows,datetime(2026,1,19,8),'A')
        self.assertEqual(result['observations'],1)
        self.assertEqual(result['skipped'][0]['reason'],'left_edge_may_be_truncated')

    def test_no_friday_cannot_be_confirmed_before_next_week(self):
        rows=bars(days=4)
        self.assertEqual(weekly_context(rows,datetime(2026,1,10,12),'A')['observations'],0)
        result=weekly_context(rows,datetime(2026,1,12,8),'A')
        self.assertEqual(result['metrics']['last_week_sessions'],4)
        self.assertEqual(result['calendar_status'],'not_independently_verified')

    def test_insufficient_history_is_none_not_zero_and_no_index_volume(self):
        rows=bars(days=5)
        result=weekly_context(rows,datetime(2026,1,12,8),'A',False)
        self.assertIsNone(result['metrics']['ma20'])
        self.assertIsNone(result['metrics']['return_4_observed_weeks_pct'])
        self.assertIsNone(result['metrics']['volume_vs_prior10_observed_weeks'])
        self.assertIn('ma20',result['warming_up'])

    def test_long_history_comparison_retains_different_as_of_dates(self):
        rows=bars(days=199)
        result=weekly_context(rows,datetime(2026,7,22,17),'A',True,
            dict(as_of='2026-07-22',close=90,ma20=100))
        self.assertEqual(result['comparison']['relationship'],'different_sides')
        self.assertEqual(result['comparison']['weekly_as_of'],'2026-07-17')
        self.assertEqual(result['comparison']['daily_as_of'],'2026-07-22')
        self.assertEqual(result['metrics']['volume_vs_prior10_observed_weeks'],1)

    def test_week_without_records_is_not_zero_filled_or_hidden(self):
        rows=[row for row in bars(days=30) if not '2026-01-12'<=row['date']<='2026-01-16']
        result=weekly_context(rows,datetime(2026,2,4,17),'A')
        self.assertIn('2026-01-12',result['absent_week_starts'])

    def test_future_duplicate_or_unknown_market_are_rejected(self):
        rows=bars(days=5)
        with self.assertRaises(ValueError):weekly_context(rows+rows[-1:],datetime(2026,1,12,8),'A')
        with self.assertRaises(ValueError):weekly_context(rows,datetime(2026,1,8,17),'A')
        self.assertEqual(weekly_context(rows,datetime(2026,1,12,8),'US')['status'],'unavailable')

    def test_real_technical_pipeline_and_prompt_use_weekly_reference_without_extra_api(self):
        import tempfile
        from unittest.mock import patch
        from app.services.technical_radar import TechnicalRadar,indicators,prompt
        history=bars(start='2026-05-04',days=177)
        observed=datetime(2026,10,28,17)
        spec=dict(symbol='sh000001',name='上证指数',market='A',kind='index')
        with tempfile.TemporaryDirectory() as root:
            radar=TechnicalRadar(root)
            with patch('app.services.technical_radar.instruments',return_value=[spec]), \
                    patch.object(radar,'fetch',return_value=dict(**spec,status='ok',provider_name='上证指数',adjustment='index_unadjusted',observed_at=observed.isoformat(),bars=history,metrics=indicators(history))), \
                    patch('app.services.technical_radar.china_now',return_value=observed), \
                    patch('requests.get',side_effect=AssertionError('no extra HTTP')):
                snapshot=radar.collect([])
                text=prompt([],root,observed)
            self.assertEqual(snapshot['weekly_coverage']['available'],1)
            self.assertIn('2026-10-23',text)
            self.assertIn('不是独立交易所周K',text)

    def test_explicit_daily_http_failure_is_persisted_not_retried(self):
        import requests,tempfile,time
        from unittest.mock import patch
        from app.services.technical_radar import TechnicalRadar
        response=requests.Response();response.status_code=410
        spec=dict(symbol='sh000001',name='上证指数',market='A',kind='index')
        with tempfile.TemporaryDirectory() as root,patch('requests.get',return_value=response) as get:
            radar=TechnicalRadar(root)
            with self.assertRaises(ValueError):radar.fetch(spec,time.monotonic()+5)
            with self.assertRaisesRegex(ValueError,'source_paused_no_automatic_retest'):radar.fetch(spec,time.monotonic()+5)
            self.assertEqual(get.call_count,1)
