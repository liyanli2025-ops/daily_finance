from datetime import datetime
import json,tempfile
import unittest
from unittest.mock import patch

from app.services.overseas_sources import parse_article,discover,permitted,iso_time,OverseasCollector,SOURCES
from app.services.news_quality import reading_scope

BODY='The source describes changing market conditions and gives its evidence. '*15
NOW=datetime(2026,10,25,18)


def bbc_html(date='2026-10-23T23:11:31Z',extra=''):
    return '<h1>Global market changes</h1><meta name="cXenseParse:publishtime" content="'+date+'"><article><div data-component="text-block">'+BODY+'</div><div data-component="links-block">Related article is not body</div></article>'+extra


class OverseasParserTests(unittest.TestCase):
    def test_utc_becomes_next_beijing_day_and_related_links_not_body(self):
        row=parse_article('bbc',bbc_html(),'https://www.bbc.com/news/articles/abc123')
        self.assertEqual(row['published'],'2026-10-24T07:11:31')
        self.assertEqual(row['original_time'],'2026-10-23T23:11:31Z')
        self.assertNotIn('Related article',row['body'])

    def test_missing_timezone_or_time_does_not_use_collection_time(self):
        for value in ['2026-10-23T23:11:31','unknown','']:
            with self.assertRaises(ValueError):parse_article('bbc',bbc_html(value),'https://www.bbc.com/news/articles/abc123')

    def test_restricted_schema_and_teaser_are_not_full_text(self):
        schema='<script type="application/ld+json">'+json.dumps({'@type':'NewsArticle','hasPart':{'isAccessibleForFree':False}})+'</script>'
        with self.assertRaisesRegex(ValueError,'restricted'):parse_article('bbc',bbc_html(extra=schema),'https://www.bbc.com/news/articles/abc123')
        with self.assertRaisesRegex(ValueError,'restricted'):parse_article('bbc',bbc_html().replace(BODY,BODY+' Subscribe to continue'),'https://www.bbc.com/news/articles/abc123')

    def test_guardian_body_has_its_own_publication_not_modified_time(self):
        html='<h1>Bank changes</h1><meta property="article:published_time" content="2026-10-23T09:00:00Z"><meta property="article:modified_time" content="2026-10-25T10:00:00Z"><div class="article-body-commercial-selector">'+BODY+'</div>'
        row=parse_article('guardian',html,'https://www.theguardian.com/business/2026/oct/23/bank-changes')
        self.assertEqual(row['published'],'2026-10-23T17:00:00')

    def test_treasury_takes_article_title_not_site_masthead_and_keeps_proposed_status(self):
        html='<h1>US Treasury</h1><h2 class="uswds-page-title">Proposed investment rule</h2><div class="field--name-field-news-publication-date"><time datetime="2026-10-22T21:00:00Z"></time></div><div class="field--name-field-news-body">'+BODY+'</div>'
        row=parse_article('treasury',html,'https://home.treasury.gov/news/press-releases/sb123/')
        self.assertEqual(row['title'],'Proposed investment rule');self.assertEqual(row['published'],'2026-10-23T05:00:00')

    def test_fed_edt_and_est_are_not_assumed_beijing(self):
        for zone,expected in [('EDT','2026-10-14T02:00:00'),('EST','2026-10-14T03:00:00')]:
            html='<div id="article"><div class="heading col-sm-8"><p class="article__time">October 13, 2026</p><h3 class="title">Policy release</h3><p class="releaseTime">For release at 2:00 p.m. '+zone+'</p></div><div class="col-sm-8">'+BODY+'</div></div>'
            row=parse_article('fed',html,'https://www.federalreserve.gov/newsevents/pressreleases/monetary20261013a.htm')
            self.assertEqual(row['published'],expected)

    def test_eia_day_precision_has_an_interval_not_an_invented_clock(self):
        html='<h1>EIA masthead</h1><div class="tie-article"><span class="date">October 22, 2026</span><h1>Oil market analysis</h1><p>'+BODY+'</p></div>'
        row=parse_article('eia',html,'https://www.eia.gov/todayinenergy/detail.php?id=123')
        self.assertEqual(row['title'],'Oil market analysis');self.assertEqual(row['precision'],'day')
        self.assertEqual(row['published'],'2026-10-21T18:00:00')
        self.assertEqual(row['publication_end'],'2026-10-23T20:00:00')
        self.assertIn('source timezone and publication clock not supplied',row['original_time'])

    def test_unverified_publishers_and_arbitrary_queries_are_not_allowed(self):
        self.assertNotIn('bloomberg',SOURCES);self.assertNotIn('wsj',SOURCES);self.assertNotIn('cnbc',SOURCES)
        for url in ['https://www.eia.gov/todayinenergy/detail.php?id=1&token=secret',
                    'https://127.0.0.1/news/articles/abc','http://www.bbc.com/news/articles/abc']:
            self.assertFalse(permitted('bbc',url))

    def test_day_only_time_label_does_not_expose_interval_start_as_publication_clock(self):
        from app.models.news import News
        from app.services.evidence import publication_label,source_notes
        row=News(id='eia-date',title='Oil analysis',content=BODY,source='EIA公开原文',
            source_url='https://www.eia.gov/todayinenergy/detail.php?id=1',published_at=datetime(2026,10,22,12),
            market_impact='原始来源时点：October 22, 2026 (US Eastern calendar date)；精度：day；存储时间为北京时间')
        self.assertNotIn('12:00',publication_label(row));self.assertNotIn('12:00',source_notes([row]))
        self.assertIn('日精度',publication_label(row))

    def test_discovery_uses_whitelisted_articles_not_summaries_as_evidence(self):
        content='<a href="/news/articles/abc123">China trade and chip markets change</a><a href="https://bad.example/news/articles/a">China market changes</a><a href="/news/videos/b">Watch market video</a>'
        result=discover('bbc',content)
        self.assertEqual(len(result),1);self.assertNotIn('body',result[0])


class OverseasCollectionTests(unittest.TestCase):
    def test_fed_date_only_legacy_rows_do_not_break_current_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            collector=OverseasCollector(folder)
            data=[dict(d='1/10/2006',t='Old policy release',pt='Monetary Policy',l='/newsevents/pressreleases/monetary20060110a.htm'),
                dict(d='10/16/2026 11:00:00 AM',t='Prior policy release',pt='Monetary Policy',l='/newsevents/pressreleases/monetary20261016a.htm')]
            with patch.object(collector,'index',return_value=json.dumps(data)),patch.object(collector,'detail') as detail, \
                    patch('app.services.overseas_sources.china_now',return_value=NOW):
                articles,status=collector.collect(72,10,providers=['fed'])
            detail.assert_not_called();self.assertEqual(articles,[])
            self.assertEqual(status['sources']['fed']['status'],'no_recent_material')
            self.assertEqual(status['sources']['fed']['outside_window'],2)

    def test_date_boundary_uncertainty_is_disclosed_and_not_counted_as_current(self):
        with tempfile.TemporaryDirectory() as folder:
            collector=OverseasCollector(folder)
            content='<a href="/todayinenergy/detail.php?id=123">Energy price market changes</a>'
            row=dict(title='Energy',body=BODY,published='2026-10-22T12:00:00',publication_end='2026-10-23T12:00:00',
                precision='day',original_time='October 22, 2026',url='https://www.eia.gov/todayinenergy/detail.php?id=123',source='EIA公开原文')
            with patch.object(collector,'index',return_value=content),patch.object(collector,'detail',return_value=row), \
                    patch('app.services.overseas_sources.china_now',return_value=NOW):
                articles,status=collector.collect(72,10,providers=['eia'])
            self.assertEqual(articles,[]);self.assertEqual(status['sources']['eia']['date_boundary_uncertain'],1)

    def test_current_overseas_body_enters_news_with_timezone_and_scope(self):
        with tempfile.TemporaryDirectory() as folder:
            collector=OverseasCollector(folder)
            row=parse_article('bbc',bbc_html(),'https://www.bbc.com/news/articles/abc123')
            with patch.object(collector,'index',return_value='<a href="/news/articles/abc123">Global stock markets change</a>'), \
                    patch.object(collector,'detail',return_value=row),patch('app.services.overseas_sources.china_now',return_value=NOW):
                articles,status=collector.collect(72,10,providers=['bbc'])
            self.assertEqual(len(articles),1);self.assertEqual(reading_scope(articles[0]),'full_text')
            self.assertEqual(articles[0].category,'海外市场原文');self.assertIn('2026-10-23T23:11:31Z',articles[0].market_impact)
            self.assertFalse(status['complete_window'])
