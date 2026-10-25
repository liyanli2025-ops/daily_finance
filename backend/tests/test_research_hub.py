from dataclasses import asdict
from datetime import datetime, timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock

from app.models.news import News
from app.services.evidence import validate_citations, source_notes
from app.services.research_hub import ResearchHub, Material, save_json, stock_key, tag_industry_news, recent_opinion
from app.services.research_schema import research_fields
from app.services.watchlist_service import WatchlistStock, WatchlistService
from app.services import research_documents as documents

NOW=datetime(2026,10,23,15)


class ResearchTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.hub=ResearchHub(self.folder.name)
        self.stock=WatchlistStock('123456','新关注公司','A')

    def test_business_fields_follow_new_company_not_a_fixed_stock_list(self):
        bank=research_fields('银行','提供存贷款服务')
        chip=research_fields('制造业','从事半导体封装材料')
        unknown=research_fields('新兴行业','尚未归入预设业务家族')
        self.assertIn('净息差',bank['fields'])
        self.assertNotIn('净息差',chip['fields'])
        self.assertIn('客户验证与量产',chip['fields'])
        self.assertIn('新兴行业',unknown['topics'])
        self.assertIn('经营现金流',unknown['fields'])

    def test_automotive_certification_does_not_assign_automaker_metrics(self):
        chip = research_fields('电子制造', '半导体封装材料，汽车电子质量管理体系认证')
        self.assertIn('半导体', chip['families'])
        self.assertNotIn('单车利润', chip['fields'])
        automaker = research_fields('汽车制造业', '新能源汽车整车制造')
        self.assertIn('单车利润', automaker['fields'])
        farm = research_fields('畜牧业','生猪养殖；食品生产销售。')
        self.assertNotIn('渠道与库存', farm['fields'])

    def test_opinion_windows_reject_old_missing_and_future_dates(self):
        for kind, days in [('company_research',30),('industry_research',7),('investor_relations',14)]:
            self.assertTrue(recent_opinion(kind, NOW-timedelta(days=days), NOW))
            self.assertFalse(recent_opinion(kind, NOW-timedelta(days=days,seconds=1), NOW))
            self.assertFalse(recent_opinion(kind, None, NOW))
            self.assertFalse(recent_opinion(kind, NOW+timedelta(seconds=1), NOW))

    def test_old_company_bodies_are_skipped_but_industry_metadata_remains_usable(self):
        rows=[dict(stockCode='123456',publishDate='2026-01-21',indvInduCode='42')]
        industry=dict(industryCode='42',publishDate='2026-10-22',title='封装材料近期变化')
        material=Mock(reading_status='full_text')
        with patch('app.services.research_hub.china_now',return_value=NOW), \
                patch.object(self.hub,'get_json',side_effect=[{'data':rows},{'data':[industry]}]), \
                patch.object(self.hub,'report_material',return_value=material) as read:
            items,status=self.hub.reports(self.stock,999999999,dict(industry='电子',topics=['封装']))
        self.assertEqual(items,[material])
        self.assertEqual(status['excluded_stale_company_reports'],1)
        self.assertEqual(status['recent_company_reports'],0)
        self.assertEqual(read.call_count,1)
        self.assertTrue(read.call_args.kwargs['industry'])

    def test_broad_provider_industry_does_not_insert_unrelated_eda_report_for_packaging(self):
        rows=[dict(stockCode='123456',publishDate='2026-01-21',indvInduCode='42')]
        industry=dict(industryCode='42',publishDate='2026-10-22',title='EDA产业生态重构')
        with patch('app.services.research_hub.china_now',return_value=NOW), \
                patch.object(self.hub,'get_json',side_effect=[{'data':rows},{'data':[industry]}]), \
                patch.object(self.hub,'report_material') as read:
            items,_=self.hub.reports(self.stock,999999999,dict(industry='电子',topics=['封装','塑封料']))
        self.assertEqual(items,[])
        read.assert_not_called()

    def test_prompt_rejects_old_cached_opinions_and_citation_ids_but_keeps_financial_baseline(self):
        materials=[]
        for kind in ['company_research','industry_research','investor_relations','financial_baseline']:
            material=Material(kind,kind,'来源','https://example.com',kind,'A:123456',
                              '旧文正文不应入模',datetime(2026,1,1),NOW.isoformat())
            materials.append({**asdict(material),'published_at':'2026-01-01'})
        context=dict(key='A:123456',name='测试',profile=None,coverage={},materials=materials)
        with patch.object(self.hub,'load',return_value=[context]), \
                patch('app.services.research_hub.china_now',return_value=NOW):
            prompt,evidence=self.hub.prompt([self.stock])
        self.assertEqual([item.kind for item in evidence],['financial_baseline'])
        self.assertNotIn('[N:company_research]',prompt)
        with self.assertRaises(RuntimeError):
            validate_citations('[N:company_research]',evidence)

    def test_profile_checks_provider_stock_identity(self):
        row=dict(SecurityCode='654321',jbzl={'agdm':'654321','gsmc':'错误公司','sshy':'银行','gsjj':'业务'})
        with patch.object(self.hub,'get_json',return_value=row),self.assertRaisesRegex(ValueError,'identity'):
            self.hub.profile(self.stock,999999999)

    def test_profile_of_arbitrary_new_stock_drives_industry_and_tasks(self):
        row=dict(SecurityCode='123456',jbzl={'agdm':'123456','gsmc':'新关注公司','sshy':'银行','gsjj':'商业银行业务'})
        with patch.object(self.hub,'get_json',return_value=row):
            profile=self.hub.profile(self.stock,999999999)
        self.assertEqual(profile['key'],'A:123456')
        self.assertIn('净息差',profile['fields'])
        self.assertTrue(profile['relationships'][0]['source_url'])
        service=WatchlistService()
        service.load_from_database([dict(code='123456',name='新关注公司',market='A')])
        service.apply_research_profiles({'A:123456':profile})
        self.assertEqual(service.get_unique_sectors(),['银行'])

    def test_cache_is_market_scoped_and_expires(self):
        fetch=Mock(return_value={'value':1})
        with patch('app.services.research_hub.china_now',return_value=NOW):
            self.hub.cache('A:123456',60,fetch)
            self.hub.cache('A:123456',60,fetch)
            self.hub.cache('HK:12345',60,fetch)
        self.assertEqual(fetch.call_count,2)
        with patch('app.services.research_hub.china_now',return_value=NOW+timedelta(seconds=61)):
            self.hub.cache('A:123456',60,fetch)
        self.assertEqual(fetch.call_count,3)

    def test_removed_stock_context_cannot_leak_into_current_watchlist(self):
        context=dict(key='A:123456',name='旧股票',collected_at=NOW.isoformat(),profile=None,
                     materials=[],coverage={'financial':{'status':'ok'}})
        save_json(Path(self.folder.name)/'stocks/A-123456.json',context)
        with patch('app.services.research_hub.china_now',return_value=NOW):
            loaded=self.hub.load([WatchlistStock('654321','新股票','A')])
        self.assertEqual([item['key'] for item in loaded],['A:654321'])
        self.assertEqual(loaded[0]['coverage']['collection']['status'],'not_collected')

    def test_future_financials_wrong_company_and_missing_numbers_are_excluded(self):
        rows=[dict(SECURITY_CODE='123456',REPORT_DATE='2026-06-30',NOTICE_DATE='2026-08-01',CURRENCY='CNY',TOTALOPERATEREVE=123),
              dict(SECURITY_CODE='123456',REPORT_DATE='2026-09-30',NOTICE_DATE='2026-10-25',TOTALOPERATEREVE=999),
              dict(SECURITY_CODE='654321',REPORT_DATE='2026-06-30',TOTALOPERATEREVE=888)]
        with patch.object(self.hub,'get_json',return_value={'result':{'data':rows}}), \
                patch('app.services.research_hub.china_now',return_value=NOW):
            items=self.hub.financial(self.stock,999999999)
        self.assertEqual(len(items),1)
        self.assertIn('123',items[0].body)
        self.assertNotIn('999',items[0].body)
        self.assertEqual(items[0].published_at,datetime(2026,8,1))

    def test_missing_hk_publication_date_is_not_invented_from_period_end(self):
        row=dict(SECURITY_CODE='00700',REPORT_DATE='2026-06-30',CURRENCY='CNY',OPERATE_INCOME=100)
        with patch.object(self.hub,'get_json',return_value={'result':{'data':[row]}}):
            material=self.hub.financial(WatchlistStock('00700','腾讯','HK'),999999999)[0]
        self.assertIsNone(material.published_at)
        self.assertIn('不能推断发布日期',material.prompt())
        self.assertIn('CNY',material.body)
        self.assertIn('来源未提供',source_notes([material]))

    def test_prompt_preserves_different_material_types_and_only_citable_provided_ids(self):
        kinds=['financial_baseline','financial_report','investor_relations','company_research','industry_research']
        materials=[]
        for i,kind in enumerate(kinds):
            item=Material(str(i),kind,'测试来源','https://example.com/doc/'+str(i),kind,'A:123456',
                          '测试原文'*1800,datetime.now(),datetime.now().isoformat())
            materials.append({**asdict(item),'published_at':item.published_at.isoformat()})
        context=dict(key='A:123456',name='新关注公司',profile=None,coverage={},materials=materials)
        with patch.object(self.hub,'load',return_value=[context]):
            prompt,evidence=self.hub.prompt([self.stock],max_characters=8000)
        self.assertEqual({item.kind for item in evidence},set(kinds))
        self.assertLessEqual(len(prompt),8200)
        for item in evidence:
            self.assertIn('[N:'+item.id+']',prompt)
        self.assertIn('历史资料保留原日期',prompt)
        validate_citations('[N:3]',evidence)
        with self.assertRaises(RuntimeError):
            validate_citations('[N:omitted]',evidence)

    def test_industry_match_does_not_mark_company_as_confirmed_beneficiary(self):
        news=News(id='n',title='猪价变化',content='行业新闻',source='测试',published_at=NOW)
        tag_industry_news([news],[dict(key='A:123456',topics=['猪价'])])
        self.assertIn('不证明该公司受益',news.market_impact)
        self.assertEqual(news.related_stocks,[])
        self.assertEqual(news.beneficiary_sectors,[])

    def test_reports_with_wrong_company_do_not_trigger_document_download(self):
        with patch.object(self.hub,'get_json',return_value={'data':[dict(stockCode='654321',publishDate='2026-10-22')]}), \
                patch.object(self.hub,'report_material') as read:
            materials,status=self.hub.reports(self.stock,999999999,None)
        self.assertEqual(materials,[])
        read.assert_not_called()

    def test_pdf_fake_html_is_rejected_even_if_content_type_says_pdf(self):
        response=Mock(status_code=200)
        response.__enter__=Mock(return_value=response)
        response.__exit__=Mock(return_value=False)
        response.iter_content.return_value=[b'<script>not a PDF</script>']
        with patch.object(documents,'pdf_ready',return_value=True),patch.object(documents.requests,'get',return_value=response), \
                self.assertRaisesRegex(ValueError,'不是PDF'):
            documents.read_pdf('https://pdf.dfcfw.com/pdf/test.pdf')

    def test_pdf_source_whitelist_blocks_external_or_private_destinations(self):
        with patch.object(documents.requests,'get') as get,self.assertRaises(ValueError):
            documents.read_pdf('http://127.0.0.1/private')
        get.assert_not_called()

    def test_future_appointment_is_a_plan_and_not_a_fabricated_publication_date(self):
        response=Mock(status_code=200)
        response.json.return_value={'prbookinfos':[dict(seccode='123456',f001d_0102='2026-09-30',
                                   f002d_0102='2026-10-30',f003d_0102='2026-10-28')]}
        with patch('app.services.research_hub.china_now',return_value=NOW), \
                patch('app.services.research_hub.requests.post',return_value=response):
            items,status=self.hub.calendar(self.stock,999999999)
        self.assertEqual(status['status'],'ok')
        self.assertIn('2026-10-28',items[0].body)
        self.assertIn('预约不是已经披露',items[0].body)
        self.assertIsNone(items[0].published_at)

    def test_pdf_failure_falls_back_to_labelled_report_excerpt_not_full_pdf(self):
        identifier='AP12345'
        response=Mock(status_code=200,text='<a class="pdf-link" href="https://pdf.dfcfw.com/pdf/H3_AP12345_1.pdf"></a>'
                      '<div class="ctx-content">'+'机构的历史预测，未经独立核实。'*20+'</div>')
        with patch.object(self.hub,'pdf_document',return_value=(None,'ValueError')), \
                patch('app.services.research_hub.requests.get',return_value=response):
            item=self.hub.report_material(dict(infoCode=identifier,title='研报',publishDate='2026-08-01'),
                                          'A:123456',999999999,False)
        self.assertIn('PDF未读取',item.reading_status)
        self.assertIn('仅为发布页研报节选',item.body)
        self.assertEqual(item.published_at,datetime(2026,8,1))


class BudgetTests(unittest.IsolatedAsyncioTestCase):
    async def test_every_watchlist_stock_gets_an_explicit_result_even_if_deferred(self):
        with tempfile.TemporaryDirectory() as folder:
            hub=ResearchHub(folder)
            stocks=[WatchlistStock(str(i).zfill(6),'动态股票'+str(i),'A') for i in range(12)]
            result=await hub.collect(stocks,budget=0)
            self.assertEqual(len(result['stocks']),12)
            self.assertTrue(all(item['coverage']['collection']['status']=='deferred' for item in result['stocks']))
            self.assertEqual(len(hub.load(stocks)),12)
