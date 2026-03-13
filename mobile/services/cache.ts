/**
 * 缓存服务
 * 处理本地数据缓存
 */
import AsyncStorage from '@react-native-async-storage/async-storage';

interface CacheItem<T> {
  data: T;
  timestamp: number;
  expiry?: number; // 过期时间（毫秒）
}

const CACHE_PREFIX = '@finance_daily_cache_';
const DEFAULT_EXPIRY = 30 * 60 * 1000; // 默认30分钟过期

class CacheService {
  /**
   * 设置缓存
   */
  async set<T>(key: string, data: T, expiry: number = DEFAULT_EXPIRY): Promise<boolean> {
    try {
      const cacheItem: CacheItem<T> = {
        data,
        timestamp: Date.now(),
        expiry,
      };
      await AsyncStorage.setItem(
        `${CACHE_PREFIX}${key}`,
        JSON.stringify(cacheItem)
      );
      return true;
    } catch (error) {
      console.error('缓存写入失败:', error);
      return false;
    }
  }

  /**
   * 获取缓存
   */
  async get<T>(key: string): Promise<T | null> {
    try {
      const cached = await AsyncStorage.getItem(`${CACHE_PREFIX}${key}`);
      if (!cached) return null;

      const cacheItem: CacheItem<T> = JSON.parse(cached);
      
      // 检查是否过期
      if (cacheItem.expiry) {
        const now = Date.now();
        if (now - cacheItem.timestamp > cacheItem.expiry) {
          await this.remove(key);
          return null;
        }
      }

      return cacheItem.data;
    } catch (error) {
      console.error('缓存读取失败:', error);
      return null;
    }
  }

  /**
   * 移除缓存
   */
  async remove(key: string): Promise<boolean> {
    try {
      await AsyncStorage.removeItem(`${CACHE_PREFIX}${key}`);
      return true;
    } catch (error) {
      console.error('缓存删除失败:', error);
      return false;
    }
  }

  /**
   * 清除所有缓存
   */
  async clearAll(): Promise<boolean> {
    try {
      const keys = await AsyncStorage.getAllKeys();
      const cacheKeys = keys.filter((key) => key.startsWith(CACHE_PREFIX));
      await AsyncStorage.multiRemove(cacheKeys);
      return true;
    } catch (error) {
      console.error('清除缓存失败:', error);
      return false;
    }
  }

  /**
   * 获取缓存大小（估算）
   */
  async getSize(): Promise<string> {
    try {
      const keys = await AsyncStorage.getAllKeys();
      const cacheKeys = keys.filter((key) => key.startsWith(CACHE_PREFIX));
      
      let totalSize = 0;
      for (const key of cacheKeys) {
        const value = await AsyncStorage.getItem(key);
        if (value) {
          totalSize += value.length;
        }
      }

      // 转换为可读格式
      if (totalSize < 1024) {
        return `${totalSize} B`;
      } else if (totalSize < 1024 * 1024) {
        return `${(totalSize / 1024).toFixed(2)} KB`;
      } else {
        return `${(totalSize / (1024 * 1024)).toFixed(2)} MB`;
      }
    } catch (error) {
      console.error('获取缓存大小失败:', error);
      return '0 B';
    }
  }

  /**
   * 缓存报告
   */
  async cacheReport(reportId: string, report: any): Promise<boolean> {
    return this.set(`report_${reportId}`, report, 24 * 60 * 60 * 1000); // 24小时
  }

  /**
   * 获取缓存的报告
   */
  async getCachedReport(reportId: string): Promise<any | null> {
    return this.get(`report_${reportId}`);
  }

  /**
   * 缓存今日报告
   */
  async cacheTodayReport(report: any): Promise<boolean> {
    const today = new Date().toISOString().split('T')[0];
    return this.set(`today_report_${today}`, report, 6 * 60 * 60 * 1000); // 6小时
  }

  /**
   * 获取缓存的今日报告
   */
  async getCachedTodayReport(): Promise<any | null> {
    const today = new Date().toISOString().split('T')[0];
    return this.get(`today_report_${today}`);
  }

  /**
   * 缓存股票行情
   */
  async cacheStockQuote(code: string, market: string, quote: any): Promise<boolean> {
    return this.set(`stock_${market}_${code}`, quote, 5 * 60 * 1000); // 5分钟
  }

  /**
   * 获取缓存的股票行情
   */
  async getCachedStockQuote(code: string, market: string): Promise<any | null> {
    return this.get(`stock_${market}_${code}`);
  }

  /**
   * 缓存自选股列表
   */
  async cacheWatchlist(watchlist: any[]): Promise<boolean> {
    return this.set('watchlist', watchlist, 60 * 60 * 1000); // 1小时
  }

  /**
   * 获取缓存的自选股列表
   */
  async getCachedWatchlist(): Promise<any[] | null> {
    return this.get('watchlist');
  }
}

// 导出单例实例
export const cacheService = new CacheService();

// 导出类（用于自定义实例）
export { CacheService };
