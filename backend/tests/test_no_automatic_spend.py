import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch,AsyncMock
import httpx
from app.config import Settings
from app.services import model_gateway as gateway
from app.services.ai_analyzer import AIAnalyzerService
from app.services.review_feedback import ReviewNeedsHuman
from app.models.report import ReportType


class CostDefaultsTests(unittest.IsolatedAsyncioTestCase):
    def test_defaults_do_not_authorize_extra_requests(self):
        config=Settings(_env_file=None)
        self.assertEqual(config.model_http_retries,0)
        self.assertFalse(config.report_auto_repair_enabled)

    async def test_transport_rate_limit_server_error_and_truncation_do_not_retry(self):
        for failure in ('transport',429,503,'max_tokens'):
            calls=[]
            def handler(request):
                calls.append(request)
                if failure=='transport': raise httpx.ReadTimeout('private provider text')
                if isinstance(failure,int):return httpx.Response(failure,json={'error':'private provider text'})
                return httpx.Response(200,json={'stop_reason':'max_tokens','content':[
                    {'type':'thinking','thinking':'not for logging'},
                    {'type':'text','text':'已付费但未完成的正文'}]})
            config=Settings(_env_file=None,openai_api_key='test',ai_model='anthropic/claude-sonnet-5.5',openai_base_url='https://api.ofox.io/v1')
            original=httpx.AsyncClient
            with patch.object(gateway,'settings',config),patch.object(gateway,'ensure_models_enabled'),patch.object(gateway.httpx,'AsyncClient',side_effect=lambda **kw:original(transport=httpx.MockTransport(handler),**kw)),patch('app.services.report_diagnostics.save_generation_stage') as save,patch('app.services.model_usage.record_usage'):
                with self.assertRaises(RuntimeError):await gateway.complete('review',[dict(role='user',content='evidence')])
            self.assertEqual(len(calls),1)
            if failure=='max_tokens':
                save.assert_called_once()
                self.assertEqual(save.call_args.args,('incomplete_response','已付费但未完成的正文'))
                self.assertFalse(save.call_args.kwargs['context']['publishable'])
                self.assertNotIn('thinking',str(save.call_args))
            else:save.assert_not_called()

    async def test_anchored_high_issue_stops_after_review_without_repair(self):
        service=AIAnalyzerService.__new__(AIAnalyzerService)
        report=SimpleNamespace(content='经营改善所以股价必涨')
        response=json.dumps(dict(overall_quality=5,issues=[dict(severity='high',type='逻辑矛盾',detail='因果跳跃',check_kind='reasoning',report_quote='经营改善所以股价必涨')]))
        service._call_ai=AsyncMock(return_value=response);service._ai_fix_report=AsyncMock()
        with patch('app.services.ai_analyzer.settings.report_auto_repair_enabled',False),patch('app.services.ai_analyzer.save_review_case',return_value='saved-case.json') as saved,patch('app.services.report_diagnostics.save_generation_stage'):
            with self.assertRaises(ReviewNeedsHuman) as error:
                await service._review_and_fix_report(report,'raw','','','',ReportType.MORNING)
        self.assertEqual(error.exception.reason,'paid_repair_not_enabled')
        saved.assert_called_once();service._call_ai.assert_awaited_once();service._ai_fix_report.assert_not_awaited()
        self.assertEqual(service._last_reviewed_report.content,report.content)
