"""Offline generic publication widgets: no publisher names or live requests."""
from datetime import datetime
import unittest
from unittest.mock import patch
from bs4 import BeautifulSoup
from app.services.article_metadata import headline_publication_fields, visible_publication_fields
from app.services.web_research import parse_visible_article
from app.services.primary_material_quality import review_body

TITLE = '市场收盘与已披露经济数据核对'
DATE = '2026-11-14 07:12:44'


def page(content):
    return '<html><head><title>' + TITLE + ' - 示例财经</title></head><body>' + content + '</body></html>'


def fields(content):
    return headline_publication_fields(BeautifulSoup(page(content), 'html.parser'))


class HeadlinePublicationTests(unittest.TestCase):
    def test_semantic_header_datetime_is_read_without_itemprop(self):
        self.assertEqual(fields('<article><header><h1>'+TITLE+'</h1><time datetime="2026-11-13T23:12:44Z">07:12</time></header></article>'), ['2026-11-13T23:12:44Z'])

    def test_compact_sibling_widget_ignores_unstable_css_names(self):
        self.assertEqual(fields('<div><h1>'+TITLE+'</h1><div class="generated-css"><i></i><span>'+DATE+'</span><a>记者</a></div><p>新闻正文</p></div>'), [DATE])

    def test_matching_h2_headline_has_publication_widget(self):
        self.assertEqual(fields('<div><h2>'+TITLE+'</h2><div><a>作者</a><i>'+DATE+'</i></div></div>'), [DATE])

    def test_duplicate_responsive_publication_is_one_field(self):
        self.assertEqual(fields('<div><h1>'+TITLE+'</h1><div><span>'+DATE+'</span></div><div><span>'+DATE+'</span></div></div>'), [DATE])

    def test_conflicting_header_clocks_require_review(self):
        self.assertEqual(fields('<header><h1>'+TITLE+'</h1><span>'+DATE+'</span><span>2026-11-14 08:00:00</span></header>'), [])

    def test_recommendations_do_not_supply_missing_publication(self):
        for wrapper in ('<aside>{}</aside>', '<div class="related-news">{}</div>', '<footer>{}</footer>'):
            with self.subTest(wrapper=wrapper):
                self.assertEqual(fields('<main><h1>'+TITLE+'</h1>'+wrapper.format('<time datetime="2026-11-14T08:00:00+08:00">08:00</time>')+'</main>'), [])

    def test_hidden_header_cannot_supply_publication(self):
        for attribute in ('hidden', 'aria-hidden="true"', 'style="display:none"', 'class="hidden"'):
            with self.subTest(attribute=attribute):
                self.assertEqual(fields('<header '+attribute+'><h1>'+TITLE+'</h1><span>'+DATE+'</span></header>'), [])

    def test_body_paragraph_and_script_dates_are_not_publication(self):
        self.assertEqual(fields('<div><h1>'+TITLE+'</h1><p>'+DATE+'</p><script>published="'+DATE+'"</script></div>'), [])

    def test_modified_field_and_children_are_not_publication(self):
        self.assertEqual(fields('<header><h1>'+TITLE+'</h1><time itemprop="dateModified" datetime="2026-11-14T08:00:00Z"><span>'+DATE+'</span></time></header>'), [])

    def test_unrelated_heading_and_header_clock_are_not_borrowed(self):
        self.assertEqual(fields('<header><h1>网站首页及推荐资讯导航</h1><span>'+DATE+'</span></header>'), [])

    def test_clock_without_date_and_title_date_are_not_inferred(self):
        self.assertEqual(fields('<header><h1>'+TITLE+'</h1><time>07:12</time></header>'), [])
        html='<title>2026-11-14 07:12:44</title><header><h1><span>'+DATE+'</span></h1></header>'
        self.assertEqual(headline_publication_fields(BeautifulSoup(html,'html.parser')), [])

    def test_parser_keeps_unknown_timezone_at_day_precision(self):
        body='公开市场情况与来源限制均需核对。'*20
        html=page('<h1>'+TITLE+'</h1><div><span>'+DATE+'</span></div><div>'+body+'</div>')
        with patch('app.services.generic_extraction.extract_main_text', return_value=dict(status='text_candidate',text=body,method='example',version='1',warnings=[])):
            item=parse_visible_article(html,'https://example.com/article',datetime(2026,11,14,9),hours=96)
        self.assertIn('来源未标时区',item.market_impact)
        self.assertIn('精度：day',item.market_impact)

    def test_stale_or_future_publication_stays_outside_window(self):
        for stamp in ('2026-10-01T07:00:00+08:00','2026-11-15T07:00:00+08:00'):
            html=page('<article><header><h1>'+TITLE+'</h1><time datetime="'+stamp+'">07:00</time></header><p>'+('实际公开正文需要核对。'*20)+'</p></article>')
            with self.subTest(stamp=stamp),self.assertRaisesRegex(ValueError,'time_outside_window'):
                parse_visible_article(html,'https://example.com/article',datetime(2026,11,14,9),hours=96)

    def test_explicit_old_publication_is_not_replaced_with_recommendation_date(self):
        html=page('<header><h1>'+TITLE+'</h1><time datetime="2026-11-10T07:00:00Z">07:00</time></header><aside><time datetime="2026-11-14T08:00:00Z">08:00</time></aside>')
        self.assertEqual(visible_publication_fields(BeautifulSoup(html,'html.parser')),['2026-11-10T07:00:00Z'])


class TrainingPromotionTests(unittest.TestCase):
    def test_course_invitation_is_flagged_without_modifying_source(self):
        raw='别只围观AI风口，零基础实操课程，限额50人，点击了解课程并立即报名！市场随后回落。'
        result=review_body(raw)
        self.assertIn('training_course_promotion',{r['code'] for r in result['findings']})
        self.assertTrue(result['requires_editorial_review'])
        self.assertFalse(result['text_modified'])
        self.assertIn('市场随后回落',raw)

    def test_education_news_alone_is_not_a_course_invitation(self):
        self.assertFalse(review_body('公司披露职业培训业务收入，课程体系更新；招生人数增长，仍有经营风险。')['requires_editorial_review'])
