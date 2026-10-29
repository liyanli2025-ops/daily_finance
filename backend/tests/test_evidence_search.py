from datetime import datetime
import tempfile
import unittest

from app.models.news import News
from app.services.evidence_search import search_window,token_weights
from app.services.episode_workspace import EpisodeWorkspace,terms


class SearchWindowTests(unittest.TestCase):
    def test_later_specific_statement_wins_over_early_generic_word(self):
        body='公司收入受到关注。'+('行业一般介绍。'*140)
        anchor='动态公司披露储能销量增长30%，产能利用率保持高位。'
        counter='但这不代表需求一定持续，分析师指出仍需观察库存。'
        body+=anchor+counter+('其他背景。'*180)
        weights=token_weights(terms('动态公司 储能销量 产能利用率'),[body])
        row=search_window(body,weights,200)
        self.assertGreater(row['offset'],200)
        self.assertIn(anchor+counter,row['excerpt'])
        self.assertEqual(row['excerpt'],body[row['offset']:row['end']])
        self.assertLessEqual(len(row['excerpt']),200)

    def test_pronoun_keeps_immediate_peer_subject_instead_of_queried_company(self):
        body='关注公司甲的产能。'+('一般资料。'*120)
        context='公司乙披露新增产线。公司表示，储能订单已经订满。'
        body+=context+'这仍是公司计划。'
        row=search_window(body,token_weights(terms('储能订单 订满'),[body]),140)
        self.assertIn(context,row['excerpt'])
        self.assertNotIn('公司甲',row['excerpt'])

    def test_long_numeric_table_is_not_sliced_into_pseudo_evidence(self):
        text='收入及统计口径1234567890'*200
        row=search_window(text,{'收入':1},100)
        self.assertEqual(row['excerpt'],'')
        self.assertEqual(row['ranges'],[])
        self.assertEqual(row['model_input_scope'],'no_body_provided')
        self.assertEqual(row['next_offset'],0)

    def test_tail_fragment_does_not_claim_no_unread_text(self):
        text=('背景信息。'*180)+'库存减少10%，需求仍未改善。'
        row=search_window(text,{'库存':1},100)
        self.assertEqual(row['end'],len(text))
        self.assertTrue(row['has_more'])
        self.assertTrue(row['unread_before'])
        self.assertIsNone(row['next_offset'])

    def test_english_decimal_and_names_remain_intact(self):
        text='Introductory context. '*100+'Lisa D. Cook preferred a 0.25 point increase. However, rates remained at 3.75 percent.'
        row=search_window(text,{'cook':1,'increase':1},180)
        self.assertIn('Lisa D. Cook preferred a 0.25 point increase.',row['excerpt'])
        self.assertIn('3.75 percent.',row['excerpt'])

    def test_related_links_are_not_search_body_hits(self):
        text='公司收入情况。\n相关阅读：\n另一公司储能订单增长。'
        row=search_window(text,{'储能订单':1},100)
        self.assertNotIn('另一公司',row['excerpt'])
        self.assertEqual(row['body_term_matches'],[])

    def test_pool_common_terms_have_less_weight_than_distinctive_terms(self):
        weights=token_weights({'公司','库存'},['公司库存','公司利润','公司情况'])
        self.assertGreater(weights['库存'],weights['公司'])


class SearchExposureTests(unittest.TestCase):
    def test_ledger_records_only_returned_whole_sentence_window(self):
        now=datetime(2026,10,29,7,32)
        body='产能变化只是前面的泛泛提及。'+('其他背景资料。'*130)+'动态企业披露储能产能增长20%。不过新增产能并未全部形成订单。'
        item=News(id='dynamic',title='企业经营情况',content=body,source='公开媒体',source_url='https://example.com/article',published_at=now)
        with tempfile.TemporaryDirectory() as folder:
            workspace=EpisodeWorkspace([item],folder,now)
            row=workspace.search('储能产能 订单')['results'][0]
            self.assertIn('新增产能并未全部形成订单',row['excerpt'])
            prepared=workspace.usage()['sources'][0]['prepared_ranges']
            self.assertTrue(prepared)
            self.assertEqual(workspace.merged_ranges(workspace.prepared['dynamic']),row['ranges'])
            self.assertEqual(workspace.completed_rounds,0)
            workspace.finish(True)

    def test_metadata_only_hit_does_not_become_body_exposure(self):
        now=datetime(2026,10,29,7,32)
        item=News(id='table',title='储能材料',content='库存统计口径1234567890'*200,source='公开媒体',source_url='https://example.com/table',published_at=now)
        with tempfile.TemporaryDirectory() as folder:
            workspace=EpisodeWorkspace([item],folder,now)
            row=workspace.search('库存')['results'][0]
            self.assertEqual(row['model_input_scope'],'no_body_provided')
            self.assertNotIn('table',workspace.prepared)
            self.assertNotIn('table',workspace.accessed)
            workspace.finish(True)

    def test_partial_company_name_cannot_outscore_exact_company_and_measure(self):
        now=datetime(2026,10,29,7,32)
        wrong=News(id='wrong',title='电力市场发电量变化',content='电力市场发电量增长，水电发电量增长。'*30,source='公开媒体',source_url='https://example.com/wrong',published_at=now)
        right=News(id='right',title='相关企业经营信息',content='其他企业的发电量变化。'*30+'动态电力披露季度发电量下降。',source='公开媒体',source_url='https://example.com/right',published_at=now)
        with tempfile.TemporaryDirectory() as folder:
            workspace=EpisodeWorkspace([wrong,right],folder,now)
            row=workspace.search('动态电力 发电量')['results'][0]
            self.assertEqual(row['id'],'right')
            self.assertIn('动态电力',row['query_phrase_matches'])
            workspace.finish(True)
