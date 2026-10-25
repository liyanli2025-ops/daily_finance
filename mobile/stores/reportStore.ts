import { create } from 'zustand';
import { api } from '@/services/api';
import { cacheService } from '@/services/cache';

const chinaDate = () => new Date(Date.now() + 8 * 60 * 60 * 1000).toISOString().slice(0, 10);
const isRealReport = (report: any): boolean => Boolean(report && typeof report.id === 'string' && !report.id.startsWith('mock-') && report.content);

interface NewsHighlight {
  title: string;
  source: string;
  summary: string;
  sentiment: 'positive' | 'negative' | 'neutral';
  related_stocks: string[];
  historical_context?: string;
}

interface MarketAnalysis {
  overall_sentiment: string;
  trend: string;
  key_factors: string[];
  opportunities: string[];
  risks: string[];
}

// 跨界热点事件
interface CrossBorderEvent {
  title: string;
  category: 'geopolitical' | 'tech' | 'social' | 'disaster';
  summary: string;
  market_impact?: {
    direct: string;
    indirect: string;
  };
  historical_reference?: string;
  beneficiaries?: string[];
  losers?: string[];
  follow_up_advice?: string;
}

// 报告类型枚举
type ReportType = 'morning' | 'evening';

interface Report {
  id: string;
  title: string;
  summary: string;
  content: string;
  report_date: string;
  report_type: ReportType;            // 报告类型：早报/晚报
  highlights: NewsHighlight[];
  analysis?: MarketAnalysis;
  // 新增字段
  core_opinions?: string[];           // 今日核心观点（3条）
  cross_border_events?: CrossBorderEvent[];  // 跨界热点事件
  cross_border_count?: number;        // 跨界热点数量
  podcast_url?: string;
  podcast_duration?: number;
  podcast_status: string;
  word_count: number;
  reading_time: number;
  news_count: number;
  created_at: string;
}

interface ReportListItem {
  id: string;
  title: string;
  summary: string;
  report_date: string;
  report_type: ReportType;            // 报告类型：早报/晚报
  podcast_status: string;
  podcast_url?: string;
  podcast_duration?: number;
  created_at: string;
}

// 今日报告汇总
interface TodayReportsResponse {
  date: string;
  reports: ReportListItem[];
  morning_report: string | null;
  evening_report: string | null;
}

interface ReportStore {
  todayReport: Report | null;
  currentReport: Report | null;
  recentReports: ReportListItem[];
  todayAllReports: TodayReportsResponse | null;  // 今日所有报告（早报+晚报）
  isLoading: boolean;
  error: string | null;

  fetchTodayReport: (reportType?: ReportType) => Promise<void>;
  fetchReport: (id: string) => Promise<void>;
  fetchRecentReports: (reportType?: ReportType) => Promise<void>;
  fetchTodayAllReports: () => Promise<void>;     // 获取今日所有报告
}

export const useReportStore = create<ReportStore>((set, get) => ({
  todayReport: null,
  currentReport: null,
  recentReports: [],
  todayAllReports: null,
  isLoading: false,
  error: null,

  fetchTodayReport: async (reportType?: ReportType) => {
    set({ isLoading: true, error: null });
    
    // 先尝试从缓存获取
    const cached = await cacheService.getCachedTodayReport();
    if (isRealReport(cached) && cached.report_date === chinaDate() && (!reportType || cached.report_type === reportType)) {
      set({ todayReport: cached, isLoading: false });
      // 后台刷新
      api.getTodayReport(reportType).then((report) => {
        if (!isRealReport(report) || report.report_date !== chinaDate()) throw new Error('今日报告尚未就绪');
        set({ todayReport: report, error: null });
        cacheService.cacheTodayReport(report);
      }).catch(() => set({ error: '刷新失败，显示的是本地缓存报告' }));
      return;
    }
    
    try {
      const report = await api.getTodayReport(reportType);
      if (!isRealReport(report) || report.report_date !== chinaDate()) throw new Error('今日报告尚未就绪');
      set({ todayReport: report, isLoading: false });
      // 缓存报告
      cacheService.cacheTodayReport(report);
    } catch (error) {
      console.error('获取今日报告失败:', error);
      set({ error: '获取今日报告失败', isLoading: false });
      
      set({ todayReport: null });
    }
  },

  fetchReport: async (id: string) => {
    set({ isLoading: true, error: null });
    
    // 先尝试从缓存获取
    const cached = await cacheService.getCachedReport(id);
    if (isRealReport(cached)) {
      set({ currentReport: cached, isLoading: false });
      return;
    }
    
    try {
      const report = await api.getReport(id);
      if (!isRealReport(report)) throw new Error('报告不可用');
      set({ currentReport: report, isLoading: false });
      // 缓存报告
      cacheService.cacheReport(id, report);
    } catch (error) {
      console.error('获取报告详情失败:', error);
      set({ currentReport: null, error: '获取报告详情失败', isLoading: false });
    }
  },

  fetchRecentReports: async (reportType?: ReportType) => {
    try {
      const reports = await api.getReports(0, 20, reportType);
      set({ recentReports: reports.filter(r => !r.id.startsWith('mock-')) });
    } catch (error) {
      console.error('获取报告列表失败:', error);
      set({ error: '获取报告列表失败，请重试' });
    }
  },

  fetchTodayAllReports: async () => {
    try {
      const response = await api.getTodayAllReports();
      set({ todayAllReports: response });
    } catch (error) {
      console.error('获取今日所有报告失败:', error);
    }
  },
}));
