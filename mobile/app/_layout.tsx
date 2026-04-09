import { useEffect } from 'react';
import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { PaperProvider, MD3DarkTheme, MD3LightTheme } from 'react-native-paper';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import * as SplashScreen from 'expo-splash-screen';
import { ThemeProvider, useAppTheme } from '@/theme/ThemeContext';

// 防止启动画面自动隐藏
SplashScreen.preventAutoHideAsync();

function RootNavigator() {
  const { colors, isDark } = useAppTheme();

  useEffect(() => {
    const prepare = async () => {
      await SplashScreen.hideAsync();
    };
    prepare();
  }, []);

  // 为旧的 react-native-paper 页面（stocks, report/[id], stock/[code]）提供兼容主题
  const paperTheme = isDark
    ? {
        ...MD3DarkTheme,
        colors: {
          ...MD3DarkTheme.colors,
          primary: colors.primary,
          primaryContainer: colors.primaryContainer,
          secondary: colors.secondary,
          surface: colors.surfaceContainer,
          surfaceVariant: colors.surfaceContainerHigh,
          background: colors.background,
          onPrimary: colors.onPrimary,
          onSurface: colors.onSurface,
          onBackground: colors.onBackground,
          outline: colors.outline,
          error: colors.error,
          elevation: {
            level0: 'transparent',
            level1: colors.surfaceContainerLow,
            level2: colors.surfaceContainer,
            level3: colors.surfaceContainerHigh,
            level4: colors.surfaceContainerHighest,
            level5: colors.surfaceContainerHighest,
          },
        },
        roundness: 12,
      }
    : {
        ...MD3LightTheme,
        colors: {
          ...MD3LightTheme.colors,
          primary: colors.primary,
          primaryContainer: colors.primaryContainer,
          secondary: colors.secondary,
          surface: colors.surfaceContainerLowest,
          surfaceVariant: colors.surfaceContainerLow,
          background: colors.background,
          onPrimary: colors.onPrimary,
          onSurface: colors.onSurface,
          onBackground: colors.onBackground,
          outline: colors.outline,
          error: colors.error,
          elevation: {
            level0: 'transparent',
            level1: colors.surfaceContainerLow,
            level2: colors.surfaceContainer,
            level3: colors.surfaceContainerHigh,
            level4: colors.surfaceContainerHighest,
            level5: colors.surfaceContainerHighest,
          },
        },
        roundness: 12,
      };

  return (
    <PaperProvider theme={paperTheme}>
      <StatusBar style={colors.statusBarStyle} />
      <Stack
        screenOptions={{
          headerShown: false,
          contentStyle: {
            backgroundColor: colors.background,
          },
          animation: 'slide_from_right',
        }}
      >
        <Stack.Screen name="(tabs)" />
        <Stack.Screen
          name="stock/[code]"
          options={{
            title: '股票详情',
            presentation: 'card',
          }}
        />
      </Stack>
    </PaperProvider>
  );
}

export default function RootLayout() {
  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
      <ThemeProvider>
        <RootNavigator />
      </ThemeProvider>
    </GestureHandlerRootView>
  );
}
