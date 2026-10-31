"""Research review and accounting scope specifications; no live acceptance."""
import unittest
from app.services.discovery_completion import review_events, FACETS, completion_review
from app.services.model_usage import collection_usage_scope, current_input_limit, reserve_call


class CompletionReviewTests(unittest.TestCase):
    def setUp(self):
        self.feedback=dict(watchlist=[],lanes=[],tasks=[],bodies={})
        self.event=dict(title='重要新变化',lane='industry',evidence_ids=['B1'],
            research_checks={key:dict(status='supported',evidence_ids=['B1'],explanation='具体研究依据') for key in FACETS})

    def test_an_article_without_research_checks_is_not_completion(self):
        del self.event['research_checks']
        result=review_events(dict(events=[self.event]),self.feedback)
        self.assertEqual(result['problems'][0]['code'],'event_research_checks_missing')

    def test_unresolved_counterevidence_becomes_an_actual_followup_task(self):
        self.event['research_checks']['disagreements']=dict(status='unresolved',evidence_ids=[],explanation='仍缺公司回应')
        result=review_events(dict(events=[self.event]),self.feedback)
        self.assertEqual(result['problems'],[])
        self.assertEqual(result['tasks'][0]['task_id'],'event:0:disagreements')
        self.assertEqual(result['tasks'][0]['lane'],'industry')

    def test_supported_check_cannot_cite_unprovided_event_evidence(self):
        self.event['research_checks']['background']['evidence_ids']=['invented']
        result=review_events(dict(events=[self.event]),self.feedback)
        self.assertEqual(result['problems'][0]['code'],'event_research_check_invalid')

    def test_a_budget_stop_without_a_dossier_keeps_incomplete_status(self):
        state=dict(collection_feedback=self.feedback,status='time_budget_exhausted',model_calls=9,
            search_tool_calls=8,body_url_calls=20)
        result=completion_review(state)
        self.assertEqual(result['status'],'incomplete')
        self.assertFalse(result['valid_dossier_present'])
        self.assertFalse(result['scope_ledger_valid'])

    def test_collection_scope_has_independent_accounting_and_input_guard(self):
        self.assertEqual(current_input_limit(),100000)
        with collection_usage_scope(160000):
            for _ in range(15):
                reserve_call()
            self.assertEqual(current_input_limit(),160000)
        self.assertEqual(current_input_limit(),100000)
