import json,tempfile,time,unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch,Mock

from app.models.news import News
from app.services.community_sources import CommunityCollector,discover,parse_thread,provider_for,statement
from app.services.discussion_briefing import statement_documents,cues,order_records
from app.services.discussion_contributions import record,summary,prune
from app.services.episode_workspace import EpisodeWorkspace

NOW=datetime(2026,10,31,11)
URL='https://www.jisilu.cn/question/123'
CAT='https://www.jisilu.cn/category/4'

def page():
    return '''<div class="aw-all-question"><div class="aw-item"><a href="/question/9">付费广告</a></div>
      <div class="aw-questoin-content"><h4><a href="/question/123">老帖的新回复</a>
      <a class="aw-topic-name" href="/topic/1">债券</a></h4>
      <span class="aw-text-color-999"><a class="aw-user-name">最后回复者</a>回复 • 2026-10-31 10:30 • 99999次浏览</span>
      </div></div>'''

def news():
    return News(id='thread-123',title='讨论',content='原始参与者说法，不是确认事实。'*20,
        source='公开参与者讨论-集思录',source_url=URL,published_at=NOW-timedelta(hours=2))

def thread():
    rows=[statement(URL,'root','原帖账号','旧原帖背景不要误称为今日新事实。'*100,'2026-01-01 10:00')]
    for i in range(25):rows.append(statement(URL,'reply:'+str(i),'同一高产账号','吾命休矣','2026-10-31 10:00'))
    rows.append(statement(URL,'late-reply','数据账号','融资余额同比下降7%，但占流通市值比例上升，需要核对口径。','2026-10-31 10:30',quoted=['他人的未经核实说法。']))
    return dict(url=URL,title='讨论',statements=rows,source_role='未经核实的公开参与者说法')


class BriefingTests(unittest.TestCase):
    def test_new_category_excludes_promotions_and_separates_last_reply_hint(self):
        self.assertEqual(provider_for(CAT,True),'jisilu')
        rows=discover('jisilu',page(),CAT)
        self.assertEqual(len(rows),1);r=rows[0]
        self.assertEqual(r['url'],URL);self.assertEqual(r['updated_hint'],'2026-10-31T10:30:00')
        self.assertEqual(r['update_kind'],'reply');self.assertNotIn('author',r)
        self.assertEqual(r['status'],'directory_not_body')

    def test_late_concrete_reply_is_readable_without_front_thread_truncation(self):
        docs,cat=statement_documents([news()],[thread()],NOW,72)
        self.assertEqual(len(docs),26)
        self.assertIn('融资余额',docs[0].content)
        self.assertEqual(cat[0]['position'],'late-reply')
        self.assertIn('旧原帖背景',docs[0].content);self.assertIn('字符0:300/',docs[0].content)
        self.assertNotIn('吾命休矣',docs[0].content)
        self.assertIn('被引作者未核',docs[0].content)
        self.assertEqual(docs[0].published_at,datetime(2026,10,31,10,30))
        self.assertEqual(cat[0]['cues']['status'],'textual_cues_not_verified_value')
        # The other 25 statements remain available, not erased as low value.
        self.assertEqual(sum('吾命休矣' in d.content for d in docs),25)

    def test_speaker_and_thread_rotation_does_not_prefer_prolific_account(self):
        rows=[]
        for url,author in [('A','loud'),('A','loud'),('A','other'),('B','third')]:
            rows.append(dict(url=url,statement=dict(author=author),cues=dict(reading_tier=2)))
        ordered=order_records(rows)
        self.assertEqual([x['statement']['author'] for x in ordered],['loud','third','other','loud'])

    def test_statement_version_keeps_dates_and_context_immutable(self):
        t=thread();a=statement_documents([news()],[t],NOW,72)[0][0]
        t['statements'][-1]['published_at']='2026-10-31T10:31:00'
        b=statement_documents([news()],[t],NOW,72)[0][0]
        self.assertNotEqual(a.id,b.id)
        t['statements'][0]['text']='新发现的原帖背景。'
        c=statement_documents([news()],[t],NOW,72)[0][0]
        self.assertNotEqual(b.id,c.id)

    def test_future_parent_and_future_reply_do_not_leak(self):
        t=thread();t['statements'][0]['published_at']='2026-11-02T10:00:00'
        t['statements'][1]['text']='未来敏感内容';t['statements'][1]['published_at']='2026-11-02T10:00:00'
        docs,_=statement_documents([news()],[t],NOW,72)
        self.assertFalse(any('旧原帖背景' in d.content or '未来敏感内容' in d.content for d in docs))

    def test_number_alone_is_not_value_score_and_no_number_observation_is_kept(self):
        self.assertEqual(cues('999999元')['reading_tier'],1)
        self.assertEqual(cues('我问渠道：交期缩短，但尚未得到厂方确认。')['reading_tier'],2)
        self.assertTrue(cues('我问渠道：交期缩短。')['requires_verification'])
        self.assertEqual(cues('Our factory has shorter lead times; reportedly customers cut orders.')['reading_tier'],2)

    def test_providers_get_turns_before_another_thread_from_same_site(self):
        rows=[dict(url=url,item=SimpleNamespace(source=provider),statement=dict(author='作者'),cues=dict(reading_tier=2))
            for url,provider in [('A','site1'),('B','site1'),('C','site2')]]
        self.assertEqual([r['url'] for r in order_records(rows)],['A','C','B'])

    def test_category_update_hint_refreshes_success_only_and_merges_duplicate_url(self):
        with tempfile.TemporaryDirectory() as root,patch('app.services.community_sources.china_now',return_value=NOW):
            collector=CommunityCollector(root)
            from test_community_sources import jsl
            def get(url,deadline,index=False,revision=None):
                if index:
                    return page() if url==CAT else '<div class="question_list"><div class="title"><a href="'+URL+'">老帖</a></div></div>'
                return jsl()
            with patch.object(collector,'get',side_effect=get) as mocked:
                dated=news().model_copy(update={'published_at':datetime(2026,10,31,9,tzinfo=timezone(timedelta(hours=8)))})
                docs,coverage=collector.collect(existing=[dated],granularity='statements')
            bodies=[call for call in mocked.call_args_list if call.args[0]==URL]
            self.assertEqual(len(bodies),1)
            self.assertEqual(bodies[0].kwargs['revision'],'2026-10-31T10:30:00')
            self.assertTrue(docs);self.assertEqual(coverage['read_unit'],'statements')

    def test_new_revision_key_cannot_bypass_a_structural_failure(self):
        with tempfile.TemporaryDirectory() as root:
            collector=CommunityCollector(root)
            response=Mock(status_code=200,content=b'challenge',text='<script>challenge()</script>',apparent_encoding='utf-8')
            with patch('app.services.community_sources.requests.get',return_value=response) as request:
                with self.assertRaises(ValueError):collector.get(URL,time.monotonic()+5)
                with self.assertRaises(ValueError):collector.get(URL,time.monotonic()+5,revision='2026-10-31T10:30:00')
            self.assertEqual(request.call_count,1)

    def test_transient_http_failure_is_not_retested_under_another_revision(self):
        import requests
        with tempfile.TemporaryDirectory() as root:
            collector=CommunityCollector(root);response=Mock(status_code=500)
            response.raise_for_status.side_effect=requests.HTTPError(response=response)
            with patch('app.services.community_sources.requests.get',return_value=response) as request:
                with self.assertRaises(ValueError):collector.get(URL,time.monotonic()+5)
                with self.assertRaises(ValueError):collector.get(URL,time.monotonic()+5,revision='2026-10-31T10:30:00')
            self.assertEqual(request.call_count,1)

    def test_directory_discovery_interleaves_body_reading(self):
        from test_community_sources import jsl
        with tempfile.TemporaryDirectory() as root,patch('app.services.community_sources.china_now',return_value=NOW),\
             patch('app.services.community_sources.INDEXES',{'jisilu':'https://www.jisilu.cn/'}),\
             patch('app.services.community_sources.EXTRA_INDEXES',{CAT:'bonds'}):
            collector=CommunityCollector(root)
            def get(url,deadline,index=False,revision=None):
                if index:
                    if url==CAT:return page().replace('/question/123','/question/456')
                    return '<div class="question_list"><div class="title"><a href="'+URL+'">目录</a></div></div>'
                return jsl()
            with patch.object(collector,'get',side_effect=get) as request:
                docs,_=collector.collect(granularity='statements')
            self.assertEqual([c.args[0] for c in request.call_args_list],['https://www.jisilu.cn/',URL,CAT,'https://www.jisilu.cn/question/456'])
            self.assertEqual(len(docs),4)

    def test_partial_statement_does_not_block_requesting_thread_context(self):
        with tempfile.TemporaryDirectory() as root,patch('app.services.community_sources.china_now',return_value=NOW):
            collector=CommunityCollector(root);partial=news().model_copy(update={'id':'discussion-statement-test'})
            from test_community_sources import jsl
            with patch.object(collector,'get',return_value=jsl()) as get:
                docs,_=collector.collect(urls=[URL],existing=[partial],granularity='thread')
            get.assert_called_once();self.assertTrue(docs)


class ContributionTests(unittest.TestCase):
    def test_usage_counts_are_not_marked_useful_or_independent_confirmation(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);ws=EpisodeWorkspace([news()],root/'episodes',NOW)
            ws.read('thread-123',characters=100)
            ws.usage('[N:thread-123]')
            record(ws,ws.usage(),False,root/'metrics',NOW)
            result=summary(root/'metrics',NOW);self.assertEqual(result['episodes'],1)
            self.assertFalse(result['automatic_frequency_changes'])
            row=result['receipts'][0]['sources'][0]
            self.assertEqual(row['prepared_documents'],1)
            self.assertEqual(row['pool_statement_documents'],0)
            self.assertEqual(row['confirmed_delivery_documents'],0)
            self.assertEqual(row['reported_citations'],1)
            self.assertEqual(row['value_review'],'not_reviewed')
            self.assertNotIn(news().content,json.dumps(result,ensure_ascii=False))
            record(ws,ws.usage(),False,root/'metrics',NOW)
            self.assertEqual(summary(root/'metrics',NOW)['episodes'],1)

    def test_pruning_removes_only_owned_expired_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);ws=EpisodeWorkspace([news()],root/'episodes',NOW)
            record(ws,ws.usage(),True,root/'metrics',NOW-timedelta(days=8))
            unrelated=root/'metrics'/'contribution-user.json';unrelated.write_text('{}')
            prune(root/'metrics',NOW)
            self.assertTrue(unrelated.exists());self.assertEqual(summary(root/'metrics',NOW)['episodes'],0)
