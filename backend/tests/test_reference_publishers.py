import unittest
from app.services.overseas_sources import discover,parse_article,permitted


class ReferencePublishersTests(unittest.TestCase):
    def test_techcrunch_map_and_exact_body(self):
        url='https://techcrunch.com/2026/10/30/ai-credit/'
        xml=f'<urlset xmlns:news="http://www.google.com/schemas/sitemap-news/0.9"><url><loc>{url}</loc><news:news><news:title>AI credit market risk</news:title></news:news></url></urlset>'
        self.assertEqual(discover('techcrunch',xml)[0]['url'],url)
        body='A reported financing development. '*15
        html='<h1>AI credit market risk</h1><meta property="article:published_time" content="2026-10-30T21:52:03+00:00"><div class="entry-content"><p>'+body+'</p><div><p>RELATED FOOTER</p></div></div>'
        row=parse_article('techcrunch',html,url)
        self.assertNotIn('RELATED FOOTER',row['body'])
        self.assertEqual(row['published'],'2026-10-31T05:52:03')

    def test_fastbull_millisecond_date_and_body(self):
        url='https://www.fastbull.com/cn/news-detail/123_1'
        html='<h1>宏观市场变化</h1><div class="news-detail-main"><div class="detail-description"><span class="timedate" data-time="1793323375192"></span></div><div class="news-detail-content">'+'公开宏观报道。'*50+'</div></div>'
        row=parse_article('fastbull',html,url)
        self.assertEqual(row['precision'],'millisecond')
        self.assertTrue(row['published'].startswith('2026-10-30'))
        with self.assertRaises(ValueError):parse_article('fastbull',html.replace('data-time','missing-time'),url)

    def test_host_and_paywall(self):
        self.assertFalse(permitted('techcrunch','https://techcrunch.com.evil.test/2026/10/30/ai/'))
        with self.assertRaises(ValueError):
            parse_article('techcrunch','<script type="application/ld+json">{"isAccessibleForFree":false}</script>', 'https://techcrunch.com/2026/10/30/ai/')

    def test_observed_transport_failure_pauses_exact_route(self):
        import tempfile
        import requests
        from app.services.source_health import record_failure,ensure_active,RetiredSourceError
        with tempfile.TemporaryDirectory() as root:
            self.assertTrue(record_failure(root,'overseas:index:v1:new_source',requests.exceptions.ReadTimeout()))
            with self.assertRaises(RetiredSourceError):ensure_active(root,'overseas:index:v1:new_source')
            ensure_active(root,'overseas:index:v1:another_source')
