from spoken_fixtures import reply
from datetime import date,datetime,timedelta
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import AsyncMock,patch

from app.services.spoken_editing import clean,report_body,audit,tts_text,tts_segments
from app.services.podcast_generator import PodcastGeneratorService
from app.services.report_diagnostics import save_spoken_case,mark_spoken_case


class SpeechFormattingTests(unittest.TestCase):
    def test_tts_preserves_comparisons_ranges_signs_and_qualifying_parentheses(self):
        text='未来1—3个交易日，若RSI≤30或收益≥+2%，则检查（市场处于过渡阶段，不代表已经反转）。\n误差±0.5，价格≈10元，不等式a≠b，2026-10-28。'
        result=tts_text(text)
        for value in ['1至3个交易日','小于或等于30','大于或等于正百分之2',
                      '市场处于过渡阶段，不代表已经反转','正负0.5','约等于10元','不等于','2026-10-28']:
            self.assertIn(value,result)
        self.assertEqual(tts_text(result),result)
        self.assertEqual(tts_text('波动1—3%，对照1%—3%。'),'波动1至百分之3，对照百分之1至百分之3。')
        hidden='（背景\u200b音乐渐弱）若增长≥2%，再验证。'
        self.assertNotIn('背景',tts_text(hidden))
        self.assertEqual(tts_text(tts_text(hidden)),tts_text(hidden))

    def test_synthesis_refuses_changed_or_empty_text_instead_of_silent_cleanup(self):
        for text in ['条件≤30。','（背景音乐渐弱）事实。','[SECTION_BREAK]']:
            with self.assertRaises(RuntimeError):tts_segments(text)
        canonical=tts_text('条件≤30。（市场处于过渡区间）[SECTION_BREAK]反证应保留。')
        self.assertEqual(tts_segments(canonical),canonical.split('[SECTION_BREAK]'))

    def test_background_scope_attribution_and_notes_are_preserved(self):
        text='该研报（仅作历史背景，不代表今日催化）提供对照。\n增长预测（来源：某机构，尚未证实）。\n注：若价格续跌，则原判断失效。'
        result=clean(text)
        for phrase in ['仅作历史背景，不代表今日催化','来源：某机构，尚未证实','若价格续跌，则原判断失效']:
            self.assertIn(phrase,result)

    def test_only_pure_stage_directions_are_removed(self):
        text='（背景音乐渐弱，停顿两秒）正文[SECTION_BREAK](music fades)\n*音乐淡出*\n（市场处于过渡区间）（观察间隔三秒）'
        result=clean(text)
        self.assertNotIn('music fades',result);self.assertNotIn('背景音乐渐弱',result)
        self.assertNotIn('音乐淡出',result);self.assertIn('[SECTION_BREAK]',result)
        self.assertIn('市场处于过渡区间',result);self.assertIn('观察间隔三秒',result)
        self.assertEqual(clean('三秒内完成（三秒）'),'三秒内完成（三秒）')
        self.assertIn('业务（音乐）收入增长',clean('业务（音乐）收入增长。'))
        self.assertIn('讲话（语气严肃）',clean('讲话（语气严肃）并非新增政策。'))
        self.assertIn('2026. 10月披露',clean('2026. 10月披露。'))

    def test_signs_values_time_and_currency_are_not_erased(self):
        result=clean('14:08价格72.23元，涨幅+8.19%；对照（-0.35），亏损9.71亿元。')
        for value in ['14:08','72.23元','正百分之8.19','（-0.35）','9.71亿元']:self.assertIn(value,result)
        self.assertIn('负百分之2.94',clean('涨跌幅-2.94%。'))
        self.assertEqual(clean(result),result)

    def test_table_conversion_keeps_headers_cells_and_units(self):
        table='| 股票 | 时间 | 涨跌幅 |\n|---|---|---|\n| 示例公司 | 14:08 | -2.94% |\n注：样本不完整。'
        result=clean(table)
        for value in ['股票：示例公司','时间：14:08','涨跌幅：负百分之2.94','样本不完整']:self.assertIn(value,result)

    def test_only_known_terminal_source_catalogue_is_removed(self):
        body='事实与条件[N:source]。'
        tail='\n\n## 本期引用来源\n以下为采集来源，来源存在不等于内容已被独立证实。\n- [N:source] 文题｜机构｜日期｜https://example.com/a'
        self.assertEqual(report_body(body+tail),body)
        unsafe=body+tail+'\n新增风险条件不能删除。'
        self.assertEqual(report_body(unsafe),unsafe)
        self.assertIn('新增风险条件不能删除',clean(unsafe))

    def test_links_citations_and_metadata_do_not_swallow_adjacent_conditions(self):
        text='[来源报道](https://example.com/a)支持判断[N:source]。详见https://example.com/a。若续跌则失效。'
        result=clean(text)
        self.assertIn('来源报道支持判断',result);self.assertIn('若续跌则失效',result)
        self.assertNotIn('http',result);self.assertNotIn('[N:',result)
        metadata=dict(title='标题',summary='摘要',core_opinions=[],market_analysis={})
        self.assertNotIn('core_opinions',clean('正文\n```json\n'+json.dumps(metadata)+'\n```'))
        self.assertIn('风险条件：数据不完整',clean('```text\n风险条件：数据不完整\n```'))

    def test_audit_is_advisory_not_a_quality_score(self):
        result=audit(('相同句子，需要保留重要反证。\n'*2)+'时间14:08价格72.23涨幅8.19对照9.71。')
        self.assertTrue(result['repeated_sentences']);self.assertTrue(result['number_dense_sentences'])
        self.assertNotIn('score',result);self.assertIn('未合成音频',result['limitation'])


class SpokenCheckpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_exact_canonical_text_is_reviewed_checkpointed_and_sent_to_engine(self):
        from app.models.report import ReportType
        generator=PodcastGeneratorService.__new__(PodcastGeneratorService);generator.ai_client=True
        raw='未来1—3日，如果指标≤30，观察反弹（市场处于过渡区间，不代表已经反转）。[SECTION_BREAK]如果回落，原判断失效。'
        generator._call_ai_for_podcast=AsyncMock(return_value=reply(raw,'事实与条件'))
        generator._verify_podcast_script=AsyncMock()
        generator._generate_tts_edge_with_fallback=AsyncMock(return_value=True)
        report=SimpleNamespace(content='事实与条件',title='测试',id='id',summary='',core_opinions=[])
        with tempfile.TemporaryDirectory() as folder:
            def save(report,raw,script,load,**kwargs):return save_spoken_case(report,raw,script,load,folder,**kwargs)
            with patch('app.services.report_diagnostics.save_spoken_case',side_effect=save):
                script=await generator._generate_ai_podcast_script(report,'',date(2026,10,28),ReportType.MORNING,False)
            # A concise script is valid input for review; there is no 200-character floor.
            self.assertLess(len(script),200)
            generator._verify_podcast_script.assert_awaited_once_with(script,report)
            case=json.loads(next(Path(folder).glob('spoken-*.json')).read_text(encoding='utf-8'))
            self.assertEqual(case['script'],script);self.assertEqual(case['raw_script'],reply(raw,report.content))
            import hashlib
            self.assertEqual(case['script_sha256'],hashlib.sha256(script.encode('utf-8')).hexdigest())
            with patch('edge_tts.Communicate',side_effect=AssertionError('no TTS network')):
                await generator._generate_segmented_tts(script,str(Path(folder)/'unused.mp3'))
            self.assertEqual(generator._generate_tts_edge_with_fallback.call_args.args[0],tts_segments(script))
            self.assertEqual(generator._call_ai_for_podcast.await_count,1)

    async def test_noncanonical_text_stops_before_either_engine(self):
        generator=PodcastGeneratorService.__new__(PodcastGeneratorService)
        generator._generate_tts_edge_with_fallback=AsyncMock(return_value=True)
        generator._generate_tts_siliconflow=AsyncMock(return_value=True)
        with self.assertRaises(RuntimeError):await generator._generate_segmented_tts('若指标≤30，则观察。','unused.mp3')
        generator._generate_tts_edge_with_fallback.assert_not_awaited()
        generator._generate_tts_siliconflow.assert_not_awaited()

    def test_cache_changes_with_format_version_and_rejects_uncanonical_script(self):
        from app.services import podcast_script_cache as cache
        report=SimpleNamespace(content='事实与条件')
        with tempfile.TemporaryDirectory() as folder:
            script=tts_text('若收益≥2%，判断需要修正。')
            cache.save(report,'用户',script,folder)
            self.assertEqual(cache.load(report,'用户',folder),script)
            with patch.object(cache,'TTS_TEXT_VERSION','new-version'):
                self.assertIsNone(cache.load(report,'用户',folder))
            with self.assertRaises(ValueError):cache.save(report,'用户','若收益≥2%，检查。',folder)

    async def test_failed_model_review_keeps_paid_script_and_recovery_needs_no_model(self):
        report=SimpleNamespace(content='事实与条件',title='报告',id='report-id',summary='',core_opinions=[])
        generator=PodcastGeneratorService.__new__(PodcastGeneratorService);generator.ai_client=True
        generator._call_ai_for_podcast=AsyncMock(return_value=reply('（仅作历史背景，不能认定当日催化）事实解释和反证。'*15,report.content))
        generator._verify_podcast_script=AsyncMock(side_effect=RuntimeError('review failed'))
        with tempfile.TemporaryDirectory() as folder:
            def save(report,raw,script,load,**kwargs):return save_spoken_case(report,raw,script,load,folder,**kwargs)
            with patch('app.services.report_diagnostics.save_spoken_case',side_effect=save),patch('requests.get',side_effect=AssertionError('no network')):
                with self.assertRaisesRegex(RuntimeError,'review failed'):
                    await generator._generate_ai_podcast_script(report,'',date(2026,10,28),__import__('app.models.report',fromlist=['ReportType']).ReportType.MORNING,False)
            paths=list(Path(folder).glob('spoken-*.json'));self.assertEqual(len(paths),1)
            data=json.loads(paths[0].read_text(encoding='utf-8'))
            self.assertEqual(data['status'],'review_failed');self.assertIn('仅作历史背景',data['script'])
            from app.spoken_check import inspect
            result=inspect(paths[0]);self.assertEqual(result['scope'],'saved_spoken_script')
            generator._call_ai_for_podcast.assert_awaited_once()

    async def test_checkpoint_failure_stops_before_another_paid_review(self):
        report=SimpleNamespace(content='事实',title='报告')
        generator=PodcastGeneratorService.__new__(PodcastGeneratorService);generator.ai_client=True
        generator._call_ai_for_podcast=AsyncMock(return_value=reply('已有事实与条件。'*40,report.content))
        generator._verify_podcast_script=AsyncMock()
        from app.models.report import ReportType
        with patch('app.services.report_diagnostics.save_spoken_case',side_effect=RuntimeError('disk failure')):
            with self.assertRaisesRegex(RuntimeError,'disk failure'):
                await generator._generate_ai_podcast_script(report,'',date(2026,10,28),ReportType.MORNING,False)
        generator._verify_podcast_script.assert_not_awaited()

    async def test_transient_spoken_cases_expire_without_deleting_audio_or_reports(self):
        from app.services.material_lifecycle import prune_material_caches
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);target=root/'diagnostics/spoken-old.json';target.parent.mkdir()
            now=datetime(2026,10,28,15)
            target.write_text(json.dumps(dict(owner='finance-spoken-v1',at=(now-timedelta(days=2)).isoformat())))
            audio=root/'podcasts/keep.mp3';audio.parent.mkdir();audio.write_bytes(b'keep')
            result=prune_material_caches(root,now)
            self.assertIn(str(Path('diagnostics')/'spoken-old.json'),result['removed']);self.assertEqual(audio.read_bytes(),b'keep')
