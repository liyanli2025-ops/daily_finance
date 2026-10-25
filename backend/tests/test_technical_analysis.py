import unittest
from app.services.technical_analysis import macd,dmi,confirmed_pivots,daily_analysis


def bars(prices):
    return [dict(date=f'bar-{i:03}',close=value,high=value+1,low=value-1,volume=100) for i,value in enumerate(prices)]


class TechnicalFamilyTests(unittest.TestCase):
    def test_macd_warmup_constant_and_cross_availability(self):
        self.assertEqual(macd([10]*33)['status'],'warming_up')
        result=macd([10]*34)
        self.assertEqual(result['histogram'],0);self.assertIsNone(result['cross_up'])
        self.assertFalse(macd([10]*35)['cross_up'])

    def test_wilder_adx_strength_and_direction(self):
        result=dmi(bars(list(range(10,60))))
        self.assertEqual(result['adx14'],100)
        self.assertGreater(result['plus_di'],0);self.assertEqual(result['minus_di'],0)
        reverse=dmi(bars(list(range(60,10,-1))))
        self.assertEqual(reverse['adx14'],100);self.assertEqual(reverse['plus_di'],0)
        self.assertEqual(dmi(bars(list(range(10,37))))['status'],'warming_up')

    def test_flat_prices_have_no_fake_band_position_and_index_volume(self):
        result=daily_analysis(bars([10]*70),dict(ma20=10,ma60=10,atr14=2),False)
        self.assertIsNone(result['families']['volatility']['bollinger20']['percent_b'])
        self.assertEqual(result['families']['volume_price']['status'],'unavailable')
        self.assertEqual(result['families']['momentum']['histogram'],0)
        self.assertEqual(result['regime'],'range_candidate')

    def test_pivot_is_only_available_two_bars_after_point(self):
        sample=bars([10,11,15,12,11])
        self.assertEqual(confirmed_pivots(sample[:4])['last_highs'],[])
        pivot=confirmed_pivots(sample)['last_highs'][0]
        self.assertEqual(pivot['point_date'],'bar-002');self.assertEqual(pivot['confirmed_at'],'bar-004')
        self.assertEqual(confirmed_pivots(bars([10]*10))['last_highs'],[])

    def test_daily_volume_is_not_presented_as_vwap_or_fund_flow(self):
        result=daily_analysis(bars(list(range(10,80))),dict(ma20=69.5,ma60=49.5,atr14=2),True)
        volume=result['families']['volume_price']
        self.assertEqual(volume['vwma20_close'],69.5)
        self.assertEqual(volume['signed_volume_balance20'],1)
        self.assertEqual(result['regime'],'uptrend_candidate')
