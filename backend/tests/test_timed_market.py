from datetime import datetime, date, timedelta
import unittest
from unittest.mock import patch, AsyncMock

import httpx

from app.services import timed_market, model_gateway
from app.services.market_data_service import MarketDataService, MarketOverview, IndexData

NOW=datetime(2026,10,25,8)


def quote(symbol='sh000001',code='000001',stamp='20261023161500',current='3690.48',previous='3658.03',change='32.45',pct='0.89'):
    fields=['']*40
    for index,value in [(1,'来源名称'),(2,code),(3,current),(4,previous),(30,stamp),(31,change),(32,pct)]:
        fields[index]=value
    return 'v_'+symbol+'="'+'~'.join(fields)+'";'


class TimedQuoteTests(unittest.TestCase):
    def test_quote_uses_real_change_not_previous_close_and_keeps_friday_timestamp(self):
        rows=timed_market.parse_quotes(quote(),NOW)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['change'],32.45)
        self.assertEqual(rows[0]['as_of'],'2026-10-23T16:15:00')
        self.assertNotIn('2026-10-25',rows[0]['as_of'])

    def test_wrong_identity_missing_future_old_time_nan_and_inconsistent_change_are_excluded(self):
        for bad in [quote(code='399001'),quote(stamp=''),quote(stamp='20261026150000'),
                    quote(stamp='20260101150000'),quote(current='nan'),quote(change='3658.03'),quote(pct='5')]:
            self.assertEqual(timed_market.parse_quotes(bad,NOW),[])

    def test_hong_kong_and_us_clock_formats_preserve_identity_without_inventing_timezone(self):
        raw=quote('hkHSI','HSI','2026/10/23 18:31:07')+quote('usINX','.INX','2026-10-23 16:38:21')
        rows=timed_market.parse_quotes(raw,NOW)
        self.assertEqual([row['region'] for row in rows],['港股','美股'])
        self.assertTrue(all('不作跨市场时点对齐' in row['time_basis'] for row in rows))

    def test_prompt_does_not_emit_untimed_index_or_invent_zero_turnover(self):
        overview=MarketOverview(date='2026-10-25',indices=[IndexData('000001','不可信',3000,1,1)])
        self.assertNotIn('不可信：3000',overview.to_prompt_text())
        overview.indices[0].as_of='2026-10-23T16:15:00'
        overview.indices[0].source='测试源'
        text=overview.to_prompt_text()
        self.assertIn('2026-10-23',text)
        self.assertNotIn('成交额 0亿',text)

    def test_billing_error_is_classified_without_leaking_response_secrets(self):
        response=httpx.Response(402,json={'error':{'code':'insufficient_balance','message':'balance low secret-key-abc'}})
        text=str(model_gateway.service_error('analysis',response))
        self.assertIn('余额或额度不足',text)
        self.assertNotIn('secret-key-abc',text)
        unknown=str(model_gateway.service_error('analysis',httpx.Response(402,json={'error':'other'})))
        self.assertIn('未提供可确认',unknown)


class MarketPathTests(unittest.IsolatedAsyncioTestCase):
    async def test_report_path_never_calls_unverified_legacy_adapters(self):
        service=MarketDataService.__new__(MarketDataService)
        service._get_consecutive_limit_stocks=AsyncMock(side_effect=AssertionError('must not call'))
        service._get_block_trades=AsyncMock(side_effect=AssertionError('must not call'))
        rows=timed_market.parse_quotes(quote(),NOW)
        with patch.object(timed_market,'china_today',return_value=NOW.date()), \
                patch.object(timed_market,'fetch_quotes',return_value=rows):
            overview=await service.get_market_overview(NOW.date())
        self.assertEqual(len(overview.indices),1)
        self.assertEqual(overview.consecutive_limit_stocks,[])
        self.assertEqual(overview.block_trades,[])
        self.assertEqual(overview.source_status['连板股']['status'],'disabled_unverified')
        service._get_consecutive_limit_stocks.assert_not_called()
        service._get_block_trades.assert_not_called()

    async def test_historical_target_does_not_read_present_quotes(self):
        with patch.object(timed_market,'china_today',return_value=NOW.date()), \
                patch.object(timed_market,'fetch_quotes') as fetch:
            result=await timed_market.collect_overview(date(2025,1,1))
        fetch.assert_not_called()
        self.assertEqual(result.source_status['指数']['status'],'unsupported')

    async def test_failed_request_does_not_fabricate_market_data(self):
        with patch.object(timed_market,'china_today',return_value=NOW.date()), \
                patch.object(timed_market,'fetch_quotes',side_effect=ConnectionError()):
            result=await timed_market.collect_overview(NOW.date())
        self.assertEqual(result.indices,[])
        self.assertEqual(result.source_status['指数']['status'],'failed')

    async def test_402_stops_without_retry_or_fallback(self):
        from app.config import Settings
        config=Settings(_env_file=None,openai_api_key='fixture',ai_model='fixture-model',
                        openai_base_url='https://example.com/v1')
        count=0
        def handler(request):
            nonlocal count
            count+=1
            return httpx.Response(402,json={'error':{'code':'insufficient_balance'}})
        original=model_gateway.httpx.AsyncClient
        with patch.object(model_gateway,'settings',config), \
                patch.object(model_gateway.httpx,'AsyncClient',side_effect=lambda **kw:original(transport=httpx.MockTransport(handler),**kw)):
            with self.assertRaisesRegex(RuntimeError,'HTTP 402'):
                await model_gateway.complete('analysis',[{'role':'user','content':'test'}],64)
        self.assertEqual(count,1)
