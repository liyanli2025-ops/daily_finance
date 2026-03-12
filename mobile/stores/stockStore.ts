import { create } from 'zustand';
import { api } from '@/services/api';

interface Stock {
  id: string;
  code: string;
  name: string;
  market: 'A' | 'HK';
  current_price?: number;
  change_percent?: number;
  latest_prediction?: 'bullish' | 'neutral' | 'bearish';
  latest_confidence?: number;
  added_at: string;
  last_updated?: string;
}

interface SearchResult {
  code: string;
  name: string;
  market: string;
}

interface StockStore {
  watchlist: Stock[];
  searchResults: SearchResult[];
  currentStock: Stock | null;
  isLoading: boolean;
  isSearching: boolean;
  error: string | null;

  fetchWatchlist: () => Promise<void>;
  searchStocks: (keyword: string) => Promise<void>;
  addToWatchlist: (stock: { code: string; name: string; market: string }) => Promise<void>;
  removeFromWatchlist: (stockId: string) => Promise<void>;
  fetchStockDetail: (code: string, market: string) => Promise<void>;
  refreshWatchlist: () => Promise<void>;
}

export const useStockStore = create<StockStore>((set, get) => ({
  watchlist: [],
  searchResults: [],
  currentStock: null,
  isLoading: false,
  isSearching: false,
  error: null,

  fetchWatchlist: async () => {
    set({ isLoading: true, error: null });
    try {
      const watchlist = await api.getWatchlist();
      set({ watchlist, isLoading: false });
    } catch (error) {
      console.error('获取自选股失败:', error);
      set({ error: '获取自选股失败', isLoading: false });
      
      // 使用模拟数据
      set({
        watchlist: [
          {
            id: '1',
            code: '600519',
            name: '贵州茅台',
            market: 'A',
            current_price: 1688.88,
            change_percent: 1.23,
            latest_prediction: 'bullish',
            latest_confidence: 0.75,
            added_at: new Date().toISOString(),
          },
          {
            id: '2',
            code: '00700',
            name: '腾讯控股',
            market: 'HK',
            current_price: 345.60,
            change_percent: -0.56,
            latest_prediction: 'neutral',
            latest_confidence: 0.65,
            added_at: new Date().toISOString(),
          },
        ],
        isLoading: false,
      });
    }
  },

  searchStocks: async (keyword: string) => {
    if (!keyword.trim()) {
      set({ searchResults: [] });
      return;
    }

    set({ isSearching: true });
    try {
      const results = await api.searchStocks(keyword);
      set({ searchResults: results, isSearching: false });
    } catch (error) {
      console.error('搜索股票失败:', error);
      
      // 模拟搜索结果
      const mockResults = [
        { code: '600519', name: '贵州茅台', market: 'A' },
        { code: '000858', name: '五粮液', market: 'A' },
        { code: '00700', name: '腾讯控股', market: 'HK' },
        { code: '09988', name: '阿里巴巴-SW', market: 'HK' },
        { code: '002594', name: '比亚迪', market: 'A' },
      ].filter(
        (s) =>
          s.code.includes(keyword) ||
          s.name.toLowerCase().includes(keyword.toLowerCase())
      );

      set({ searchResults: mockResults, isSearching: false });
    }
  },

  addToWatchlist: async (stock: { code: string; name: string; market: string }) => {
    try {
      const newStock = await api.addToWatchlist(stock);
      const currentList = get().watchlist;
      set({ watchlist: [...currentList, newStock] });
    } catch (error) {
      console.error('添加自选股失败:', error);
      
      // 本地添加模拟
      const currentList = get().watchlist;
      const newStock: Stock = {
        id: Date.now().toString(),
        code: stock.code,
        name: stock.name,
        market: stock.market as 'A' | 'HK',
        current_price: Math.random() * 100 + 50,
        change_percent: (Math.random() - 0.5) * 10,
        latest_prediction: 'neutral',
        latest_confidence: 0.5,
        added_at: new Date().toISOString(),
      };
      set({ watchlist: [...currentList, newStock] });
    }
  },

  removeFromWatchlist: async (stockId: string) => {
    try {
      await api.removeFromWatchlist(stockId);
      const currentList = get().watchlist;
      set({ watchlist: currentList.filter((s) => s.id !== stockId) });
    } catch (error) {
      console.error('移除自选股失败:', error);
      // 本地移除
      const currentList = get().watchlist;
      set({ watchlist: currentList.filter((s) => s.id !== stockId) });
    }
  },

  fetchStockDetail: async (code: string, market: string) => {
    set({ isLoading: true, error: null });
    try {
      // TODO: 实现获取股票详情
      set({ isLoading: false });
    } catch (error) {
      console.error('获取股票详情失败:', error);
      set({ error: '获取股票详情失败', isLoading: false });
    }
  },

  refreshWatchlist: async () => {
    try {
      await api.refreshWatchlist();
      await get().fetchWatchlist();
    } catch (error) {
      console.error('刷新自选股失败:', error);
    }
  },
}));
