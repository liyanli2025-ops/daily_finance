import { create } from 'zustand';
import AsyncStorage from '@react-native-async-storage/async-storage';

const SETTINGS_KEY = '@finance_daily_settings';

interface SettingsStore {
  notificationEnabled: boolean;
  reportHour: number;
  reportMinute: number;
  defaultPlaybackRate: number;
  autoDownload: boolean;
  followMarkets: string[];
  apiUrl: string;
  
  isLoading: boolean;

  loadSettings: () => Promise<void>;
  setNotificationEnabled: (enabled: boolean) => void;
  setReportTime: (hour: number, minute: number) => void;
  setDefaultPlaybackRate: (rate: number) => void;
  setAutoDownload: (enabled: boolean) => void;
  setFollowMarkets: (markets: string[]) => void;
  setApiUrl: (url: string) => void;
}

export const useSettingsStore = create<SettingsStore>((set, get) => ({
  notificationEnabled: true,
  reportHour: 6,
  reportMinute: 0,
  defaultPlaybackRate: 1,
  autoDownload: true,
  followMarkets: ['A', 'HK'],
  apiUrl: 'http://82.156.59.2:8000',
  isLoading: false,

  loadSettings: async () => {
    set({ isLoading: true });
    try {
      const saved = await AsyncStorage.getItem(SETTINGS_KEY);
      if (saved) {
        const settings = JSON.parse(saved);
        set({ ...settings, isLoading: false });
      } else {
        set({ isLoading: false });
      }
    } catch (error) {
      console.error('加载设置失败:', error);
      set({ isLoading: false });
    }
  },

  setNotificationEnabled: (enabled: boolean) => {
    set({ notificationEnabled: enabled });
    saveSettings(get());
  },

  setReportTime: (hour: number, minute: number) => {
    set({ reportHour: hour, reportMinute: minute });
    saveSettings(get());
  },

  setDefaultPlaybackRate: (rate: number) => {
    set({ defaultPlaybackRate: rate });
    saveSettings(get());
  },

  setAutoDownload: (enabled: boolean) => {
    set({ autoDownload: enabled });
    saveSettings(get());
  },

  setFollowMarkets: (markets: string[]) => {
    set({ followMarkets: markets });
    saveSettings(get());
  },

  setApiUrl: (url: string) => {
    set({ apiUrl: url });
    saveSettings(get());
  },
}));

// 保存设置到本地存储
async function saveSettings(state: Partial<SettingsStore>) {
  try {
    const toSave = {
      notificationEnabled: state.notificationEnabled,
      reportHour: state.reportHour,
      reportMinute: state.reportMinute,
      defaultPlaybackRate: state.defaultPlaybackRate,
      autoDownload: state.autoDownload,
      followMarkets: state.followMarkets,
      apiUrl: state.apiUrl,
    };
    await AsyncStorage.setItem(SETTINGS_KEY, JSON.stringify(toSave));
  } catch (error) {
    console.error('保存设置失败:', error);
  }
}
