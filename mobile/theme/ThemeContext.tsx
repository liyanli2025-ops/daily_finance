import React, { createContext, useContext, useEffect, useState } from 'react';
import { useColorScheme } from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { LightColors, DarkColors, AppColors } from './colors';

const THEME_KEY = '@finance_daily_theme_mode';

type ThemeMode = 'light' | 'dark' | 'system';

interface ThemeContextType {
  colors: AppColors;
  isDark: boolean;
  themeMode: ThemeMode;
  setThemeMode: (mode: ThemeMode) => void;
}

const ThemeContext = createContext<ThemeContextType>({
  colors: DarkColors,
  isDark: true,
  themeMode: 'system',
  setThemeMode: () => {},
});

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const systemScheme = useColorScheme();
  const [themeMode, setThemeModeState] = useState<ThemeMode>('system');
  const [isReady, setIsReady] = useState(false);

  // 从本地存储加载主题偏好
  useEffect(() => {
    (async () => {
      try {
        const saved = await AsyncStorage.getItem(THEME_KEY);
        if (saved && (saved === 'light' || saved === 'dark' || saved === 'system')) {
          setThemeModeState(saved as ThemeMode);
        }
      } catch (e) {
        console.error('加载主题设置失败:', e);
      }
      setIsReady(true);
    })();
  }, []);

  const setThemeMode = async (mode: ThemeMode) => {
    setThemeModeState(mode);
    try {
      await AsyncStorage.setItem(THEME_KEY, mode);
    } catch (e) {
      console.error('保存主题设置失败:', e);
    }
  };

  const isDark =
    themeMode === 'system' ? systemScheme === 'dark' : themeMode === 'dark';
  const colors = isDark ? DarkColors : LightColors;

  if (!isReady) return null;

  return (
    <ThemeContext.Provider value={{ colors, isDark, themeMode, setThemeMode }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useAppTheme() {
  return useContext(ThemeContext);
}
