import { create } from 'zustand';
import { api } from '@/services/api';

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

interface Report {
  id: string;
  title: string;
  summary: string;
  content: string;
  report_date: string;
  highlights: NewsHighlight[];
  analysis?: MarketAnalysis;
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
  podcast_status: string;
  podcast_duration?: number;
  created_at: string;
}

interface ReportStore {
  todayReport: Report | null;
  currentReport: Report | null;
  recentReports: ReportListItem[];
  isLoading: boolean;
  error: string | null;

  fetchTodayReport: () => Promise<void>;
  fetchReport: (id: string) => Promise<void>;
  fetchRecentReports: () => Promise<void>;
}

export const useReportStore = create<ReportStore>((set, get) => ({
  todayReport: null,
  currentReport: null,
  recentReports: [],
  isLoading: false,
  error: null,

  fetchTodayReport: async () => {
    set({ isLoading: true, error: null });
    try {
      const report = await api.getTodayReport();
      set({ todayReport: report, isLoading: false });
    } catch (error) {
      console.error('获取今日报告失败:', error);
      set({ error: '获取今日报告失败', isLoading: false });
      
      // 使用模拟数据
      set({
        todayReport: {
          id: 'mock-1',
          title: '2026年3月12日 财经深度日报',
          summary: '今日市场震荡整理，央行货币政策维持稳定，新能源板块表现活跃。建议关注政策动向和行业轮动机会。',
          content: '# 今日市场概览\n\n今日A股市场震荡整理...',
          report_date: new Date().toISOString().split('T')[0],
          highlights: [
            {
              title: '央行维持稳健货币政策不变',
              source: '财联社',
              summary: '央行表示将继续实施稳健的货币政策，保持流动性合理充裕。',
              sentiment: 'neutral',
              related_stocks: [],
            },
            {
              title: '新能源汽车销量创历史新高',
              source: '华尔街见闻',
              summary: '2月新能源汽车销量同比增长45%，渗透率突破35%。',
              sentiment: 'positive',
              related_stocks: ['002594', '01211'],
            },
          ],
          analysis: {
            overall_sentiment: 'neutral',
            trend: 'neutral',
            key_factors: ['央行政策', '外围市场'],
            opportunities: ['新能源', '科技'],
            risks: ['估值压力', '外部风险'],
          },
          podcast_status: 'ready',
          podcast_duration: 1500,
          word_count: 5000,
          reading_time: 12,
          news_count: 25,
          created_at: new Date().toISOString(),
        },
        isLoading: false,
      });
    }
  },

  fetchReport: async (id: string) => {
    set({ isLoading: true, error: null });
    try {
      const report = await api.getReport(id);
      set({ currentReport: report, isLoading: false });
    } catch (error) {
      console.error('获取报告详情失败:', error);
      set({ error: '获取报告详情失败', isLoading: false });
    }
  },

  fetchRecentReports: async () => {
    try {
      const reports = await api.getReports();
      set({ recentReports: reports });
    } catch (error) {
      console.error('获取报告列表失败:', error);
      // 使用模拟数据
      set({
        recentReports: [
          {
            id: 'mock-2',
            title: '2026年3月11日 财经深度日报',
            summary: '市场情绪回暖，科技板块领涨...',
            report_date: '2026-03-11',
            podcast_status: 'ready',
            podcast_duration: 1400,
            created_at: '2026-03-11T06:00:00Z',
          },
          {
            id: 'mock-3',
            title: '2026年3月10日 财经深度日报',
            summary: '外围市场波动加剧，避险情绪升温...',
            report_date: '2026-03-10',
            podcast_status: 'ready',
            podcast_duration: 1600,
            created_at: '2026-03-10T06:00:00Z',
          },
        ],
      });
    }
  },
}));
