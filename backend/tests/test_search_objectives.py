from datetime import datetime
import unittest
from unittest.mock import Mock,patch

from app.services.search_objectives import request_profile,assess,infer_purpose,executed_coverage
from app.services.primary_discovery import unsupported_page

NOW=datetime(2026,10,31,15,36)


class ObjectiveTests(unittest.TestCase):
    def test_close_query_gets_year_and_absolute_date_hint_not_a_fabricated_session(self):
        query,options=request_profile('美股收盘 道指 标普 纳指 10月30日','latest_close',NOW)
        self.assertTrue(query.endswith('2026'));self.assertEqual(options['start_date'],'2026-10-28')
        self.assertEqual(options['end_date'],'2026-11-01');self.assertTrue(options['filter_by_published_date'])
        self.assertIn('instagram.com',options['exclude_domains'])
        self.assertNotIn('trading_date',options)

    def test_commentary_keeps_discussion_discovery_open(self):
        query,options=request_profile('AI融资 投资者分歧','commentary',NOW)
        self.assertEqual(query,'AI融资 投资者分歧');self.assertEqual(options,{})

    def test_explicit_year_not_silently_replaced(self):
        query,_=request_profile('2026-10-30 Wall Street closing stocks','latest_close',NOW)
        self.assertEqual(query,'2026-10-30 Wall Street closing stocks')

    def test_social_source_is_a_lead_not_deleted_or_read_as_article(self):
        result=assess(dict(title='Instagram',url='https://www.instagram.com/p/example'),'latest_close','us_market')
        self.assertIn('social_or_video_needs_platform_reader',result['flags'])
        self.assertEqual(result['role'],'lead_needs_body_check')
        self.assertIsNotNone(unsupported_page('https://www.youtube.com/watch?v=example'))

    def test_pre_market_not_verified_close_but_preserved_for_time_line(self):
        result=assess(dict(title='【美股10月29日盘前必看分析】谷歌财报拖累科技股',url='https://example.com/news/1'),'latest_close','us_market')
        self.assertIn('session_or_rolling_update_needs_body_check',result['flags'])
        self.assertFalse(result['event_or_session_verified'])

    def test_rolling_update_not_discarded_just_because_title_says_open(self):
        result=assess(dict(title='A股三大指数集体低开，恒科指涨1%',url='https://example.com/news/1'),'latest_close','a_market')
        self.assertEqual(result['role'],'lead_needs_body_check')
        self.assertNotIn('discard',str(result))

    def test_monthly_return_not_treated_as_daily_return(self):
        result=assess(dict(title='港股收盘：科技指数创年内单月最大跌幅',url='https://example.com/news/1'),'latest_close','hk_market')
        self.assertIn('monthly_period_not_daily_return_needs_body_check',result['flags'])

    def test_korean_move_not_us_close_confirmation(self):
        result=assess(dict(title='AI投资回报存疑，韩股下跌1.4%，三星跌超4%',url='https://example.com/news/1'),'latest_close','us_market')
        self.assertIn('different_market_primary_subject_hint',result['flags'])

    def test_policy_forecast_retained_but_not_confirmation(self):
        for title in ('日本央行“鹰派暂停”只差官宣','美联储本周决议将风平浪静？高盛预测'):
            result=assess(dict(title=title,url='https://example.com/news/1'),'released_policy','global_policy')
            self.assertIn('forecast_or_commentary_not_release_confirmation',result['flags'])
        release=assess(dict(title='Federal Reserve issues FOMC statement',url='https://example.com/news/1'),'released_policy','global_policy')
        self.assertNotIn('forecast_or_commentary_not_release_confirmation',release['flags'])

    def test_execution_ledger_not_model_claimed_coverage(self):
        receipts=[dict(request=dict(tool='search',lane='a_market',query='A股收盘'),result=dict(status='ok'))]
        ledger=executed_coverage(receipts,[dict(market='A',code='300750',name='动态股')])
        self.assertIn('us_market',ledger['lanes_without_search_receipts'])
        self.assertEqual(ledger['stocks_without_scoped_search_receipts'],['A:300750'])

    def test_invalid_purpose_rejected_before_requests(self):
        with self.assertRaises(ValueError):request_profile('市场','unknown',NOW)

    def test_missing_purpose_has_auditable_fallback(self):
        self.assertEqual(infer_purpose('美股收盘 纳指 10月30日','us_market'),'latest_close')
        self.assertEqual(infer_purpose('谷歌 亚马逊 财报','us_market'),'company_event')
        self.assertEqual(infer_purpose('央行本周决议','global_policy'),'released_policy')
        self.assertEqual(infer_purpose('机构预测政策','global_policy'),'commentary')
