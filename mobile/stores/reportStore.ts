import { create } from 'zustand';
import { api } from '@/services/api';
import { cacheService } from '@/services/cache';

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
    if (cached && (!reportType || cached.report_type === reportType)) {
      set({ todayReport: cached, isLoading: false });
      // 后台刷新
      api.getTodayReport(reportType).then((report) => {
        set({ todayReport: report });
        cacheService.cacheTodayReport(report);
      }).catch(() => {});
      return;
    }
    
    try {
      const report = await api.getTodayReport(reportType);
      set({ todayReport: report, isLoading: false });
      // 缓存报告
      cacheService.cacheTodayReport(report);
    } catch (error) {
      console.error('获取今日报告失败:', error);
      set({ error: '获取今日报告失败', isLoading: false });
      
      // 使用模拟数据
      set({
        todayReport: {
          id: 'mock-1',
          title: '2026年3月31日 财经深度日报',
          summary: '今日市场震荡整理，央行货币政策维持稳定，新能源板块表现活跃。建议关注政策动向和行业轮动机会。',
          content: '# 今日市场概览\n\n今日A股市场震荡整理...',
          report_date: new Date().toISOString().split('T')[0],
          report_type: 'morning',
          core_opinions: [
            '央行定向降准释放流动性，看好银行股短期修复行情，建议配置招商银行、宁波银行',
            '新能源汽车渗透率突破35%，宁德时代、比亚迪业绩确定性强，维持"买入"评级',
            '中东局势升级推高油价，利好中国石油、中国石化，同时警惕输入性通胀风险',
          ],
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
          cross_border_events: [
            {
              title: '中东地区紧张局势升级',
              category: 'geopolitical',
              summary: '伊朗与以色列冲突加剧，红海航运受影响，国际油价应声上涨3%。',
              market_impact: {
                direct: '能源板块直接受益，中国石油、中国石化预计短期上涨5-8%',
                indirect: '航运成本上升可能推高整体物价，警惕输入性通胀',
              },
              historical_reference: '2022年俄乌冲突期间，油价曾突破120美元/桶，能源股涨幅超30%',
              beneficiaries: ['中国石油', '中国石化', '中国海油'],
              losers: ['航空股', '物流运输'],
              follow_up_advice: '持续关注局势发展，设定10%止盈位',
            },
            {
              title: 'OpenAI发布GPT-5，AI算力需求暴增',
              category: 'tech',
              summary: 'GPT-5性能提升10倍，推理成本下降50%，全球科技巨头加速AI布局。',
              market_impact: {
                direct: 'AI算力芯片需求激增，英伟达概念股直接受益',
                indirect: '传统软件公司面临转型压力，人力替代加速',
              },
              beneficiaries: ['中际旭创', '浪潮信息', '紫光股份'],
              losers: ['传统软件外包公司'],
            },
          ],
          cross_border_count: 2,
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
    
    // 先尝试从缓存获取
    const cached = await cacheService.getCachedReport(id);
    if (cached) {
      set({ currentReport: cached, isLoading: false });
      return;
    }
    
    try {
      const report = await api.getReport(id);
      set({ currentReport: report, isLoading: false });
      // 缓存报告
      cacheService.cacheReport(id, report);
    } catch (error) {
      console.error('获取报告详情失败:', error);
      set({ error: '获取报告详情失败', isLoading: false });
    }
  },

  fetchRecentReports: async (reportType?: ReportType) => {
    try {
      const reports = await api.getReports(0, 20, reportType);
      set({ recentReports: reports });
    } catch (error) {
      console.error('获取报告列表失败:', error);
      // 使用模拟数据
      set({
        recentReports: [
          {
            id: 'mock-2',
            title: '2026年3月30日 财经早报',
            summary: '市场情绪回暖，科技板块领涨...',
            report_date: '2026-03-30',
            report_type: 'morning',
            podcast_status: 'ready',
            podcast_duration: 1400,
            created_at: '2026-03-30T07:00:00Z',
          },
          {
            id: 'mock-3',
            title: '2026年3月30日 财经晚报',
            summary: '今日复盘：科技股强势领涨，指数震荡上行...',
            report_date: '2026-03-30',
            report_type: 'evening',
            podcast_status: 'ready',
            podcast_duration: 1800,
            created_at: '2026-03-30T17:00:00Z',
          },
          {
            id: 'mock-4',
            title: '2026年3月29日 财经早报',
            summary: '外围市场波动加剧，避险情绪升温...',
            report_date: '2026-03-29',
            report_type: 'morning',
            podcast_status: 'ready',
            podcast_duration: 1600,
            created_at: '2026-03-29T07:00:00Z',
          },
        ],
      });
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
