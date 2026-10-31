"""Non-destructive evidence warnings; no claims of semantic classification."""
from datetime import datetime
import unittest
from unittest.mock import AsyncMock, patch

from app.models.news import News
from app.services.primary_material_quality import review_body, followup_plan
from app.services.primary_report import PrimaryReportService, fingerprint


class BodyQualityTests(unittest.TestCase):
    def test_promotional_tail_is_located_without_discarding_counter_evidence(self):
        text='公司盈利改善，但现金流转差，需要进一步核对。'*8+'\nA 级｜上涨\nB 级｜持平\nC 级｜回撤\n限量周边冰箱贴，把快乐带回家！'
        result=review_body(text)
        self.assertTrue(result['requires_editorial_review'])
        self.assertFalse(result['text_modified'])
        self.assertIn('reader_poll_choices',{r['code'] for r in result['findings']})
        for finding in result['findings']:
            self.assertTrue(0<=finding['start']<finding['end']<=len(text))
        self.assertIn('现金流转差',text)

    def test_financial_buy_language_and_risk_disclaimers_are_not_promotion(self):
        result=review_body('机构维持买入评级，购买订单增长，但订阅收入下降。价格与库存出现分歧。以上不构成投资建议。')
        self.assertFalse(result['requires_editorial_review'])

    def test_one_company_is_not_automatically_counted_as_industry(self):
        item=News(id='source1',title='某公司财报',content='营业收入增加。'*20,
                  source='公开网页可见正文-公司',source_url='https://example.com/report',published_at=datetime(2026,10,31))
        plan=followup_plan([item],{'intake':{'declared_body_coverage':{'company_event':['source1']}}})
        self.assertIn('industry',[t['lane'] for t in plan['tasks']])
        self.assertNotIn('company_event',[t['lane'] for t in plan['tasks']])
        self.assertEqual(plan['requests_performed'],0)

    def test_suspect_quote_is_flagged_for_review_not_silently_deleted(self):
        text='报道揭露广告骗局，文中引述：“立即抢购”。不要扫描不明二维码。'
        self.assertTrue(review_body(text)['requires_editorial_review'])


class ReportAdmissionTests(unittest.IsolatedAsyncioTestCase):
    async def test_promotion_stops_before_app_and_paid_generation(self):
        now=datetime(2026,10,31,16)
        value=dict(owner='finance-search-primary-v1',collected_at=now.isoformat(),watchlist=[],
                   search_receipts=[dict(query='查市场事实',checked_at=now.isoformat(),status='ok')],
                   articles=[dict(title='市场事实与推广',body='市场公开事实需独立核对。'*12+'立即下单',
                       url='https://example.com/report',source_name='example',body_scope='visible_body',
                       observed_at=now.isoformat(),published_at='2026-10-31T15:00:00+08:00',
                       publication_precision='second',lanes=['a_market'])])
        with patch('app.services.model_gateway.ensure_models_enabled'), \
             patch('app.services.primary_report.china_now',return_value=now), \
             patch('app.config.settings.model_http_retries',0), \
             patch('app.config.settings.report_auto_repair_enabled',False), \
             patch('app.services.watchlist_repository.assert_watchlist_current',new_callable=AsyncMock) as app:
            with self.assertRaisesRegex(RuntimeError,'body_quality_review_required'):
                await PrimaryReportService().generate(value,fingerprint(value))
            app.assert_not_awaited()

    def test_boc_container_keeps_attribution_and_no_timezone_guess(self):
        from app.services.web_research import parse_visible_article
        html='<article class="content_page"><h2 class="title">金市观察与市场数据</h2><h3 class="time">2026-10-30 13:57:28</h3>'
        html+='<section id="BOC_CONTENT_SECTION">'+('上一交易日的现货价格与单位。'*12)+'免责声明：观点仅代表作者。</section></article><aside>推荐商品</aside>'
        item=parse_visible_article(html,'https://wap.boc.cn/bif/bi7/202610/t20261030_123.html',datetime(2026,10,31,16))
        self.assertIn('观点仅代表作者',item.content)
        self.assertNotIn('推荐商品',item.content)
        self.assertIn('来源未标时区',item.market_impact)
