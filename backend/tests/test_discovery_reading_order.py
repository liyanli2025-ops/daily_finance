"""A busy company must not consume the body-fetch window before market checks."""
import unittest
from app.services.news_assignment import discovery_order
from app.services.public_news_sources import discover
from app.services.watchlist_service import WatchlistStock


class DiscoveryReadingOrderTests(unittest.TestCase):
    def test_many_watchlist_results_leave_early_fetch_opportunities_for_markets(self):
        stock=WatchlistStock('123456','测试公司','A')
        company=[dict(id=str(i),title=f'测试公司三季度利润增长{i}%') for i in range(20)]
        market=[dict(id='a',title='A股收评：创业板走弱'),
                dict(id='hk',title='港股收盘：恒生科技回落'),
                dict(id='us',title='美股收盘：纳指下跌'),
                dict(id='policy',title='央行宣布降息调整政策利率')]
        result=discovery_order(company+market,[stock])
        self.assertTrue({'a','hk','us','policy'}<={r['id'] for r in result[:5]})
        self.assertEqual({r['id'] for r in result},{r['id'] for r in company+market})

    def test_new_watchlist_members_do_not_wait_for_all_old_company_headlines(self):
        stocks=[WatchlistStock('123456','甲公司','A'),WatchlistStock('654321','乙公司','A')]
        rows=[dict(id=str(i),title=f'甲公司三季度利润增长{i}%') for i in range(12)]
        rows.append(dict(id='new',title='乙公司三季度利润下降'))
        self.assertIn('new',[r['id'] for r in discovery_order(rows,stocks)[:2]])

    def test_reprints_are_deferred_not_deleted_or_marked_read(self):
        rows=[dict(id='one',title='全球芯片库存下降'),dict(id='copy',title='全球芯片库存下降'),
              dict(id='counter',title='全球芯片库存下降但终端需求转弱')]
        result=discovery_order(rows)
        self.assertEqual([r['id'] for r in result],['one','counter','copy'])
        self.assertTrue(all('body_provided' not in r for r in result))

    def test_direct_publisher_uses_balancing_before_body_fetches(self):
        stocks=[WatchlistStock('123456','测试公司','A')]
        titles=[f'测试公司三季度利润增长{i}%' for i in range(10)]+['A股收评：创业板走弱']
        page=''.join(f'<a href="/articles/2026-10-31/{100+i}.html">{title}</a>' for i,title in enumerate(titles))
        rows=discover('nbd',page,stocks,{}, {})
        self.assertEqual(len(rows),len(titles))
        self.assertTrue(any('A股收评' in row['title'] for row in rows[:2]))
