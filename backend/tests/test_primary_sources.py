from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from app.services import primary_sources as primary
from app.services.research_hub import ResearchHub
from app.services.watchlist_service import WatchlistStock

NOW=datetime(2026,10,25,8)


class PrimarySourceTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.hub=ResearchHub(self.temporary.name)
        self.stock=WatchlistStock('003456','测试公司','A')
        self.deadline=time.monotonic()+30

    def profile(self, family):
        return dict(key='A:123456',families=[family])

    def notice(self, title, date, code='003456', org='issuer1'):
        return dict(secCode=code,orgId=org,announcementTitle=title,announcementId='12345',
                    adjunctUrl='finalpage/'+date+'/12345.PDF',
                    announcementTime=datetime.fromisoformat(date).replace(tzinfo=timezone(timedelta(hours=8))).timestamp()*1000)

    def identities(self):
        return dict(stockList=[dict(code='003456',category='A股',orgId='issuer1',zwjc='测试公司')])

    def pdf(self,text='证券代码003456 测试公司 原始经营披露正文'):
        return dict(pages=[dict(page=1,text=text*6)],reading_status='full_text')

    def article(self, title='最新规模以上工业增加值情况', date='2026/10/19 10:00', body=None):
        body=body or '集成电路及电子设备制造业的统计口径为行业总体，并不是任何一家公司的订单。'*5
        return '<meta name="ArticleTitle" content="'+title+'"><meta name="PubDate" content="'+date+'"><div class="trs_editor_view"><p>'+body+'</p></div>'

    def test_tasks_follow_business_without_a_fixed_stock_code_list(self):
        self.assertEqual(primary.government_tasks(self.profile('半导体')),['nbs_industry'])
        self.assertIn('moa',primary.government_tasks(self.profile('养殖')))
        self.assertIn('nbs_energy',primary.government_tasks(self.profile('电力')))
        self.assertEqual(primary.government_tasks(self.profile('新行业')),[])

    def test_issuer_filter_rejects_wrong_company_and_org_before_download(self):
        rows=[self.notice('重大合同','2026-10-24',code='654321'),self.notice('重大合同','2026-10-24',org='wrong')]
        with patch.object(primary,'get_json',side_effect=[self.identities(),dict(announcements=rows)]), \
                patch.object(primary,'china_now',return_value=NOW),patch.object(primary,'read_pdf') as read:
            items,status=primary.cninfo_notices(self.hub,self.stock,self.deadline)
        self.assertEqual(items,[])
        self.assertEqual(status['excluded'],2)
        read.assert_not_called()

    def test_current_month_operating_release_is_baseline_not_today_news(self):
        rows=[self.notice('2026年9月份销售简报','2026-10-12'),self.notice('旧重大合同','2026-10-01')]
        with patch.object(primary,'get_json',side_effect=[self.identities(),dict(announcements=rows)]), \
                patch.object(primary,'china_now',return_value=NOW),patch.object(primary,'read_pdf',return_value=self.pdf()) as read:
            items,status=primary.cninfo_notices(self.hub,self.stock,self.deadline)
        self.assertEqual(len(items),1)
        self.assertEqual(items[0].kind,'operating_release')
        self.assertIn('不能重包装成今日新闻',items[0].body)
        self.assertEqual(items[0].published_at,datetime(2026,10,12))
        self.assertIn('日期粒度',items[0].reading_status)
        self.assertEqual(read.call_count,1)

    def test_future_and_old_operating_releases_are_not_downloaded(self):
        rows=[self.notice('销售简报','2026-10-26'),self.notice('销售简报','2026-09-01')]
        with patch.object(primary,'get_json',side_effect=[self.identities(),dict(announcements=rows)]), \
                patch.object(primary,'china_now',return_value=NOW),patch.object(primary,'read_pdf') as read:
            items,_=primary.cninfo_notices(self.hub,self.stock,self.deadline)
        self.assertEqual(items,[])
        read.assert_not_called()

    def test_original_pdf_identity_failure_is_partial_not_success(self):
        with patch.object(primary,'get_json',side_effect=[self.identities(),dict(announcements=[self.notice('重大合同','2026-10-24')])]), \
                patch.object(primary,'china_now',return_value=NOW),patch.object(primary,'read_pdf',return_value=self.pdf('其他企业654321')):
            items,status=primary.cninfo_notices(self.hub,self.stock,self.deadline)
        self.assertEqual(items,[])
        self.assertEqual(status['status'],'partial')
        self.assertEqual(status['failures'][0]['error'],'ValueError')

    def test_original_financial_report_replaces_front_chunk_mirror(self):
        row=self.notice('2026年半年度报告','2026-08-20')
        parsed={**self.pdf(), 'read_pages':196,'total_pages':196}
        with patch.object(primary,'get_json',side_effect=[self.identities(),dict(announcements=[row])]), \
                patch.object(primary,'china_now',return_value=NOW),patch.object(primary,'read_pdf',return_value=parsed):
            materials,status=primary.cninfo_financial(self.hub,self.stock,self.deadline)
        self.assertEqual(status['parsed_pages'],196)
        self.assertEqual(materials[0].kind,'financial_report')
        self.assertIn('196/196',materials[0].reading_status)
        self.assertIn('不是当日催化',materials[0].body)

    def test_new_pdf_policy_bypasses_old_failure_and_respects_stock_deadline(self):
        self.hub.cache('primary:attempt:cninfo:pdf:12345', 600,
                       lambda:dict(ok=False, error='TimeoutExpired'))
        row=self.notice('2026年半年度报告','2026-08-20')
        deadline=time.monotonic()+45
        with patch.object(primary,'get_json',side_effect=[self.identities(),dict(announcements=[row])]), \
                patch.object(primary,'china_now',return_value=NOW), \
                patch.object(primary,'read_pdf',return_value=self.pdf()) as read:
            materials,status=primary.cninfo_financial(self.hub,self.stock,deadline)
        self.assertEqual(len(materials),1)
        read.assert_called_once()
        self.assertGreater(read.call_args.kwargs['timeout'],40)
        self.assertLessEqual(read.call_args.kwargs['timeout'],45)

    def test_financial_report_wrong_org_and_summary_do_not_trigger_pdf_download(self):
        rows=[self.notice('2026年半年度报告','2026-08-20',org='wrong'),self.notice('2026年半年度报告摘要','2026-08-20')]
        with patch.object(primary,'get_json',side_effect=[self.identities(),dict(announcements=rows)]), \
                patch.object(primary,'china_now',return_value=NOW),patch.object(primary,'read_pdf') as read:
            materials,status=primary.cninfo_financial(self.hub,self.stock,self.deadline)
        self.assertEqual(materials,[])
        read.assert_not_called()

    def test_shared_index_cache_and_failure_cooldown_prevent_repeated_requests(self):
        fetch=Mock(return_value={'data':1})
        self.assertEqual(primary.cached(self.hub,'index',1800,fetch),{'data':1})
        primary.cached(self.hub,'index',1800,fetch)
        self.assertEqual(fetch.call_count,1)
        failed=Mock(side_effect=TimeoutError())
        for _ in range(2):
            with self.assertRaisesRegex(ValueError,'cached_primary_failure:TimeoutError'):
                primary.cached(self.hub,'failed',1800,failed)
        self.assertEqual(failed.call_count,1)

    def test_cached_media_failure_preserves_fixed_reason_but_not_arbitrary_response(self):
        failed=Mock(side_effect=ValueError('media_full_body_unavailable'))
        with self.assertRaisesRegex(ValueError,'cached_primary_failure:ValueError:media_full_body_unavailable'):
            primary.cached(self.hub,'media-failure',600,failed)
        private=Mock(side_effect=ValueError('untrusted response text with secrets'))
        with self.assertRaises(ValueError) as error:
            primary.cached(self.hub,'private-failure',600,private)
        self.assertEqual(str(error.exception),'cached_primary_failure:ValueError')

    def test_government_link_discovery_rejects_old_future_and_external_pages(self):
        content=''.join('<a href="'+url+'">规模以上工业增加值</a>' for url in [
            './202610/t20261019_1.html','./202601/t20260101_2.html',
            './202610/t20261026_3.html','https://example.com/202610/t20261019_4.html',
            './202610/t20261099_5.html'])
        result=primary.government_candidates(content,primary.SOURCES['nbs_industry'],NOW)
        self.assertEqual(len(result),1)
        self.assertIn('t20261019_1.html',result[0][3])

    def test_missing_publication_metadata_is_not_inferred_from_url(self):
        content=self.article().replace('name="PubDate"','name="not-a-date"')
        with patch.object(primary,'html',return_value=content),patch.object(primary,'china_now',return_value=NOW), \
                self.assertRaisesRegex(ValueError,'publication_date'):
            primary.government_article(self.hub,'nbs_industry','最新规模以上工业增加值情况',
                'https://www.stats.gov.cn/sj/zxfb/202610/t20261019_1.html',self.profile('半导体'),self.deadline)

    def test_statistics_keep_publication_time_and_scope_without_company_benefit(self):
        with patch.object(primary,'html',return_value=self.article()),patch.object(primary,'china_now',return_value=NOW):
            material=primary.government_article(self.hub,'nbs_industry','最新规模以上工业增加值情况',
                'https://www.stats.gov.cn/sj/zxfb/202610/t20261019_1.html',self.profile('半导体'),self.deadline)
        self.assertEqual(material.published_at,datetime(2026,10,19,10))
        self.assertIn('不证明该公司受益',material.body)
        self.assertIn('不是今日现货报价',material.body)
        self.assertEqual(material.scope,'A:123456:行业关联')

    def test_page_layout_table_does_not_hide_real_article_paragraphs(self):
        content='<table><tr><td>'+self.article()+'</td></tr></table>'
        with patch.object(primary,'html',return_value=content),patch.object(primary,'china_now',return_value=NOW):
            material=primary.government_article(self.hub,'nbs_industry','最新规模以上工业增加值情况',
                'https://www.stats.gov.cn/sj/zxfb/202610/t20261019_1.html',self.profile('半导体'),self.deadline)
        self.assertIn('集成电路',material.body)

    def test_irrelevant_statistics_and_unparsed_table_values_do_not_become_evidence(self):
        content=self.article(body='仅有银行业务讨论。'*10).replace('</div>',
            '<table><tr><td>集成电路</td><td>999999</td></tr></table></div>')
        with patch.object(primary,'html',return_value=content),patch.object(primary,'china_now',return_value=NOW), \
                self.assertRaisesRegex(ValueError,'not_relevant'):
            primary.government_article(self.hub,'nbs_industry','最新规模以上工业增加值情况',
                'https://www.stats.gov.cn/sj/zxfb/202610/t20261019_1.html',self.profile('半导体'),self.deadline)

    def test_http_failure_is_failed_not_no_material(self):
        with patch.object(primary,'html',side_effect=ConnectionError()):
            items,status=primary.government_observations(self.hub,self.stock,self.deadline,self.profile('半导体'))
        self.assertEqual(items,[])
        self.assertEqual(status['status'],'failed')
        self.assertEqual(status['sources']['nbs_industry']['status'],'failed')

    def test_success_http_challenge_page_is_a_parse_failure_not_no_news(self):
        with patch.object(primary,'html',return_value='<html>需要验证后继续访问</html>'):
            items,status=primary.government_observations(self.hub,self.stock,self.deadline,self.profile('半导体'))
        self.assertEqual(items,[])
        self.assertEqual(status['status'],'failed')


if __name__=='__main__':
    unittest.main()
