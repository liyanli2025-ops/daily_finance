from datetime import datetime,timedelta
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch,AsyncMock,Mock

from app.models.news import News
from app.services.ai_analyzer import AIAnalyzerService
from app.services.news_briefing import associations,weak_industry_only,briefing
from app.services.policy_sources import PolicyCollector,index_links,parse_article,permitted,SOURCES
from app.services.watchlist_service import WatchlistStock

NOW=datetime(2026,10,25,12)


def item(identifier,title,body='公开正文事实。'*20,impact=''):
    return News(id=identifier,title=title,content=title+'。'+body,source='原始媒体',source_url='https://example.com/article/'+identifier,
                published_at=NOW-timedelta(hours=2),importance_score=.9,market_impact=impact)


class BriefingTests(unittest.TestCase):
    def setUp(self):
        self.stocks=[WatchlistStock('123456','材料新公司','A'),WatchlistStock('234567','养殖新公司','A')]
        self.profiles={'A:123456':dict(business='主营环氧塑封料'),'A:234567':dict(business='主营生猪养殖')}

    def test_different_supply_chain_stages_do_not_get_business_overlap_grade(self):
        row=item('substrate','三星扩产封装基板','FC-BGA基板扩产，用于高端芯片。'*10,'行业关联 A:123456（匹配：封装）')
        self.assertEqual(associations(row,self.stocks,self.profiles)[0]['level'],'keyword_only')
        self.assertTrue(weak_industry_only(row,self.stocks,self.profiles))
        row=item('slaughter','屠宰项目投产','每年新增200万头生猪屠宰能力。'*10,'行业关联 A:234567（匹配：生猪）')
        self.assertEqual(associations(row,self.stocks,self.profiles)[0]['level'],'keyword_only')

    def test_operating_variable_match_remains_separate_from_beneficiary_claim(self):
        row=item('hog','生猪价格变化','区域猪价及统计口径待核验。'*10,'行业关联 A:234567（匹配：猪价）')
        self.assertEqual(associations(row,self.stocks,self.profiles)[0]['level'],'business_overlap')
        self.assertEqual(row.related_stocks,[])
        mention=item('mention','材料新公司发布公告')
        self.assertEqual(associations(mention,self.stocks,self.profiles)[0]['level'],'company_mention')

    def test_topic_concentration_does_not_displace_domestic_event_or_company(self):
        ai=[item('ai'+str(i),title) for i,title in enumerate([
            'AI抛售背后的流动性冲击','AI交易何时止跌：资金压力','高盛认为AI资本开支风险显著',
            '对冲基金创纪录抛售AI资产','AI发债规模扩大改变市场'])]
        policy=item('policy','国内交易规则公开征求意见',impact='全市场事件入口')
        policy.category='监管原文';policy.importance_score=.5
        company=item('company','材料新公司发布订单变更公告')
        analyzer=AIAnalyzerService.__new__(AIAnalyzerService)
        with patch('app.services.ai_analyzer.get_watchlist_service',return_value=SimpleNamespace(get_all_stocks=lambda:self.stocks)), \
                patch('app.services.research_hub.ResearchHub.load',return_value=[dict(key=k,profile=v) for k,v in self.profiles.items()]):
            text=analyzer._prepare_news_summary(ai+[policy,company])
        ids={n.id for n in analyzer._selected_evidence_news}
        self.assertLessEqual(len(ids&{n.id for n in ai}),2)
        self.assertIn('company',ids);self.assertIn('policy',ids)
        self.assertIn('主题分组',text)
        self.assertEqual(analyzer._news_briefing['topic_counts']['海外AI交易与融资'],5)

    def test_notice_and_explanation_share_editorial_slot_but_final_rule_does_not(self):
        notice=item('notice','关于《私募投资母基金管理规定（征求意见稿）》公开征求意见的通知',body='通知明确征求意见期限及递交办法。'*20)
        explanation=item('explanation','证监会就《私募投资母基金管理规定（征求意见稿）》公开征求意见',body='说明文件阐述背景及不同条款的考虑。'*20)
        final=item('final','证监会发布《私募投资母基金管理规定》',body='正式规定明确实施日期，不能混为草案。'*20)
        for row in [notice,explanation,final]:row.source='证监会原文'
        analyzer=AIAnalyzerService.__new__(AIAnalyzerService)
        with patch('app.services.ai_analyzer.get_watchlist_service',return_value=SimpleNamespace(get_all_stocks=lambda:[])), \
                patch('app.services.research_hub.ResearchHub.load',return_value=[]):
            analyzer._prepare_news_summary([notice,explanation,final])
        ids={row.id for row in analyzer._selected_evidence_news}
        self.assertEqual(len(ids & {'notice','explanation'}),1)
        self.assertIn('final',ids)
        self.assertEqual(len(analyzer._news_briefing['articles']),3)


class PolicyTests(unittest.TestCase):
    def page(self,title='私募基金规定公开征求意见',date='2026-10-23 17:24:29'):
        return '<meta name="ArticleTitle" content="'+title+'"><meta name="PubDate" content="'+date+'"><div class="detail-news">'+('现向社会公开征求意见，内容需要区分草案与正式规定。'*10)+'</div>'

    def test_metadata_and_body_are_required_and_unknown_hosts_rejected(self):
        url='https://www.csrc.gov.cn/csrc/c100028/c7666352/content.shtml'
        row=parse_article(self.page(),url)
        self.assertEqual(row['published'],'2026-10-23T17:24:29')
        self.assertEqual(row['precision'],'second')
        with self.assertRaises(ValueError):parse_article('<div class="detail-news">正文</div>',url)
        self.assertFalse(permitted('https://example.com/csrc/c100028/c7666352/content.shtml'))

    def test_undated_or_old_list_does_not_invent_publication_year(self):
        html='<li><a href="/csrc/c100028/c7666352/content.shtml">私募规定征求意见</a><span class="time">10-23</span></li>'
        self.assertEqual(len(index_links(html,'csrc_news',NOW,72)),1)
        with tempfile.TemporaryDirectory() as temporary:
            collector=PolicyCollector(temporary)
            def get(url,deadline):
                if url in {row['url'] for row in SOURCES.values()}:return html if 'csrc' in url else ''
                return self.page(date='2021-10-23 17:24:29')
            with patch.object(collector,'html',side_effect=get),patch('app.services.policy_sources.china_now',return_value=NOW):
                news,status=collector.collect(72)
            self.assertEqual(news,[])
            self.assertEqual(status['sources']['csrc_news']['excluded'],1)

    def test_consultation_is_not_promoted_to_active_law(self):
        html='<li><a href="/csrc/c100028/c7666352/content.shtml">私募规定征求意见</a><span class="time">10-23</span></li>'
        with tempfile.TemporaryDirectory() as temporary:
            collector=PolicyCollector(temporary)
            def get(url,deadline):
                if url in {row['url'] for row in SOURCES.values()}:return html if 'csrc' in url else ''
                return self.page()
            with patch.object(collector,'html',side_effect=get),patch('app.services.policy_sources.china_now',return_value=NOW):
                news,status=collector.collect(72)
            self.assertEqual(len(news),1)
            self.assertIn('征求意见阶段',news[0].market_impact)
            self.assertIn('缺少到期量',news[0].market_impact)

    def test_failure_does_not_claim_no_policy(self):
        with tempfile.TemporaryDirectory() as temporary:
            collector=PolicyCollector(temporary)
            with patch.object(collector,'html',side_effect=TimeoutError('fixture')):
                news,status=collector.collect(72)
            self.assertEqual(news,[])
            self.assertTrue(all(row['status']=='failed' for row in status['sources'].values()))

    def test_administrative_registry_and_coin_issues_are_not_market_events(self):
        html=''.join('<li><a href="/csrc/c100028/c'+str(i)+'/content.shtml">'+title+'</a></li>'
            for i,title in enumerate(['行政许可事项：再融资企业基本情况','纪念币发行公告','金融交易规则征求意见']))
        rows=index_links(html,'csrc_news',NOW,72)
        self.assertEqual(len(rows),1)
        self.assertIn('金融交易规则',rows[0][1])


class FullCollectionAcceptanceTests(unittest.IsolatedAsyncioTestCase):
    async def test_full_acceptance_uses_production_pool_and_saves_actual_news_input_without_models(self):
        from app import radar_check
        news=item('actual','实际完整采集新闻')
        collector=Mock()
        collector.collect_all=AsyncMock(return_value=[news])
        collector.client.aclose=AsyncMock()
        collector.get_news_by_type.return_value={'finance':[news]}
        collector.filter_china_related.return_value=[news]
        collector._technical_snapshot={};collector._radar_coverage={'sources':{}}
        with tempfile.TemporaryDirectory() as temporary, \
                patch.object(radar_check,'ROOT',__import__('pathlib').Path(temporary)), \
                patch('app.services.watchlist_repository.refresh_app_watchlist',AsyncMock(return_value=SimpleNamespace(get_all_stocks=lambda:[]))), \
                patch('app.services.watchlist_repository.assert_watchlist_current',AsyncMock()) as unchanged, \
                patch.object(radar_check,'NewsCollectorService',return_value=collector) as factory, \
                patch('app.services.ai_analyzer.get_watchlist_service',return_value=SimpleNamespace(get_all_stocks=lambda:[])), \
                patch('app.services.research_hub.ResearchHub.load',return_value=[]), \
                patch('app.services.event_observations.EventObservations.context',return_value='无历史'), \
                patch.object(AIAnalyzerService,'_call_ai',AsyncMock(side_effect=AssertionError('no model requests'))) as model:
            result=await radar_check.inspect(72,True)
            factory.assert_called_once_with(sentiment=False)
            collector.collect_all.assert_awaited_once_with(72)
            collector.client.aclose.assert_awaited_once()
            model.assert_not_awaited()
            import json
            from pathlib import Path
            saved=json.loads(Path(result['snapshot_path']).read_text(encoding='utf-8'))
            unchanged.assert_awaited_once_with(())
            self.assertEqual(saved['watchlist_signature'],[])
            self.assertLessEqual(saved['collection_started_at'],saved['collected_at'])
            self.assertIn('[N:actual]',saved['news_input'])
            self.assertEqual(saved['raw_articles'][0]['content'],news.content)
            self.assertTrue(result['full_collection'])
            self.assertEqual(result['selection_summary']['selected_articles'],1)
