/**
 * API 服务层
 * 封装所有与后端的通信
 */

const BASE_URL = 'http://localhost:9090/api';

class ApiService {
  private baseUrl: string;

  constructor(baseUrl: string = BASE_URL) {
    this.baseUrl = baseUrl;
  }

  setBaseUrl(url: string) {
    this.baseUrl = url;
  }

  private async request<T>(
    endpoint: string,
    options: RequestInit = {}
  ): Promise<T> {
    const url = `${this.baseUrl}${endpoint}`;
    
    const defaultHeaders = {
      'Content-Type': 'application/json',
    };

    const config: RequestInit = {
      ...options,
      headers: {
        ...defaultHeaders,
        ...options.headers,
      },
    };

    try {
      const response = await fetch(url, config);
      
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      
      return await response.json();
    } catch (error) {
      console.error(`API请求失败: ${endpoint}`, error);
      throw error;
    }
  }

  // ==================== 报告相关 ====================

  /**
   * 获取今日报告
   */
  async getTodayReport() {
    return this.request<any>('/reports/today');
  }

  /**
   * 获取报告列表
   */
  async getReports(skip = 0, limit = 20) {
    return this.request<any[]>(`/reports?skip=${skip}&limit=${limit}`);
  }

  /**
   * 根据ID获取报告
   */
  async getReport(id: string) {
    return this.request<any>(`/reports/${id}`);
  }

  /**
   * 根据日期获取报告
   */
  async getReportByDate(date: string) {
    return this.request<any>(`/reports/date/${date}`);
  }

  // ==================== 播客相关 ====================

  /**
   * 获取今日播客信息
   */
  async getTodayPodcast() {
    return this.request<any>('/podcasts/today');
  }

  /**
   * 获取播客状态
   */
  async getPodcastStatus(reportId: string) {
    return this.request<any>(`/podcasts/${reportId}/status`);
  }

  /**
   * 重新生成播客
   */
  async regeneratePodcast(reportId: string) {
    return this.request<any>(`/podcasts/${reportId}/regenerate`, {
      method: 'POST',
    });
  }

  /**
   * 获取播客历史列表
   */
  async getPodcastHistory(skip = 0, limit = 20) {
    return this.request<any[]>(`/podcasts/history?skip=${skip}&limit=${limit}`);
  }

  // ==================== 股票相关 ====================

  /**
   * 获取自选股列表
   */
  async getWatchlist() {
    return this.request<any[]>('/stocks/watchlist');
  }

  /**
   * 添加自选股
   */
  async addToWatchlist(stock: { code: string; name: string; market: string }) {
    return this.request<any>('/stocks/watchlist', {
      method: 'POST',
      body: JSON.stringify(stock),
    });
  }

  /**
   * 移除自选股
   */
  async removeFromWatchlist(stockId: string) {
    return this.request<any>(`/stocks/watchlist/${stockId}`, {
      method: 'DELETE',
    });
  }

  /**
   * 搜索股票
   */
  async searchStocks(keyword: string, market?: string) {
    const params = new URLSearchParams({ keyword });
    if (market) params.append('market', market);
    return this.request<any[]>(`/stocks/search?${params}`);
  }

  /**
   * 获取股票实时行情
   */
  async getStockQuote(code: string, market: string) {
    return this.request<any>(`/stocks/${code}/quote?market=${market}`);
  }

  /**
   * 获取K线数据
   */
  async getStockKline(code: string, market: string, period = 'daily', limit = 60) {
    return this.request<any[]>(
      `/stocks/${code}/kline?market=${market}&period=${period}&limit=${limit}`
    );
  }

  /**
   * 获取股票预测
   */
  async getStockPrediction(code: string, market: string) {
    return this.request<any>(`/stocks/${code}/prediction?market=${market}`);
  }

  /**
   * 触发股票分析
   */
  async triggerStockAnalysis(code: string, market: string) {
    return this.request<any>(`/stocks/${code}/analyze?market=${market}`, {
      method: 'POST',
    });
  }

  /**
   * 刷新自选股数据
   */
  async refreshWatchlist() {
    return this.request<any>('/stocks/watchlist/refresh', {
      method: 'POST',
    });
  }

  // ==================== 系统相关 ====================

  /**
   * 健康检查
   */
  async healthCheck() {
    return this.request<any>('/health');
  }

  /**
   * 获取系统设置
   */
  async getSettings() {
    return this.request<any>('/settings');
  }

  /**
   * 手动触发报告生成
   */
  async triggerReportGeneration() {
    return this.request<any>('/trigger-report', {
      method: 'POST',
    });
  }

  // ==================== 公众号订阅 ====================

  /**
   * 获取公众号列表
   */
  async getWechatAccounts() {
    return this.request<any[]>('/wechat/accounts');
  }

  /**
   * 添加公众号
   */
  async addWechatAccount(data: {
    name: string;
    biz: string;
    description?: string;
    category?: string;
  }) {
    return this.request<any>('/wechat/accounts', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  /**
   * 删除公众号
   */
  async deleteWechatAccount(accountId: string) {
    return this.request<any>(`/wechat/accounts/${accountId}`, {
      method: 'DELETE',
    });
  }

  /**
   * 切换公众号启用/禁用
   */
  async toggleWechatAccount(accountId: string) {
    return this.request<any>(`/wechat/accounts/${accountId}/toggle`, {
      method: 'POST',
    });
  }

  /**
   * 从链接提取 biz
   */
  async extractWechatBiz(url: string) {
    return this.request<any>(`/wechat/extract-biz?url=${encodeURIComponent(url)}`, {
      method: 'POST',
    });
  }

  /**
   * 测试采集公众号
   */
  async testWechatFetch(accountId: string) {
    return this.request<any>(`/wechat/test-fetch/${accountId}`, {
      method: 'POST',
    });
  }

  /**
   * 获取预置公众号列表
   */
  async getWechatPresets() {
    return this.request<any[]>('/wechat/presets');
  }
}

// 导出单例实例
export const api = new ApiService();

// 导出类（用于自定义实例）
export { ApiService };
