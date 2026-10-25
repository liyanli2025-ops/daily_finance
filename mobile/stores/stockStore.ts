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
  latest_confidence?: number | null;
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
  addToWatchlist: (stock: { code: string; name: string; market: string }) => Promise<boolean>;
  removeFromWatchlist: (stockId: string) => Promise<boolean>;
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
      
      set({ searchResults: [], isSearching: false, error: '搜索失败，请重试' });
    }
  },

  addToWatchlist: async (stock: { code: string; name: string; market: string }) => {
    try {
      const newStock = await api.addToWatchlist(stock);
      const currentList = get().watchlist;
      set({ watchlist: [...currentList, newStock], error: null });
      return true;
    } catch (error) {
      console.error('添加自选股失败:', error);
      
      set({ error: '添加失败，未保存到服务器' });
      return false;
    }
  },

  removeFromWatchlist: async (stockId: string) => {
    try {
      await api.removeFromWatchlist(stockId);
      const currentList = get().watchlist;
      set({ watchlist: currentList.filter((s) => s.id !== stockId), error: null });
      return true;
    } catch (error) {
      console.error('移除自选股失败:', error);
      set({ error: '移除失败，服务器列表未改变' });
      return false;
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
