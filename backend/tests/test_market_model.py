from copy import deepcopy
from datetime import date,timedelta
import json
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
from unittest.mock import patch

from app.services.market_model import build,calculate,compact
from app.market_model_check import inspect


def series(symbol,returns,kind='watchlist',market='A'):
    days=[];day=date(2026,1,1)
    while len(days)<len(returns)+1:
        if day.weekday()<5:days.append(day.isoformat())
        day+=timedelta(days=1)
    prices=[100.0]
    for value in returns:prices.append(prices[-1]*(1+value/100))
    return dict(symbol=symbol,kind=kind,market=market,status='ok',
        adjustment='index_unadjusted' if kind=='index' else 'provider_qfq',
        source_url='https://example.com/daily',observed_at=days[-1]+'T18:00:00',
        metrics=dict(as_of=days[-1]),bars=[dict(date=day,close=price,volume=1000)
            for day,price in zip(days,prices)])


class MarketModelTests(unittest.TestCase):
    def setUp(self):
        self.x=[(i%11-5)*.15 for i in range(145)]
        self.y=[.03+1.6*x+(.8 if i>=140 else 0) for i,x in enumerate(self.x)]
        self.index=series('sh000300',self.x,'index')
        self.stock=series('sh123456',self.y)

    def test_known_linear_model_and_disjoint_windows(self):
        result=calculate(self.stock,self.index)
        self.assertEqual(result['status'],'holdout_better_than_naive')
        self.assertAlmostEqual(result['estimation']['beta'],1.6)
        self.assertAlmostEqual(result['estimation']['alpha_daily_pp'],.03)
        self.assertAlmostEqual(result['estimation']['estimation_r_squared'],1)
        self.assertAlmostEqual(result['recent']['sum_abnormal_returns_pp'],4)
        self.assertEqual(result['estimation']['observations'],120)
        self.assertEqual(result['holdout']['observations'],20)
        self.assertEqual(result['recent']['observations'],5)
        self.assertLess(result['estimation']['last_return_date'],result['holdout']['first_return_date'])
        self.assertLess(result['holdout']['last_return_date'],result['recent']['first_return_date'])
        self.assertFalse(result['future_return_prediction_supported'])
        self.assertEqual(result['event_association'],'not_established')

    def test_recent_data_never_refits_estimation_or_holdout(self):
        changed=series('sh123456',self.y[:140]+[5]*5)
        original=calculate(self.stock,self.index);new=calculate(changed,self.index)
        self.assertEqual(original['estimation'],new['estimation'])
        self.assertEqual(original['holdout'],new['holdout'])
        self.assertNotEqual(original['recent'],new['recent'])

    def test_bad_holdout_suppresses_residual_and_coefficients_in_prompt(self):
        changed=series('sh123456',self.y[:120]+self.x[120:140]+self.y[140:])
        result=build([self.index,changed]);row=result['instruments'][0]
        self.assertEqual(row['estimation'],calculate(self.stock,self.index)['estimation'])
        self.assertEqual(row['status'],'diagnostic_only')
        reduced=compact(result)['instruments'][0]
        self.assertNotIn('recent',reduced);self.assertNotIn('estimation',reduced)
        self.assertIn('restriction',reduced)
        self.assertIn('recent',row)

    def test_no_fill_for_missing_internal_date(self):
        self.stock['bars'][-6]['date']='2026-07-11'
        with self.assertRaises(ValueError):calculate(self.stock,self.index)

    def test_short_history_flat_benchmark_and_zero_volume(self):
        short=deepcopy(self.stock);short['bars']=short['bars'][1:]
        with self.assertRaisesRegex(ValueError,'146'):calculate(short,self.index)
        flat=series('sh000300',[0]*145,'index')
        with self.assertRaisesRegex(ValueError,'variation'):calculate(self.stock,flat)
        self.stock['bars'][100]['volume']=0
        with self.assertRaisesRegex(ValueError,'volume'):calculate(self.stock,self.index)

    def test_same_market_dynamic_identity_and_explicit_failures(self):
        hk=series('hk01234',self.y,market='HK')
        self.assertEqual(build([self.index,hk])['instruments'][0]['reason'],'same_market_benchmark_unavailable')
        hsi=series('hkHSI',self.x,'index','HK')
        self.assertEqual(build([hsi,hk])['instruments'][0]['status'],'holdout_better_than_naive')
        self.assertEqual(build([self.stock,self.stock])['reason'],'duplicate_instrument_identity')
        self.assertEqual(build([{}])['reason'],'instrument_identity_missing')
        self.assertEqual(compact(build([{}]))['reason'],'instrument_identity_missing')

    def test_readonly_replay_has_no_network_or_writes(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'snapshot.json'
            path.write_text(json.dumps(dict(collected_at='historical',instruments=[self.index,self.stock])),encoding='utf-8')
            before=path.read_bytes()
            with patch('httpx.AsyncClient',side_effect=AssertionError('network forbidden')):
                result=inspect(path)
            self.assertEqual(path.read_bytes(),before)
            self.assertEqual(list(Path(folder).iterdir()),[path])
            self.assertEqual(result['snapshot_collected_at'],'historical')
            self.assertNotIn('daily',result['prompt_context']['instruments'][0]['recent'])

    def test_pure_model_import_does_not_bootstrap_app_or_audio(self):
        result=subprocess.run([sys.executable,'-c',
            "from app.services.market_model import build; import sys; assert 'app.config' not in sys.modules; assert 'app.services.scheduler' not in sys.modules; assert 'app.services.podcast_generator' not in sys.modules; print('ready')"],capture_output=True,text=True,check=True)
        self.assertEqual(result.stdout.strip(),'ready')
        self.assertEqual(result.stderr,'')


if __name__=='__main__':unittest.main()
