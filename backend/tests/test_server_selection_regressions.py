"""Server snapshot regressions, no source re-probes or model requests."""
from datetime import datetime
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from app.models.news import News
from app.services.ai_analyzer import AIAnalyzerService
from app.services.media_sources import relation
from app.services.news_briefing import associations,editorial_exclusion
from app.services.overseas_sources import OverseasCollector
from app.services.research_hub import tag_industry_news
from app.services.source_health import record_failure
from app.services.watchlist_service import WatchlistStock


def article(identifier,title,body):
    return News(id=identifier,title=title,content=body,source='第一财经公开原文',
        source_url='https://www.yicai.com/news/'+identifier+'.html',published_at=datetime(2026,10,25,11))


class ServerSelectionTests(unittest.TestCase):
    def test_household_utility_words_are_not_hydropower_operating_signals(self):
        stock=WatchlistStock('600900','长江电力','A')
        text='智慧养老设备监测自来水和水电费。'
        self.assertEqual(relation('养老设备',text,[stock],{'600900':['来水','水电']})[1],{})
        row=article('home','养老设备',text)
        tag_industry_news([row],[dict(key='A:600900',topics=['来水','水电'])])
        self.assertNotIn('行业关联',row.market_impact or '')
        row.market_impact='行业关联 A:600900（匹配：来水,水电）'
        self.assertEqual(associations(row,[stock],{'A:600900':dict(business='水力发电')})[0]['level'],'keyword_only')
        valid=relation('流域水库来水增加','水电站发电量变化',[stock],{'600900':['来水','水电']})
        self.assertIn('600900',valid[1])

    def test_soft_features_do_not_displace_concrete_events_and_same_title_has_one_slot(self):
        title='下周外盘看点丨美联储领衔央行超级周'
        rows=[article('one',title,'不同正文第一版。'*50),article('two',title,'不同正文第二版。'*50),
            article('school','直面AI时代新命题 会计学院探索管理人才培养路径','人才培训。'*50),
            article('home','老有所依｜毫米波雷达走进卧室','养老设备。'*50)]
        # The same article can be present in both fresh and restored samples,
        # with recommendation/footer changes. Contrary independent bodies stay.
        rows[1].source_url=rows[0].source_url
        analyzer=AIAnalyzerService.__new__(AIAnalyzerService)
        with patch('app.services.ai_analyzer.get_watchlist_service',return_value=SimpleNamespace(get_all_stocks=lambda:[])), \
                patch('app.services.research_hub.ResearchHub.load',return_value=[]):
            analyzer._prepare_news_summary(rows)
        self.assertEqual(len(analyzer._selected_evidence_news),1)
        self.assertEqual(analyzer._news_quality_exclusions['soft_feature_without_concrete_market_event'],2)
        self.assertIsNone(editorial_exclusion(article('policy','养老设备补贴政策发布','政策正文。'*50),[]))
        self.assertIsNone(editorial_exclusion(article('order','某公司管理人才培训业务订单增长','订单正文。'*50),[]))

    def test_failure_reason_reads_existing_ledger_without_network(self):
        import requests
        with tempfile.TemporaryDirectory() as folder:
            collector=OverseasCollector(folder)
            key='overseas:index:v1:bbc'
            response=requests.Response();response.status_code=403
            record_failure(collector.hub.root,key,requests.HTTPError(response=response))
            with patch('requests.get',side_effect=AssertionError('must not re-probe')):
                self.assertEqual(collector.failure_detail(key,ValueError('hidden')),'http_403')
                self.assertEqual(collector.failure_detail('unknown',ValueError('private provider response')),
                    'cause_not_retained_no_retest')


if __name__=='__main__':unittest.main()
