from dataclasses import asdict
from datetime import datetime
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.services.research_hub import Material,ResearchHub,save_json
from app.services.material_identity import coalesce_materials
from app.services.episode_workspace import EpisodeWorkspace
from app.services.watchlist_service import WatchlistStock

NOW=datetime(2026,10,29,14)


def context(code,body,identifier='legacy-source',kind='industry_observation'):
    material=Material(identifier,'同一篇行业统计','原文来源','https://example.com/statistics',kind,'A:'+code+':行业关联',body,NOW,NOW.isoformat(),'2026年9月','按业务词匹配的段落节选')
    return dict(key='A:'+code,name='动态企业'+code,profile=None,collected_at=NOW.isoformat(),coverage={},materials=[dict(asdict(material),published_at=NOW.isoformat())])


class MaterialIdentityTests(unittest.TestCase):
    def test_legacy_same_source_different_views_both_survive_without_workspace_collision(self):
        contexts=[context('123456','电池产量增长10%，属于全国数据，不等于企业订单。'*15),context('654321','集成电路产量增长5%，属于全国数据，不等于企业收入。'*15)]
        stocks=[WatchlistStock(code,'动态企业'+code,'A') for code in ('123456','654321')]
        hub=ResearchHub()
        with patch.object(hub,'load',return_value=contexts),patch('app.services.research_hub.china_now',return_value=NOW):
            text,evidence=hub.prompt(stocks,max_characters=8000)
            pool=hub.evidence_pool(stocks)
        self.assertEqual(len(evidence),2)
        self.assertEqual(len({item.id for item in evidence}),2)
        self.assertEqual(len({item.source_id for item in evidence}),1)
        self.assertIn('电池产量增长10%',text);self.assertIn('集成电路产量增长5%',text)
        self.assertEqual({item.id for item in evidence},{item.id for item in pool})
        with tempfile.TemporaryDirectory() as root:
            workspace=EpisodeWorkspace([],root,NOW)
            workspace.add(evidence);workspace.add(pool)
            self.assertEqual(len(workspace.documents),2)
            result=workspace.search('集成电路产量')['results'][0]
            self.assertIn('654321',result['scope'])
            self.assertNotIn('123456',result['scope'])
            self.assertEqual(result['source_id'],evidence[0].source_id)
            workspace.finish(True)

    def test_identical_view_provided_once_with_all_scopes_and_no_double_character_count(self):
        body='同一份全国统计中的相同段落，不能证明两家企业受益。'*20
        contexts=[context('123456',body),context('654321',body)]
        hub=ResearchHub()
        with patch.object(hub,'load',return_value=contexts),patch('app.services.research_hub.china_now',return_value=NOW):
            text,evidence=hub.prompt([],max_characters=8000)
            pool=hub.evidence_pool([])
        self.assertEqual(len(evidence),1);self.assertEqual(len(pool),1)
        self.assertEqual(evidence[0].scope_links,['A:123456:行业关联','A:654321:行业关联'])
        self.assertEqual([row['status'] for row in hub.prompt_reading],['provided','shared_already_provided'])
        self.assertEqual(sum(row['selected_characters'] for row in hub.prompt_reading),len(body))
        self.assertEqual(len(hub.prompt_ranges),1)
        with tempfile.TemporaryDirectory() as root:
            workspace=EpisodeWorkspace([],root,NOW);workspace.add(evidence);workspace.add(pool)
            row=workspace.metadata(next(iter(workspace.documents.values())))
            self.assertEqual(row['scope_links'],evidence[0].scope_links)
            workspace.finish(True)

    def test_view_id_is_stable_when_only_one_related_stock_is_requested(self):
        first=Material(**{**context('123456','电池统计。'*30)['materials'][0],'published_at':NOW})
        other=Material(**{**context('654321','芯片统计。'*30)['materials'][0],'published_at':NOW})
        alone=coalesce_materials([first])[0]
        together=coalesce_materials([first,other])
        self.assertEqual(alone.id,together[0].id)

    def test_unknown_conflicting_id_outside_known_government_view_format_still_rejected(self):
        first=Material(**{**context('123456','第一版研究。'*20,kind='company_research')['materials'][0],'published_at':NOW})
        second=Material(**{**context('654321','另一个研究。'*20,kind='company_research')['materials'][0],'published_at':NOW})
        with self.assertRaisesRegex(ValueError,'identity_collision'):coalesce_materials([first,second])

    def test_cached_legacy_ids_and_bodies_are_not_rewritten_on_disk(self):
        with tempfile.TemporaryDirectory() as root:
            hub=ResearchHub(root);row=context('123456','全国电池统计。'*30)
            path=Path(root)/'stocks/A-123456.json';save_json(path,row);original=path.read_bytes()
            with patch('app.services.research_hub.china_now',return_value=NOW):
                pool=hub.evidence_pool([WatchlistStock('123456','动态企业','A')])
            self.assertEqual(path.read_bytes(),original)
            self.assertNotEqual(pool[0].id,'legacy-source')
            self.assertEqual(pool[0].body,row['materials'][0]['body'])
