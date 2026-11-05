"""Saved-source preparation and the two-request execution boundary."""
import asyncio
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

TOOLS = Path(__file__).absolute().parents[2] / 'tools'
sys.path.insert(0, str(TOOLS))
import saved_editorial as sample
import run_saved_editorial_once as runner
import resume_saved_editorial_review as continuation


def bundle():
    return dict(watchlist=[], cutoff='2026-11-05T08:32:25', sources=[dict(id='sample-source',
        text='来源明确记载：指数本日上涨百分之二，市场成交额扩大，部分行业仍然下跌。',
        url='https://example.com/news', title='市场收盘')])


def draft():
    body = '本期只讨论已保存的收盘材料。[N:sample-source]\n' + '已有上涨并不代表所有行业盈利改善，后续持续性仍取决于订单和成交支持。' * 15
    return dict(title='已存资料的市场分析样稿', body=body,
        editor_notes=['没有核对最新海外交易时段，不代表当前实时行情。'],
        evidence_checks=[dict(draft_quote='本期只讨论已保存的收盘材料。', source_id='sample-source',
            source_quote='指数本日上涨百分之二，市场成交额扩大')])


def completed_writer():
    return dict(owner=sample.OWNER, status='failed_no_retry', reason='editorial_unchecked_citation',
        completed_phases=['analysis'], phase='analysis', model_http_attempts=1,
        model_input_characters=2000, reserved_output_tokens=6500, elapsed_seconds=20,
        original_files_unchanged=True, production_pause_preserved=True,
        completed_source_deliveries=[], usage=[dict(task='analysis', http_status=200,
        transport_error=None, max_output_tokens=6500, request_characters=2000)])


class EditorialInputTests(unittest.TestCase):
    def test_missing_pair_is_reviewable_but_strict_validation_still_rejects(self):
        value = draft()
        value['evidence_checks'] = []
        raw = json.dumps(value, ensure_ascii=False)
        with self.assertRaisesRegex(ValueError, 'evidence_checks_missing'):
            sample.validate_draft(raw, bundle())
        accepted = sample.validate_draft(raw, bundle(), allow_unchecked=True)
        self.assertEqual(sample.citation_audit(accepted)['unchecked_source_ids'], ['sample-source'])

    def test_lenient_candidate_still_rejects_fabricated_source(self):
        value = draft()
        value['body'] += '[N:invented]'
        with self.assertRaisesRegex(ValueError, 'unknown_or_missing_citation'):
            sample.validate_draft(json.dumps(value), bundle(), allow_unchecked=True)

    def test_lenient_candidate_still_rejects_fabricated_quote(self):
        value = draft()
        value['evidence_checks'][0]['source_quote'] = '不存在于来源的连续文字'
        with self.assertRaisesRegex(ValueError, 'quote_not_in_provided_text'):
            sample.validate_draft(json.dumps(value), bundle(), allow_unchecked=True)

    def test_review_can_add_a_real_pair_without_changing_the_draft(self):
        value = draft()
        quote = value['evidence_checks'].pop()
        review = dict(verdict='pass', issues=[], editorial_assessment='仍待人工判断', additional_evidence_checks=[quote])
        checked = sample.validate_review(json.dumps(review), bundle(), value)
        self.assertEqual(sample.citation_audit(value, checked)['unchecked_source_ids'], [])
        self.assertEqual(value['evidence_checks'], [])

    def test_review_cannot_close_missing_pair_using_invented_quote(self):
        value = draft()
        quote = value['evidence_checks'].pop()
        quote['source_quote'] = '并不存在于正文中的支持性文字'
        review = dict(verdict='pass', issues=[], editorial_assessment='判断', additional_evidence_checks=[quote])
        with self.assertRaisesRegex(ValueError, 'quote_not_in_provided_text'):
            sample.validate_review(json.dumps(review), bundle(), value)

    def test_prior_usage_only_leaves_one_review_and_deducts_writer(self):
        remaining = continuation.prior_usage(completed_writer())
        self.assertEqual(remaining['model_requests'], 1)
        self.assertEqual(remaining['total_input_characters'], 128000)
        self.assertEqual(remaining['output_tokens'], 3500)
        self.assertEqual(remaining['seconds'], 460)

    def test_ambiguous_or_already_reviewed_result_cannot_start_a_continuation(self):
        for change in (dict(completed_phases=[]), dict(model_http_attempts=2),
                       dict(reason='editorial_quote_not_in_provided_text'), dict(elapsed_seconds=float('nan'))):
            with self.subTest(change=change), self.assertRaises(ValueError):
                continuation.prior_usage(dict(completed_writer(), **change))

    def test_quote_must_match_actual_delivered_text(self):
        value = draft()
        value['evidence_checks'][0]['source_quote'] = '不存在的政策原文：新增了贷款额度'
        with self.assertRaisesRegex(ValueError, 'quote_not_in_provided_text'):
            sample.validate_draft(json.dumps(value, ensure_ascii=False), bundle())

    def test_unknown_citation_cannot_enter_draft(self):
        value = draft()
        value['body'] += '[N:invented]'
        with self.assertRaisesRegex(ValueError, 'unknown_or_missing_citation'):
            sample.validate_draft(json.dumps(value, ensure_ascii=False), bundle())

    def test_duplicate_json_keys_are_not_silently_accepted(self):
        with self.assertRaisesRegex(ValueError, 'duplicate_key'):
            sample.decode('{"title":"one","title":"two"}')

    def test_explicit_recommendation_tail_keeps_exact_original_ranges(self):
        body = '市场上涨，但企业现金流依然承压。' * 30
        text = body + '\n—— / 好文推荐 / ——\n unrelated headline'
        value = sample.retained_text(text)
        self.assertEqual(value['text'], text[:value['retained_ranges'][0][1]])
        self.assertIn('现金流依然承压', value['text'])
        self.assertTrue(value['excluded_ranges'])

    def test_mid_article_recommendation_word_does_not_truncate_argument(self):
        text = '作者讨论为您推荐功能带来的偏差。\n' + '随后披露订单、毛利率和风险。' * 40
        self.assertEqual(sample.retained_text(text)['text'], text)

    def test_dense_trailing_navigation_is_separate_from_article(self):
        body = '国债收益率有所上升，媒体称投资者仍在等待数据。' * 10
        text = body + '\nADP就业人数变化\n' + '\n'.join('指标目录条目' + str(i) for i in range(40))
        self.assertEqual(sample.retained_text(text)['text'].strip(), body)

    def test_small_real_data_list_is_preserved(self):
        text = '数据如下：\nADP就业人数变化\n本月增加十万人\n上月增加八万人'
        self.assertEqual(sample.retained_text(text)['text'], text)

    def test_reprint_with_different_header_is_not_independent_evidence(self):
        text = ''.join(f'第{i}项事实包括收入增长、成本下降及尚未确认的未来订单。' for i in range(60))
        self.assertEqual(sample.duplicate_of('不同标题和编辑日期\n' + text,
                                           [dict(id='first', text=text)]), 'first')

    def test_shared_headline_does_not_remove_distinct_reporting(self):
        first = ''.join(f'甲企业第{i}个季度收入增长但现金流仍有约束。' for i in range(60))
        other = ''.join(f'乙企业第{i}份披露表明订单减少且成本压力增加。' for i in range(60))
        self.assertIsNone(sample.duplicate_of(other, [dict(id='first', text=first)]))

    def test_review_cannot_pass_with_material_issue(self):
        review = dict(verdict='pass', editorial_assessment='有完整主线', issues=[dict(severity='high',
            draft_quote='本期只讨论已保存的收盘材料。', source_id='', source_quote='', reason='范围表述错误')])
        with self.assertRaisesRegex(ValueError, 'verdict_conflicts'):
            sample.validate_review(json.dumps(review, ensure_ascii=False), bundle(), draft())

    def test_review_must_cite_real_draft_sentence(self):
        review = dict(verdict='needs_revision', editorial_assessment='需修正', issues=[dict(severity='medium',
            draft_quote='模型编造的报告原句', source_id='', source_quote='', reason='时段混淆')])
        with self.assertRaisesRegex(ValueError, 'review_evidence_invalid'):
            sample.validate_review(json.dumps(review, ensure_ascii=False), bundle(), draft())

    def test_failed_discovery_does_not_become_editorial_source(self):
        result = dict(status='failed_no_retry')
        with self.assertRaisesRegex(ValueError, 'not_completed'):
            sample.prepare_bundle(result, {}, [], lambda text: {})

    def test_started_marker_is_never_overwritten(self):
        with TemporaryDirectory() as temporary:
            p = Path(temporary) / 'started.json'
            runner.create_once(p, b'original')
            with self.assertRaises(FileExistsError):
                runner.create_once(p, b'retry')
            self.assertEqual(p.read_bytes(), b'original')

    def test_changed_source_is_detected_before_new_request(self):
        with TemporaryDirectory() as temporary:
            p = Path(temporary) / 'source.json'
            p.write_bytes(b'original')
            frozen = {str(p): sample.sha(p.read_bytes())}
            p.write_bytes(b'edited')
            with self.assertRaisesRegex(ValueError, 'original_files_changed'):
                runner.assert_frozen(frozen)


class SavedReviewIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.backend = Path(self.temporary.name) / 'backend'
        self.source = self.backend / 'data/diagnostics/saved-editorial-v1'
        self.source.mkdir(parents=True)
        value = draft()
        value['evidence_checks'] = []
        self.text = json.dumps(value, ensure_ascii=False)
        self.bundle = dict(bundle(), limits=sample.LIMITS, upstream_usage={})
        self.env = dict(runtime='unchanged', routes={}, connection='private-hash',
                        env_file='unchanged', editorial_policy='unchanged', tools={'new': 'tool'})
        self.oldenv = dict(self.env, tools={'old': 'tool'})
        messages = [dict(role='user', content='原始写稿输入')]
        size = len(json.dumps(messages, ensure_ascii=False, separators=(',', ':')))
        self.value = dict(owner=sample.OWNER, bundle=self.bundle, frozen={},
                          writer_messages=messages, environment=self.oldenv)
        self.result = completed_writer()
        self.result.update(input_sha256=sample.fingerprint(self.value), model_input_characters=size,
            source_cutoff=self.bundle['cutoff'], upstream_usage={}, completed_source_deliveries=[
                dict(id=s['id'], text_sha256=sample.sha(s['text'].encode()), characters=len(s['text']))
                for s in self.bundle['sources']])
        self.result['usage'][0]['request_characters'] = size
        data = {'result.json': self.result, 'input.json': self.value,
                'started.json': dict(owner=sample.OWNER, input_sha256=self.result['input_sha256']),
                'analysis-request.json': messages, 'analysis-visible-response.json': dict(text=self.text)}
        for name, body in data.items():
            runner.write(self.source / name, body)
        self.case = dict(result_sha256=sample.sha((self.source / 'result.json').read_bytes()),
            writer_input_sha256=self.result['input_sha256'],
            writer_response_sha256=sample.sha((self.source / 'analysis-visible-response.json').read_bytes()),
            bundle_sha256=sample.fingerprint(self.bundle), prior_tools=self.oldenv['tools'])

    def load(self):
        return continuation.load_saved(self.backend, self.source, self.case, self.env)

    def test_load_keeps_old_files_unchanged_and_freezes_them(self):
        before = {p.name: p.read_bytes() for p in self.source.iterdir()}
        loaded = self.load()
        self.assertEqual(loaded['resume']['writer_text'], self.text)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.source.iterdir()})
        self.assertIn(str(self.source / 'started.json'), loaded['frozen'])

    def test_changed_private_input_is_rejected(self):
        runner.write(self.source / 'input.json', dict(self.value, owner='different'))
        with self.assertRaisesRegex(ValueError, 'saved_identity_changed'):
            self.load()

    def test_changed_route_or_backend_is_not_authorized_by_new_tool_hashes(self):
        self.env['runtime'] = 'changed'
        with self.assertRaisesRegex(ValueError, 'saved_environment_changed'):
            self.load()

    def test_changed_saved_response_is_rejected(self):
        runner.write(self.source / 'analysis-visible-response.json', dict(text=self.text + ' '))
        with self.assertRaisesRegex(ValueError, 'saved_response_changed'):
            self.load()

    def test_an_existing_review_attempt_is_not_restarted(self):
        runner.write(self.source / 'review-request.json', [])
        with self.assertRaisesRegex(ValueError, 'review_already_attempted'):
            self.load()


class EditorialExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def run_case(self, writer, *, resume=False):
        from app.services import model_gateway, model_usage, watchlist_repository
        import httpx
        review = dict(verdict='pass', issues=[], editorial_assessment='样稿形成完整主线，仍待人工验收。')
        responses = [SimpleNamespace(is_error=False, json=lambda: dict(choices=[dict(finish_reason='stop',
            message=dict(content=writer))])), SimpleNamespace(is_error=False,
            json=lambda: dict(choices=[dict(finish_reason='stop', message=dict(content=json.dumps(review, ensure_ascii=False)))]))]
        client = AsyncMock()
        client.post.side_effect = responses[1:] if resume else responses
        manager = AsyncMock()
        manager.__aenter__.return_value = client
        b = bundle()
        value = dict(bundle=b, environment={}, frozen={}, writer_messages=[dict(role='user', content='写稿')])
        if resume:
            value['resume'] = dict(prior_result=completed_writer(), result_sha256='prior', writer_text=writer)
        base = SimpleNamespace(require_pause=lambda backend: None)
        with TemporaryDirectory() as temporary:
            backend = Path(temporary) / 'backend'
            (backend / 'data').mkdir(parents=True)
            (backend / 'data/.automation-paused').write_text('paused')
            root = backend / 'data/sample'
            root.mkdir()
            b['upstream_usage'] = dict(model_http_attempts=12, search_http_attempts=11)
            route = SimpleNamespace(provider='compatible', model='configured', base_url='https://example.com', api_key='test', effort='none')
            with patch.object(runner, 'environment', return_value={}), \
                    patch.object(watchlist_repository, 'assert_watchlist_current', new=AsyncMock()), \
                    patch.object(model_gateway, 'resolve_route', return_value=route), \
                    patch.object(model_gateway, 'request_for', return_value=('https://example.com', {}, {})), \
                    patch.object(model_usage, 'record_usage', return_value=dict(input_tokens=100, output_tokens=100)), \
                    patch.object(httpx, 'AsyncClient', return_value=manager):
                result = await runner.execute(backend, value, root, base)
                if resume:
                    self.assertFalse((root / 'analysis-request.json').exists())
                    self.assertTrue((root / 'review-request.json').exists())
            self.assertTrue((root / 'started.json').is_file())
            self.assertTrue((backend / 'data/.automation-paused').is_file())
            self.assertFalse(result['publication_allowed'])
            self.assertFalse(result['content_accepted'])
            return result, client.post.await_count, (root / 'draft.md').is_file()

    async def test_valid_draft_and_review_spend_at_most_two_requests(self):
        result, calls, saved = await self.run_case(json.dumps(draft(), ensure_ascii=False))
        self.assertEqual(calls, 2)
        self.assertEqual(result['status'], 'sample_reviewed_pending_human')
        self.assertTrue(saved)
        self.assertEqual(result['upstream_usage']['model_http_attempts'], 12)

    async def test_malformed_writer_stops_without_review_or_retry(self):
        result, calls, saved = await self.run_case('visible but invalid JSON')
        self.assertEqual(calls, 1)
        self.assertEqual(result['status'], 'failed_no_retry')
        self.assertFalse(saved)

    async def test_missing_quote_mapping_does_not_lose_draft_or_skip_review(self):
        value = draft()
        value['evidence_checks'] = []
        result, calls, saved = await self.run_case(json.dumps(value, ensure_ascii=False))
        self.assertEqual(calls, 2)
        self.assertTrue(saved)
        self.assertEqual(result['status'], 'sample_needs_citation_review')

    async def test_resume_only_posts_review_and_keeps_total_at_two(self):
        value = draft()
        value['evidence_checks'] = []
        result, calls, saved = await self.run_case(json.dumps(value, ensure_ascii=False), resume=True)
        self.assertEqual(calls, 1)
        self.assertEqual(result['model_http_attempts'], 2)
        self.assertEqual(result['new_model_http_attempts'], 1)
        self.assertEqual(result['reserved_output_tokens'], 10000)
        self.assertEqual(result['prior_editorial_usage'][0]['request_characters'], 2000)
        self.assertTrue(saved)
