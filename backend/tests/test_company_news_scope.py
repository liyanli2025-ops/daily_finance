from datetime import datetime
from types import SimpleNamespace
import unittest

from app.services.company_news_scope import decision, partition


def item(title, content='', category=''):
    return SimpleNamespace(id=title,title=title,content=content,category=category,
                           related_stocks=[],source='',published_at=datetime(2026,10,30))


class CompanyNewsScopeTests(unittest.TestCase):
    def setUp(self):
        self.stock=SimpleNamespace(code='123456',name='动态自选甲',market='A')

    def test_watchlist_changes_are_respected(self):
        news=item('动态自选甲：前三季度净利润增长4%')
        self.assertTrue(decision(news,[self.stock])['keep'])
        self.assertFalse(decision(news,[])['keep'])

    def test_body_mention_does_not_make_other_company_watchlist(self):
        self.assertFalse(decision(item('普通公司：三季度净利润增长4%', '文章末尾提到动态自选甲'),[self.stock])['keep'])

    def test_market_and_industry_are_preserved(self):
        for title in ('A股收评：全市场4600只下跌','多家芯片公司财报后下跌，产业链订单出现变化','全球能源供应链遭遇冲击'):
            self.assertTrue(decision(item(title),[])['keep'],title)

    def test_concrete_controversy_is_a_lead_not_verified_heat(self):
        result=decision(item('非自选公司：涉嫌财务造假被立案调查'))
        self.assertTrue(result['keep'])
        self.assertIn('not_confirmed_public_opinion',result['reason'])

    def test_promotion_and_high_growth_do_not_prove_importance(self):
        for title in ('普通公司：三季度净利润增长600%','普通公司：前三季度营收同比增长4%'):
            self.assertFalse(decision(item(title))['keep'])

    def test_related_company_requires_current_dated_source(self):
        row=dict(aliases=['产业公司乙'],role='industry_representative',
                 source_url='https://example.com/research/sector',as_of='2026-10-01',valid_until='2026-11-01')
        profiles={'A:123456':dict(related_companies=[row])}
        news=item('产业公司乙：第三季度净利润增长4%')
        self.assertEqual(decision(news,[self.stock],profiles)['reason'],'sourced_related_company')
        row['valid_until']='2026-10-29'
        self.assertFalse(decision(news,[self.stock],profiles)['keep'])
        row['valid_until']='2026-11-01';row['source_url']=''
        self.assertFalse(decision(news,[self.stock],profiles)['keep'])

    def test_excluded_rows_remain_inspectable(self):
        news=item('普通公司：三季度净利润增长4%')
        kept,excluded=partition([news])
        self.assertEqual(kept,[])
        self.assertEqual(excluded[0]['id'],news.id)


if __name__=='__main__':unittest.main()
