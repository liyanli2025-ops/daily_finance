"""Only traceable articles may enter the writer's evidence pool."""
from datetime import datetime
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app.models.news import News, NewsType
from app.services.ai_analyzer import AIAnalyzerService
from app.services.evidence import validate_citations


def item(identifier, url, **kwargs):
    return News(id=identifier, title='新闻' + identifier, content='完整新闻内容',
                source='测试来源', source_url=url,
                published_at=datetime(2026, 10, 23, 12), **kwargs)


class TraceableInputsTests(unittest.TestCase):
    def test_bad_links_are_filtered_before_the_forty_article_quota(self):
        pool = [item('bad' + str(i), 'https://example.com/', importance_score=1)
                for i in range(45)]
        pool.append(item('valid-full-id', 'https://example.com/articles/1', importance_score=0.1))
        analyzer = AIAnalyzerService.__new__(AIAnalyzerService)
        with patch('app.services.ai_analyzer.get_watchlist_service',
                   return_value=SimpleNamespace(get_all_stocks=lambda: [])):
            summary = analyzer._prepare_news_summary_with_sentiment(pool)
        self.assertEqual([n.id for n in analyzer._selected_evidence_news], ['valid-full-id'])
        self.assertIn('[N:valid-full-id]', summary)
        self.assertNotIn('[N:bad', summary)

    def test_cross_border_bad_links_do_not_consume_category_quota(self):
        pool = [item('bad' + str(i), '', news_type=NewsType.TECH) for i in range(4)]
        pool.append(item('valid', 'https://example.com/articles/2', news_type=NewsType.TECH))
        analyzer = AIAnalyzerService.__new__(AIAnalyzerService)
        summary = analyzer._prepare_cross_border_summary(pool)
        self.assertEqual([n.id for n in analyzer._cross_border_evidence_news], ['valid'])
        self.assertNotIn('[N:bad', summary)

    def test_repair_diagnostics_identify_the_exact_invalid_reference(self):
        with self.assertRaisesRegex(RuntimeError, r'\[N:unknown\]'):
            validate_citations('[N:unknown]', [])
        with self.assertRaisesRegex(RuntimeError, r'\[N:homepage\]'):
            validate_citations('[N:homepage]', [item('homepage', 'https://example.com/')])
