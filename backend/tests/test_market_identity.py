"""Do not merge Hong Kong index identities or currency variants."""
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
import pandas as pd
from app.services.market_data_service import MarketDataService, MarketOverview


class MarketIdentityTests(unittest.IsolatedAsyncioTestCase):
    async def test_exact_hk_names_exclude_variants_and_duplicates(self):
        provider = SimpleNamespace(index_global_em=lambda: None,
                                   index_us_stock_sina=lambda: None,
                                   stock_hk_index_spot_em=lambda: None)
        frame = pd.DataFrame([
            {'名称':'恒生指数','最新价':20000,'涨跌幅':0.58},
            {'名称':'恒生科技指数','最新价':4000,'涨跌幅':1.58},
            {'名称':'恒生科技指数(美元)','最新价':500,'涨跌幅':2.5},
            {'名称':'恒生科技指数','最新价':4000,'涨跌幅':1.58},
        ])
        service = MarketDataService.__new__(MarketDataService)
        service._call_akshare_with_retry = AsyncMock(side_effect=[None, None, frame])
        with patch.dict(sys.modules, {'akshare':provider}), patch(
                'app.services.market_data_service.asyncio.sleep', new=AsyncMock()):
            rows = await service._get_global_indices()
        self.assertEqual([(r.name,r.change_pct) for r in rows], [('恒生指数',0.58),('恒生科技指数',1.58)])

    def test_overview_does_not_label_query_date_as_market_timestamp(self):
        text = MarketOverview(date='2026-10-23').to_prompt_text()
        self.assertIn('查询目标日期', text)
        self.assertIn('不等于各项来源行情时间', text)
        self.assertIn('不能当作同一时点', text)
