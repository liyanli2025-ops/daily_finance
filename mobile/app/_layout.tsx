import { useEffect } from 'react';
import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { PaperProvider, MD3DarkTheme } from 'react-native-paper';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import * as SplashScreen from 'expo-splash-screen';

// 防止启动画面自动隐藏
SplashScreen.preventAutoHideAsync();

// 自定义深色主题
const theme = {
  ...MD3DarkTheme,
  colors: {
    ...MD3DarkTheme.colors,
    primary: '#6C63FF',
    primaryContainer: '#3D3A80',
    secondary: '#03DAC6',
    secondaryContainer: '#005048',
    surface: '#1a1a2e',
    surfaceVariant: '#252542',
    background: '#0f0f1a',
    error: '#CF6679',
    onPrimary: '#FFFFFF',
    onSecondary: '#000000',
    onSurface: '#FFFFFF',
    onBackground: '#FFFFFF',
    outline: '#3D3D5C',
    elevation: {
      level0: 'transparent',
      level1: '#1a1a2e',
      level2: '#252542',
      level3: '#2f2f52',
      level4: '#393962',
      level5: '#434372',
    },
  },
  roundness: 12,
};

export default function RootLayout() {
  useEffect(() => {
    // 应用准备好后隐藏启动画面
    const prepare = async () => {
      await SplashScreen.hideAsync();
    };
    prepare();
  }, []);

  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
      <PaperProvider theme={theme}>
        <StatusBar style="light" />
        <Stack
          screenOptions={{
            headerStyle: {
              backgroundColor: theme.colors.surface,
            },
            headerTintColor: theme.colors.onSurface,
            headerTitleStyle: {
              fontWeight: '600',
            },
            contentStyle: {
              backgroundColor: theme.colors.background,
            },
          }}
        >
          <Stack.Screen
            name="(tabs)"
            options={{
              headerShown: false,
            }}
          />
          <Stack.Screen
            name="report/[id]"
            options={{
              title: '报告详情',
              presentation: 'card',
            }}
          />
          <Stack.Screen
            name="stock/[code]"
            options={{
              title: '股票详情',
              presentation: 'card',
            }}
          />
        </Stack>
      </PaperProvider>
    </GestureHandlerRootView>
  );
}
