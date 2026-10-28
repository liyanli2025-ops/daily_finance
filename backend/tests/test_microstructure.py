from datetime import datetime,timedelta
import json,tempfile,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import requests

from app.services.intraday_context import parse_minutes,IntradayRadar
from app.services.market_breadth import parse_catalog_page,parse_dated_quotes,summarize_breadth,bounded_map
from app.services.microstructure import prompt

NOW=datetime(2026,10,28,9,43)
SPEC=dict(symbol='sz000001',market='A',kind='watchlist')


def minute_payload(symbol='sz000001',scale=100):
    qt=['0']*40;qt[1]='动态股票';qt[2]=symbol[2:];qt[4]='10';qt[30]='2026/10/28 09:41:30' if symbol.startswith('hk') else '20261028094130';qt[33]='11';qt[34]='9'
    lines=[]
    for i in range(13):
        clock=(datetime(2026,10,28,9,30)+timedelta(minutes=i)).strftime('%H%M');volume=(i+1)*10
        lines.append(f'{clock} {10+i/100:.2f} {volume} {volume*scale*10.05}')
    return dict(code=0,data={symbol:dict(data=dict(date='20261028',data=lines),qt={symbol:qt})})


def quote(symbol='sh600001',stamp='20261028094130',price=10.1,previous=10,volume=100):
    fields=['0']*40;fields[2]=symbol[2:];fields[3]=str(price);fields[4]=str(previous);fields[6]=str(volume)
    fields[30]=stamp;fields[32]=str((price/previous-1)*100)
    return 'v_'+symbol+'="'+'~'.join(fields)+'";'


class MinuteTests(unittest.TestCase):
    def test_future_and_current_points_are_not_confirmed_bars(self):
        row=parse_minutes(minute_payload(),SPEC,NOW)
        self.assertEqual(row['as_of'],'2026-10-28T09:40:00')
        self.assertEqual(row['observations'],11);self.assertEqual(row['excluded_unconfirmed_points'],2)
        self.assertEqual(row['volume']['consistent_volume_scale'],100)
        self.assertAlmostEqual(row['volume']['implied_cumulative_average_price'],10.05)
        self.assertEqual(row['volume']['recent5_vs_previous5_interval_rate'],1)

    def test_hk_units_not_assumed_to_be_a_share_lots(self):
        row=parse_minutes(minute_payload('hk00700',1),dict(symbol='hk00700',market='HK',kind='watchlist'),NOW)
        self.assertEqual(row['volume']['consistent_volume_scale'],1)

    def test_index_volume_never_becomes_vwap(self):
        row=parse_minutes(minute_payload('sh000001'),dict(symbol='sh000001',market='A',kind='index'),NOW)
        self.assertEqual(row['volume']['status'],'unavailable')
        self.assertNotIn('implied_cumulative_average_price',row['volume'])

    def test_missing_amount_is_not_invented(self):
        data=minute_payload();node=data['data']['sz000001']['data']
        node['data']=[' '.join(line.split()[:3]) for line in node['data']]
        self.assertIsNone(parse_minutes(data,SPEC,NOW)['volume']['implied_cumulative_average_price'])

    def test_counter_reset_keeps_prices_but_disables_volume(self):
        data=minute_payload();lines=data['data']['sz000001']['data']['data'];parts=lines[7].split();parts[2]='1';lines[7]=' '.join(parts)
        row=parse_minutes(data,SPEC,NOW)
        self.assertEqual(row['status'],'ok');self.assertEqual(row['volume']['status'],'unavailable')
        self.assertIsNone(row['volume']['recent5_vs_previous5_interval_rate'])

    def test_lunch_gap_cannot_be_counted_as_one_minute_flow(self):
        data=minute_payload();node=data['data']['sz000001'];node['qt']['sz000001'][30]='20261028130330'
        for i,line in enumerate(node['data']['data']):
            clock=(datetime(2026,10,28,11,20)+timedelta(minutes=i)).strftime('%H%M') if i<10 else '130'+str(i-10)
            node['data']['data'][i]=clock+' '+line.split(' ',1)[1]
        row=parse_minutes(data,SPEC,datetime(2026,10,28,13,5))
        self.assertIsNone(row['volume']['recent5_vs_previous5_interval_rate'])

    def test_wrong_identity_date_or_stale_quote_rejected(self):
        data=minute_payload();data['data']['sz000001']['qt']['sz000001'][2]='999999'
        with self.assertRaises(ValueError):parse_minutes(data,SPEC,NOW)
        data=minute_payload();data['data']['sz000001']['data']['date']='20261027'
        with self.assertRaisesRegex(ValueError,'date_mismatch'):parse_minutes(data,SPEC,NOW)
        with self.assertRaises(ValueError):parse_minutes(minute_payload(),SPEC,datetime(2026,11,5,10))

    def test_clear_http_failure_does_not_repeat(self):
        response=requests.Response();response.status_code=403
        with tempfile.TemporaryDirectory() as root,patch('requests.get',return_value=response) as get:
            radar=IntradayRadar(root)
            with self.assertRaises(ValueError):radar.fetch(SPEC,time.monotonic()+5)
            with self.assertRaisesRegex(ValueError,'source_paused'):radar.fetch(SPEC,time.monotonic()+5)
            self.assertEqual(get.call_count,1)

    def test_current_date_is_not_sufficient_when_clock_stalls(self):
        with self.assertRaisesRegex(ValueError,'clock_stale'):parse_minutes(minute_payload(),SPEC,datetime(2026,10,28,11))
        with self.assertRaisesRegex(ValueError,'clock_stale'):parse_minutes(minute_payload(),SPEC,datetime(2026,10,29,8))


class BreadthTests(unittest.TestCase):
    def test_catalog_is_membership_only(self):
        rows=parse_catalog_page([dict(symbol='bj920000',code='920000',name='某公司',trade='wrong',ticktime='11:00')])
        self.assertEqual(set(rows[0]),{'symbol','name'})
        with self.assertRaises(ValueError):parse_catalog_page([dict(symbol='sh000001',code='000001')])

    def test_each_quote_requires_date_identity_and_consistent_pct(self):
        rows,bad=parse_dated_quotes(quote(),{'sh600001'},NOW)
        self.assertEqual(rows['sh600001']['as_of'],'2026-10-28T09:41:30')
        self.assertEqual(bad,{})
        for text in [quote(stamp='future'),quote(stamp='20261029094130'),quote().replace('~600001~','~600002~')]:
            rows,bad=parse_dated_quotes(text,{'sh600001'},NOW);self.assertEqual(rows,{})
        rows,bad=parse_dated_quotes(quote()+quote(),{'sh600001'},NOW)
        self.assertEqual(rows,{});self.assertIn('duplicate_symbol',bad)

    def rows(self,count=20):
        return {str(i):dict(as_of='2026-10-28T09:41:30',volume=100,price=10.1 if i%2 else 9.9,previous=10,pct=1 if i%2 else -1) for i in range(count)}

    def test_incomplete_page_never_becomes_market_breadth(self):
        result=summarize_breadth(dict(expected=100,observed_at=NOW.isoformat()),self.rows(20),NOW)
        self.assertEqual(result['status'],'unavailable');self.assertNotIn('distribution',result)

    def test_threshold_distribution_and_no_trade_not_flat(self):
        rows=self.rows();rows['0']['volume']=0
        result=summarize_breadth(dict(expected=20,observed_at=NOW.isoformat()),rows,NOW)
        self.assertEqual(result['status'],'ok_sampled')
        self.assertEqual(sum(result['distribution'][key] for key in ['advancing','declining','unchanged']),19)
        self.assertEqual(result['distribution']['unchanged'],0)
        rows['1']['as_of']='2026-10-27T15:00:00'
        self.assertEqual(summarize_breadth(dict(expected=20,observed_at='x'),rows,NOW)['status'],'unavailable')

    def test_too_wide_clock_span_not_published_as_synchronous(self):
        rows=self.rows();rows['0']['as_of']='2026-10-28T09:35:30'
        self.assertEqual(summarize_breadth(dict(expected=20,observed_at='x'),rows,NOW)['status'],'unavailable')

    def test_stop_scheduling_after_failure(self):
        visited=[]
        def fetch(i):
            visited.append(i)
            if i==2:raise ValueError('failed')
            return i
        with self.assertRaises(ValueError):bounded_map([1,2,3,4],fetch,1)
        self.assertEqual(visited,[1,2])

    def test_breadth_stale_source_clock_does_not_become_current_by_recollection(self):
        result=summarize_breadth(dict(expected=20,observed_at='x'),self.rows(),datetime(2026,10,28,11))
        self.assertEqual(result['status'],'unavailable');self.assertNotIn('distribution',result)

    def test_future_source_clock_cannot_become_valid_breadth(self):
        result=summarize_breadth(dict(expected=20,observed_at='x'),self.rows(),datetime(2026,10,28,9,40))
        self.assertEqual(result['status'],'unavailable')


class PromptTests(unittest.TestCase):
    def test_combined_snapshot_uses_time_alignment_not_just_same_collection(self):
        from app.services.microstructure import MicrostructureRadar
        minute=dict(instruments=[dict(symbol='sh000001',market='A',kind='index',status='ok',as_of='2026-10-28T09:40:00')],coverage={})
        for stamp,expected in [('2026-10-28T09:41:00','nearby_same_date'),('2026-10-27T15:00:00','not_aligned')]:
            with tempfile.TemporaryDirectory() as root,patch('app.services.microstructure.IntradayRadar.collect',return_value=minute), \
                    patch('app.services.microstructure.BreadthRadar.collect',return_value=dict(status='ok_sampled',as_of=stamp)):
                result=MicrostructureRadar(root).collect([])
                self.assertEqual(result['a_index_breadth_time_alignment'],expected)
                self.assertTrue(Path(root,'microstructure.json').is_file())

    def test_saved_prompt_filters_deleted_watchlist_and_no_network(self):
        data=dict(collected_at=NOW.isoformat(),watchlist=['sz000001'],limitation='覆盖有限',
            intraday=dict(instruments=[dict(symbol='sz000001',kind='watchlist',status='ok')]),breadth={'status':'unavailable'})
        with tempfile.TemporaryDirectory() as root,patch('requests.get',side_effect=AssertionError('no network')):
            Path(root,'microstructure.json').write_text(json.dumps(data),encoding='utf-8')
            text=prompt([],root,NOW)
            self.assertNotIn('"symbol":"sz000001"',text)
            self.assertIn('不是nearby_same_date',text)
            self.assertIn('没有有效近期快照',prompt([],root,NOW+timedelta(minutes=11)))

    def test_live_watchlist_symbols_are_dynamic(self):
        radar=IntradayRadar()
        with patch.object(radar,'fetch',side_effect=lambda spec,deadline:dict(**spec,status='ok')) as fetch:
            result=radar.collect([SimpleNamespace(code='12345',name='新公司',market='HK')])
        self.assertIn('hk12345',{r['symbol'] for r in result['instruments']})
        self.assertEqual(result['coverage']['requested'],3)


class AcceptanceToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_market_only_does_not_read_app_database(self):
        from app import microstructure_check as check
        from unittest.mock import AsyncMock
        with patch.object(check,'read_app_watchlist',AsyncMock(side_effect=AssertionError('no DB read'))) as read, \
                patch.object(check,'MicrostructureRadar') as factory:
            factory.return_value.collect.return_value={'coverage':{}}
            await check.inspect(True)
        read.assert_not_awaited()
        factory.return_value.collect.assert_called_once_with([],110)

    async def test_database_failure_does_not_use_stale_watchlist(self):
        from app import microstructure_check as check
        from unittest.mock import AsyncMock
        with patch.object(check,'read_app_watchlist',AsyncMock(side_effect=RuntimeError('DB unavailable'))), \
                patch.object(check,'MicrostructureRadar') as factory:
            with self.assertRaises(RuntimeError):await check.inspect(False)
        factory.assert_not_called()
