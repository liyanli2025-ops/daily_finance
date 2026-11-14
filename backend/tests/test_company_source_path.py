"""Public-source diagnostic boundaries; all HTTP responses are local fakes."""
from datetime import datetime
import importlib.util
import json
from pathlib import Path
import tempfile
import time
import unittest

ROOT=Path(__file__).parents[2]
spec=importlib.util.spec_from_file_location('company_source_path',ROOT/'tools/check_company_source_path.py')
probe=importlib.util.module_from_spec(spec);spec.loader.exec_module(probe)

STOCK=dict(market='A',code='600001',name='示例股份')
NOW=datetime(2026,11,14,9,0)


def listing(**overrides):
    value=dict(codes=[dict(stock_code='600001')],display_time='2026-11-13 18:00:00',
        notice_date='2026-11-14',title='示例股份：项目披露',art_code='AN202611130000000001')
    value.update(overrides);return value


def page(index=1,count=1,**overrides):
    value=dict(art_code='AN202611130000000001',page_size=count,notice_content='示例公告第'+str(index)+'页正文。'*30)
    value.update(overrides);return dict(data=value)


class CompanySourcePathTests(unittest.TestCase):
    def collect(self,rows,pages):
        calls=[]
        def get(url,**kwargs):
            calls.append((url,kwargs))
            data=dict(data={'list':rows}) if url==probe.LIST_URL else pages[len(calls)-2]
            from types import SimpleNamespace
            return SimpleNamespace(raise_for_status=lambda:None,json=lambda:data)
        stock=type('Stock',(),STOCK)()
        result=probe.load_collector()(stock,now=NOW,hours=168,request_get=get,
            max_announcements=1,max_pages=2)
        return result,calls

    def test_wrong_company_old_and_future_rows_do_not_trigger_body_requests(self):
        rows=[listing(codes=[dict(stock_code='600002')]),
              listing(display_time='2026-10-30 18:00:00'),listing(display_time='2026-11-15 18:00:00')]
        (items,status),calls=self.collect(rows,[])
        self.assertEqual(items,[]);self.assertEqual(len(calls),1);self.assertEqual(status['in_window'],0)

    def test_publication_and_document_date_remain_separate(self):
        (items,status),calls=self.collect([listing()],[page()])
        self.assertEqual(len(items),1);self.assertEqual(len(calls),2)
        self.assertEqual(items[0].published_at,datetime(2026,11,13,18))
        self.assertIn('2026-11-14',items[0].content)
        self.assertIn('两者不可混同',items[0].content)

    def test_only_one_announcement_selected_and_two_pages_complete(self):
        rows=[listing(),listing(art_code='AN202611120000000002',display_time='2026-11-12 18:00:00')]
        (items,status),calls=self.collect(rows,[page(1,2),page(2,2)])
        self.assertEqual(len(items),1);self.assertEqual(len(calls),3)
        self.assertIn('第1页',items[0].content);self.assertIn('第2页',items[0].content)
        self.assertEqual(status['in_window'],2);self.assertEqual(status['status'],'partial')

    def test_long_announcement_does_not_become_complete_body(self):
        (items,status),calls=self.collect([listing()],[page(1,3)])
        self.assertEqual(items,[]);self.assertEqual(len(calls),2);self.assertTrue(status['body_errors'])

    def test_repeated_page_or_wrong_document_cannot_be_evidence(self):
        for pages in ([page(1,2),page(1,2)],[page(art_code='AN999')]):
            with self.subTest(pages=pages):
                (items,status),_=self.collect([listing()],pages)
                self.assertEqual(items,[]);self.assertTrue(status['body_errors'])

    def test_invalid_announcement_id_never_reaches_body_endpoint(self):
        (items,_),calls=self.collect([listing(art_code='../../other')],[])
        self.assertEqual(items,[]);self.assertEqual(len(calls),1)

    def test_invalid_limits_fail_before_transport(self):
        collector=probe.load_collector()
        for kwargs in (dict(max_announcements=0),dict(max_announcements=4),dict(max_pages=0),dict(max_pages=6)):
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):
                collector(type('Stock',(),STOCK)(),request_get=lambda *a,**k:self.fail('network called'),**kwargs)

    def test_transport_rejects_unlisted_document_and_external_url(self):
        with tempfile.TemporaryDirectory() as temporary:
            calls=[];transport=probe.PublicTransport(Path(temporary),dict(watchlist=[STOCK]),
                request_get=lambda *a,**k:calls.append(True))
            for url,params in ((probe.BODY_URL,dict(art_code='AN999',page_index=1)),
                ('https://example.com/',dict(stock_list=STOCK['code']))):
                with self.assertRaises(ValueError):transport(url,params=params)
            self.assertEqual(calls,[]);self.assertEqual(transport.receipts,[])

    def test_transport_budget_and_duplicate_prevent_second_request(self):
        with tempfile.TemporaryDirectory() as temporary:
            class Response:
                status_code=200
                def iter_content(self,size):yield json.dumps(dict(data={'list':[listing()]})).encode()
                def close(self):pass
            calls=[]
            def get(*a,**k):calls.append(k);return Response()
            transport=probe.PublicTransport(Path(temporary),dict(watchlist=[STOCK]),get,max_requests=1)
            params=dict(stock_list=STOCK['code'],page_size=20,page_index=1)
            transport(probe.LIST_URL,params=params)
            with self.assertRaises(ValueError):transport(probe.BODY_URL,params=dict(art_code=listing()['art_code'],page_index=1))
            self.assertEqual(len(calls),1);self.assertFalse(calls[0]['allow_redirects'])
            self.assertEqual(len(transport.receipts),1)

    def test_redirect_is_not_followed_or_retried(self):
        with tempfile.TemporaryDirectory() as temporary:
            class Response:
                status_code=302
                def close(self):pass
            transport=probe.PublicTransport(Path(temporary),dict(watchlist=[STOCK]),lambda *a,**k:Response())
            params=dict(stock_list=STOCK['code'],page_size=20,page_index=1)
            with self.assertRaises(ValueError):transport(probe.LIST_URL,params=params)
            with self.assertRaises(ValueError):transport(probe.LIST_URL,params=params)
            self.assertEqual(len(transport.receipts),1)


if __name__=='__main__':unittest.main()
