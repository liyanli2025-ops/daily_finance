from copy import deepcopy
from datetime import date,datetime,timedelta
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import time
import unittest
from unittest.mock import patch

from app.services.relative_strength import build,compact
from app.services.technical_radar import TechnicalRadar,prompt
from app.relative_strength_check import inspect
from app.services.source_health import state_path,RetiredSourceError


def row(symbol,kind='sector_proxy',market='A',middle=100,end=110):
    days=[];day=date(2026,9,1)
    while len(days)<21:
        if day.weekday()<5:days.append(day.isoformat())
        day+=timedelta(days=1)
    closes=[100.0]*21;closes[15]=middle;closes[-1]=end
    bars=[dict(date=day,close=value,open=value,high=value,low=value,volume=100) for day,value in zip(days,closes)]
    return dict(symbol=symbol,name=symbol,provider_name=symbol,kind=kind,market=market,status='ok',bars=bars,
        adjustment='index_unadjusted' if kind=='index' else 'provider_qfq',
        observed_at='2026-09-29T18:00:00',source_url='https://example.com/daily',metrics=dict(as_of=days[-1]))


class RelativeStrengthTests(unittest.TestCase):
    def setUp(self):
        self.benchmark=row('sh000300','index',middle=105,end=110)
        self.first=row('sh512480');self.second=row('sh512800',middle=110,end=110)

    def test_aligned_disjoint_windows_and_reference_difference(self):
        context=build([self.benchmark,self.first,self.second]);first=context['comparisons'][0]
        self.assertAlmostEqual(first['recent5']['instrument_return_pct'],10)
        self.assertAlmostEqual(first['recent5']['excess_return_percentage_points'],5.238095)
        self.assertEqual(first['prior5']['excess_return_percentage_points'],-5)
        self.assertAlmostEqual(first['excess_change_5_vs_prior5_percentage_points'],10.238095)
        self.assertEqual(first['recent5']['start'],first['prior5']['end'])
        members={item['symbol']:item for item in context['proxy_samples'][0]['members']}
        self.assertEqual((members['sh512480']['recent_rank'],members['sh512480']['prior_rank']),(1,2))
        self.assertEqual((members['sh512800']['recent_rank'],members['sh512800']['prior_rank']),(2,1))

    def test_missing_internal_date_does_not_align_by_endpoints_or_fill(self):
        self.first['bars'].pop(-3)
        context=build([self.benchmark,self.first,self.second])
        self.assertEqual(context['comparisons'][0]['reason'],'observation_dates_not_aligned')
        sample=context['proxy_samples'][0]
        self.assertEqual(sample['comparable_members'],1)
        self.assertIsNone(sample['members'][0]['recent_rank'])

    def test_prior_window_gap_does_not_invent_relative_change_or_rank(self):
        self.first['bars'].pop(-7)
        context=build([self.benchmark,self.first,self.second]);first=context['comparisons'][0]
        self.assertEqual(first['status'],'ok')
        self.assertEqual(first['prior5']['reason'],'observation_dates_not_aligned')
        self.assertIsNone(first['excess_change_5_vs_prior5_percentage_points'])
        self.assertEqual(context['proxy_samples'][0]['comparable_members'],1)

    def test_cross_market_uses_own_benchmark_or_reports_gap(self):
        hk=row('hk00123','watchlist','HK')
        context=build([self.benchmark,hk])
        self.assertEqual(context['comparisons'][0]['reason'],'same_market_benchmark_unavailable')
        hsi=row('hkHSI','index','HK',end=120)
        context=build([self.benchmark,hsi,hk])
        self.assertEqual(context['comparisons'][0]['benchmark'],'hkHSI')
        self.assertAlmostEqual(context['comparisons'][0]['recent5']['excess_return_percentage_points'],-10)
        self.assertEqual(context['proxy_samples'],[])

    def test_bad_series_adjustment_and_dates_do_not_rank(self):
        for mutation in ('price','adjustment','date','as_of'):
            candidate=deepcopy(self.first)
            if mutation=='price':candidate['bars'][-1]['close']=float('nan')
            if mutation=='adjustment':candidate['adjustment']='unadjusted_stock'
            if mutation=='date':candidate['bars'][-1]['date']=candidate['bars'][-2]['date']
            if mutation=='as_of':candidate['metrics']['as_of']='2026-09-28'
            self.assertEqual(build([self.benchmark,candidate])['comparisons'][0]['status'],'unavailable')

    def test_short_history_duplicate_identity_and_failed_sources_are_explicit(self):
        self.first['bars']=self.first['bars'][-5:]
        result=build([self.benchmark,self.first])['comparisons'][0]
        self.assertEqual(result['reason'],'insufficient_observations')
        self.assertEqual(build([self.benchmark,self.benchmark])['reason'],'duplicate_instrument_identity')
        failed=dict(self.second,status='failed',reason='paused_no_retest')
        self.assertEqual(build([self.benchmark,failed])['comparisons'][0]['reason'],'paused_no_retest')

    def test_rank_ties_do_not_create_fake_winners(self):
        tied=dict(self.first,symbol='sh512170')
        sample=build([self.benchmark,self.first,tied])['proxy_samples'][0]
        self.assertEqual([item['recent_rank'] for item in sample['members']],[1,1])

    def test_positive_relative_return_can_still_be_an_absolute_loss(self):
        benchmark=row('sh000300','index',end=90)
        losing=row('sh512480',end=95)
        result=build([benchmark,losing])
        recent=result['comparisons'][0]['recent5']
        self.assertEqual(recent['instrument_return_pct'],-5)
        self.assertEqual(recent['benchmark_return_pct'],-10)
        self.assertEqual(recent['excess_return_percentage_points'],5)
        self.assertIn('不等于绝对上涨',result['definition'])

    def test_compact_window_references_preserve_all_excess_values(self):
        full=build([self.benchmark,self.first,self.second]);small=compact(full)
        definitions={item['id']:item for item in small['windows']}
        for original,reduced in zip(full['comparisons'],small['comparisons']):
            for period in ('recent5','prior5','latest20'):
                key,value=reduced[period]
                self.assertEqual(value,original[period]['excess_return_percentage_points'])
                self.assertEqual(definitions[key]['start'],original[period]['start'])
        self.assertLess(len(json.dumps(small,ensure_ascii=False)),5000)

    def test_old_snapshot_replay_is_read_only_and_never_refreshes(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'technical.json'
            path.write_text(json.dumps(dict(collected_at='2026-09-29T18:00:00',instruments=[self.benchmark,self.first])),encoding='utf-8')
            before=path.read_bytes()
            with patch('requests.get',side_effect=AssertionError('no network')):result=inspect(path)
            self.assertEqual(result['mode'],'saved_daily_replay_not_current')
            self.assertEqual(result['snapshot_collected_at'],'2026-09-29T18:00:00')
            self.assertEqual(path.read_bytes(),before)

    def test_prompt_filters_removed_watchlist_from_comparisons(self):
        old=row('sh600001','watchlist');new=row('sz000001','watchlist')
        with tempfile.TemporaryDirectory() as folder:
            snapshot=dict(collected_at='2026-09-29T18:00:00',instruments=[self.benchmark,old,new],
                watchlist=['A:600001','A:000001'],limitation='fixture',coverage={},breadth={})
            (Path(folder)/'technical.json').write_text(json.dumps(snapshot),encoding='utf-8')
            with patch('requests.get',side_effect=AssertionError('no network')):
                text=prompt([SimpleNamespace(code='000001',market='A')],folder,datetime(2026,9,29,18))
            self.assertNotIn('sh600001',text)
            self.assertIn('sz000001',text)
            self.assertIn('prior5',text)

    def test_collection_adds_context_without_extra_fetch(self):
        specs=[{key:item[key] for key in ('symbol','name','market','kind')} for item in [self.benchmark,self.first,self.second]]
        existing={item['symbol']:item for item in [self.benchmark,self.first,self.second]}
        with tempfile.TemporaryDirectory() as folder:
            radar=TechnicalRadar(folder)
            with patch('app.services.technical_radar.instruments',return_value=specs),patch.object(radar,'fetch',side_effect=lambda spec,deadline:deepcopy(existing[spec['symbol']])) as fetch,patch('requests.get',side_effect=AssertionError('no extra HTTP')):
                result=radar.collect([])
            self.assertEqual(fetch.call_count,3)
            self.assertEqual(result['relative_strength']['status'],'ok')

    def test_saved_watchlist_parser_failure_migrates_without_retesting(self):
        spec=dict(symbol='hk00123',name='动态港股',kind='watchlist',market='HK')
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'technical.json'
            path.write_text(json.dumps(dict(instruments=[dict(spec,status='failed',reason='completed_daily_or_adjusted_series_missing')])),encoding='utf-8')
            original=path.read_bytes()
            with patch('requests.get',side_effect=AssertionError('must not retest')) as get:
                with self.assertRaises(RetiredSourceError):TechnicalRadar(folder).fetch(spec,time.monotonic()+5)
            get.assert_not_called()
            self.assertTrue(state_path(folder,'daily:v1:hk00123').exists())
            self.assertEqual(path.read_bytes(),original)

    def test_new_parser_failure_is_retired_before_second_http(self):
        import requests
        spec=dict(symbol='hk00456',name='新动态港股',kind='watchlist',market='HK')
        response=requests.Response();response.status_code=200
        response._content=json.dumps(dict(code=0,data={'hk00456':{}})).encode()
        with tempfile.TemporaryDirectory() as folder,patch('requests.get',return_value=response) as get:
            with self.assertRaisesRegex(ValueError,'completed_daily'):TechnicalRadar(folder).fetch(spec,time.monotonic()+5)
            with self.assertRaises(RetiredSourceError):TechnicalRadar(folder).fetch(spec,time.monotonic()+5)
            get.assert_called_once()

    def test_temporary_incomplete_day_is_not_permanently_retired(self):
        import requests
        spec=dict(symbol='sh600123',name='动态股票',kind='watchlist',market='A')
        response=requests.Response();response.status_code=200;response._content=b'{}'
        with tempfile.TemporaryDirectory() as folder,patch('requests.get',return_value=response),patch('app.services.technical_radar.parse_bars',side_effect=ValueError('no_completed_daily_bars')):
            with self.assertRaisesRegex(ValueError,'no_completed_daily'):TechnicalRadar(folder).fetch(spec,time.monotonic()+5)
            self.assertFalse(state_path(folder,'daily:v1:sh600123').exists())
