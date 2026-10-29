import json
import unittest

from app.services.evidence_reading import read_news,render_initial_news
from app.services.prompt_reading import compact_market,restore_market,MARKET_MAP


class InputPresentationTests(unittest.TestCase):
    def test_compact_news_preserves_every_selected_source_slice_and_followup(self):
        text='行业经营发生变化。'+('一般背景。'*100)+'公司表示，订单增长20%。不过，这并不代表需求一定改善。'+('尾部背景。'*100)
        reading=read_news(text,'订单变化',300)
        rendered=render_initial_news(text,reading)
        for start,end in reading['ranges']:
            self.assertIn(text[start:end],rendered)
            self.assertIn(f'【原文字符{start}:{end} / 总长{len(text)}】',rendered)
        if reading['followup_ranges']:
            self.assertIn(str(reading['followup_ranges']),rendered)
            self.assertIn('未提供',rendered)
        self.assertLess(len(rendered),len(reading['text']))

    def test_short_full_text_is_not_changed_by_initial_renderer(self):
        text='公司预计需求可能改善，不代表实现结果。'
        self.assertEqual(render_initial_news(text,read_news(text)),text)

    def test_shorter_json_keys_compress_losslessly_with_identity_and_status_readable(self):
        data={'windows':[{'symbol':'dynamic','benchmark':'same-market','status':'diagnostic_only','periods':20,'returns_pct':-1.2345,'signals':[1,2,3],'source_url':'https://example.com','as_of':'2026-10-28'} for _ in range(40)]}
        original=json.dumps(data,ensure_ascii=False)
        compact=compact_market(original)
        self.assertLess(len(compact),len(original))
        self.assertIn(MARKET_MAP,compact)
        self.assertIn('"symbol":"dynamic"',compact)
        self.assertIn('"status":"diagnostic_only"',compact)
        self.assertEqual(json.loads(restore_market(compact)),data)
