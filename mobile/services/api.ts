/**
 * API 服务层
 * 封装所有与后端的通信
 */

const BASE_URL = 'http://82.156.59.2/api';

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
    options: RequestInit = {},
    timeout: number = 15000
  ): Promise<T> {
    const url = `${this.baseUrl}${endpoint}`;
    
    const defaultHeaders = {
      'Content-Type': 'application/json',
    };

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), timeout);

    const config: RequestInit = {
      ...options,
      signal: controller.signal,
      headers: {
        ...defaultHeaders,
        ...options.headers,
      },
    };

    try {
      const response = await fetch(url, config);
      clearTimeout(timeoutId);
      
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      
      return await response.json();
    } catch (error: any) {
      clearTimeout(timeoutId);
      if (error.name === 'AbortError') {
        console.error(`API请求超时: ${endpoint}`);
        throw new Error('请求超时');
      }
      console.error(`API请求失败: ${endpoint}`, error);
      throw error;
    }
  }

  // ==================== 报告相关 ====================

  /**
   * 获取今日报告
   * @param reportType 报告类型：morning/evening，不指定则返回最新的
   */
  async getTodayReport(reportType?: 'morning' | 'evening') {
    const params = reportType ? `?report_type=${reportType}` : '';
    return this.request<any>(`/reports/today${params}`);
  }

  /**
   * 获取今日所有报告（早报+晚报）
   */
  async getTodayAllReports() {
    return this.request<{
      date: string;
      reports: any[];
      morning_report: string | null;
      evening_report: string | null;
    }>('/reports/today/all');
  }

  /**
   * 获取报告列表
   * @param reportType 报告类型：morning/evening，不指定则返回全部
   */
  async getReports(skip = 0, limit = 20, reportType?: 'morning' | 'evening') {
    let url = `/reports?skip=${skip}&limit=${limit}`;
    if (reportType) {
      url += `&report_type=${reportType}`;
    }
    return this.request<any[]>(url);
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
   * @param reportType 报告类型：morning/evening，不指定则返回最新的
   */
  async getTodayPodcast(reportType?: 'morning' | 'evening') {
    const params = reportType ? `?report_type=${reportType}` : '';
    return this.request<any>(`/podcasts/today${params}`);
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
   * @param reportType 报告类型：morning/evening，不指定则返回全部
   */
  async getPodcastHistory(skip = 0, limit = 20, reportType?: 'morning' | 'evening') {
    let url = `/podcasts/history?skip=${skip}&limit=${limit}`;
    if (reportType) {
      url += `&report_type=${reportType}`;
    }
    return this.request<any[]>(url);
  }

  // ==================== 股票相关 ====================

  /**
   * 获取主要市场指数实时行情
   */
  async getMarketIndices() {
    return this.request<{
      status: string;
      data: Array<{
        code: string;
        name: string;
        current: number;
        change: number;
        change_pct: number;
        volume: number;
        amount: number;
        high: number;
        low: number;
        open: number;
      }>;
      message?: string;
    }>('/stocks/market/indices', {}, 45000);
  }

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

  /**
   * 生成自选股 AI 预测
   * 这是一个耗时操作，会调用 AI 对每只股票进行分析
   */
  async generateWatchlistPredictions() {
    return this.request<{
      status: string;
      message: string;
      predicted: number;
      total: number;
      results: Array<{
        code: string;
        name: string;
        prediction?: string;
        confidence?: number;
        reasoning?: string;
        error?: string;
      }>;
    }>('/stocks/watchlist/predict', {
      method: 'POST',
    }, 120000);  // 2分钟超时，因为 AI 分析比较慢
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

}

// 导出单例实例
export const api = new ApiService();

// 导出类（用于自定义实例）
export { ApiService };
