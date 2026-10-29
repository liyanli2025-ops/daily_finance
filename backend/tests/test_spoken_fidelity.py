import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from app.services.spoken_fidelity import assess
from app.services import podcast_script_cache as cache
from spoken_fixtures import review_reply


class FidelityTests(unittest.TestCase):
    def test_unanchored_pass_is_not_accepted(self):
        self.assertFalse(assess({'passed':True,'issues':[]},'原稿','口播')['anchors_valid'])

    def test_valid_quotes_are_only_anchor_validation_not_semantic_proof(self):
        value=json.loads(review_reply('若需求回落，修复依据减弱。','需求回落，修复依据不会减弱。'))
        result=assess(value,'若需求回落，修复依据减弱。','需求回落，修复依据不会减弱。')
        self.assertTrue(result['anchors_valid'])
        self.assertIn('不证明含义相同',result['limitation'])

    def test_missing_or_fabricated_qualifier_quote_cannot_pass(self):
        value=json.loads(review_reply('原稿事实和条件','口播事实和条件'))
        for quote in (None,'原稿没有的条件','  ','\n\t'):
            value['checks'][2]['report_quote']=quote
            self.assertFalse(assess(value,'原稿事实和条件','口播事实和条件')['anchors_valid'])

    def test_mixed_pass_and_changed_status_rejected(self):
        value=json.loads(review_reply('原稿事实','口播事实'))
        value['checks'][1]['status']='changed'
        self.assertFalse(assess(value,'原稿事实','口播事实')['anchors_valid'])

    def test_missing_side_allowed_only_on_negative_review(self):
        value=json.loads(review_reply('原稿条件','口播事实'))
        value['passed']=False;value['issues']=['删掉限制']
        value['checks'][2].update(status='missing',script_quote=None)
        self.assertTrue(assess(value,'原稿条件','口播事实')['anchors_valid'])
        value['passed']=True
        self.assertFalse(assess(value,'原稿条件','口播事实')['anchors_valid'])

    def test_review_contract_change_invalidates_cache_signature(self):
        report=SimpleNamespace(content='原稿',title='早报')
        old=cache.signature(report,'用户')
        with patch.object(cache,'REVIEW_CONTRACT','更新后的实际审查协议'):
            self.assertNotEqual(old,cache.signature(report,'用户'))


class SavedReviewTests(unittest.TestCase):
    def test_replay_is_read_only_and_not_a_publish_approval(self):
        import tempfile
        from pathlib import Path
        from app.spoken_review_check import check
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'saved.json'
            content=json.dumps(dict(stage='spoken_review_response',context=dict(report_body='原稿事实',script='口播事实'),response=review_reply('原稿事实','口播事实')))
            path.write_text(content,encoding='utf-8')
            result=check(path)
            self.assertTrue(result['anchor_check']['anchors_valid'])
            self.assertFalse(result['publish_approved'])
            self.assertEqual(result['model_requests'],0)
            self.assertEqual(path.read_text(encoding='utf-8'),content)

    def test_old_checkpoint_cannot_invent_missing_context(self):
        import tempfile
        from pathlib import Path
        from app.spoken_review_check import check
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'saved.json'
            path.write_text(json.dumps(dict(stage='spoken_review_response',response='{}')),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'旧检查点'):
                check(path)
