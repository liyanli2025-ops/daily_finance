from datetime import datetime,timedelta
from pathlib import Path
from types import SimpleNamespace
import tempfile,time
import unittest
from unittest.mock import Mock,AsyncMock,patch
import requests

from app.services.source_health import ensure_active,record_failure,permanent_reason,RetiredSourceError,state_path
from app.services.research_hub import ResearchHub
from app.services.primary_sources import cached
from app.services.technical_radar import TechnicalRadar
from app.services.news_collector import NewsCollectorService


class SourceHealthTests(unittest.TestCase):
    def test_legacy_failed_parser_cache_is_migrated_without_a_probe(self):
        with tempfile.TemporaryDirectory() as folder:
            hub=ResearchHub(folder)
            hub.cache('primary:attempt:legacy-article',600,lambda:dict(ok=False,error='ValueError',reason=None))
            fetch=Mock(side_effect=AssertionError('must not probe'))
            with self.assertRaises(ValueError):cached(hub,'legacy-article',600,fetch)
            self.assertTrue(state_path(folder,'legacy-article').exists())
            with self.assertRaises(RetiredSourceError):cached(ResearchHub(folder),'legacy-article',600,fetch)
            fetch.assert_not_called()

    def test_known_http_failure_survives_cache_expiry_and_new_instance(self):
        with tempfile.TemporaryDirectory() as folder:
            response=requests.Response();response.status_code=404
            fetch=Mock(side_effect=requests.HTTPError('untrusted body',response=response))
            with self.assertRaises(ValueError):cached(ResearchHub(folder),'article-one',1,fetch)
            future=datetime(2026,11,1)
            with patch('app.services.research_hub.china_now',return_value=future):
                with self.assertRaises(RetiredSourceError):cached(ResearchHub(folder),'article-one',1,fetch)
            self.assertEqual(fetch.call_count,1)
            self.assertNotIn('untrusted',state_path(folder,'article-one').read_text())
            self.assertEqual(cached(ResearchHub(folder),'different-article',1,lambda:'ok'),'ok')

    def test_body_failure_does_not_retry_every_ten_minutes(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertTrue(record_failure(folder,'one',ValueError('publisher_full_body_unavailable')))
            with self.assertRaises(RetiredSourceError):ensure_active(folder,'one')
            ensure_active(folder,'another')

    def test_transient_and_budget_errors_do_not_retire_entire_source(self):
        self.assertIsNone(permanent_reason(TimeoutError('budget')))
        # Observed transport failures now pause the exact adapter key under
        # the user's no-repeat requirement; this does not ban the publisher.
        self.assertEqual(permanent_reason(requests.Timeout()),'observed_request_timeout_no_auto_retest')
        self.assertEqual(permanent_reason(requests.exceptions.SSLError()),'tls_verification_failed')
        for status in [429,500,503]:
            response=requests.Response();response.status_code=status
            self.assertIsNone(permanent_reason(requests.HTTPError(response=response)))

    def test_failed_proxy_is_stopped_before_network(self):
        with tempfile.TemporaryDirectory() as folder:
            radar=TechnicalRadar(folder)
            with patch('app.services.technical_radar.requests.get') as get:
                with self.assertRaisesRegex(ValueError,'no_retest'):
                    radar.fetch(dict(symbol='sh512660',kind='sector_proxy'),time.monotonic()+10)
            get.assert_not_called()


class PausedFeedTests(unittest.IsolatedAsyncioTestCase):
    async def test_new_feed_404_is_persistently_paused_before_next_request(self):
        with tempfile.TemporaryDirectory() as folder:
            collector=NewsCollectorService.__new__(NewsCollectorService)
            collector._rss_state_root=Path(folder)
            response=requests.Response();response.status_code=404
            collector.client=SimpleNamespace(get=AsyncMock(side_effect=requests.HTTPError(response=response)))
            feed=dict(name='新发现的失败路由',url='https://example.com/rss')
            await collector._collect_rss(feed)
            await collector._collect_rss(feed)
            self.assertEqual(collector.client.get.await_count,1)
            self.assertEqual(collector._rss_coverage[feed['name']]['status'],'disabled')

    async def test_previously_failed_feed_never_calls_another_node_after_cooldown(self):
        collector=NewsCollectorService.__new__(NewsCollectorService)
        collector.client=SimpleNamespace(get=AsyncMock(side_effect=AssertionError('must not request')))
        result=await collector._collect_rss(dict(name='金十数据',url='{RSSHUB}/jin10'))
        self.assertEqual(result,[]);collector.client.get.assert_not_awaited()
        self.assertEqual(collector._rss_coverage['金十数据']['status'],'disabled')
