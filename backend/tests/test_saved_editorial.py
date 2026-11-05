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


class EditorialInputTests(unittest.TestCase):
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


class EditorialExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def run_case(self, writer):
        from app.services import model_gateway, model_usage, watchlist_repository
        import httpx
        review = dict(verdict='pass', issues=[], editorial_assessment='样稿形成完整主线，仍待人工验收。')
        responses = [SimpleNamespace(is_error=False, json=lambda: dict(choices=[dict(finish_reason='stop',
            message=dict(content=writer))])), SimpleNamespace(is_error=False,
            json=lambda: dict(choices=[dict(finish_reason='stop', message=dict(content=json.dumps(review, ensure_ascii=False)))]))]
        client = AsyncMock()
        client.post.side_effect = responses
        manager = AsyncMock()
        manager.__aenter__.return_value = client
        b = bundle()
        value = dict(bundle=b, environment={}, frozen={}, writer_messages=[dict(role='user', content='写稿')])
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
