import { Tabs } from 'expo-router';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import { StyleSheet, Platform, View } from 'react-native';
import { useAppTheme } from '@/theme/ThemeContext';

export default function TabLayout() {
  const { colors, isDark } = useAppTheme();

  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: colors.tabBarActive,
        tabBarInactiveTintColor: colors.tabBarInactive,
        tabBarStyle: {
          position: 'absolute',
          backgroundColor: colors.tabBarBackground,
          borderTopColor: colors.tabBarBorder,
          borderTopWidth: StyleSheet.hairlineWidth,
          height: Platform.OS === 'ios' ? 88 : 64,
          paddingBottom: Platform.OS === 'ios' ? 28 : 8,
          paddingTop: 8,
          elevation: 0,
        },
        tabBarLabelStyle: {
          fontSize: 9,
          fontWeight: '700',
          letterSpacing: 1.2,
          textTransform: 'uppercase',
        },
      }}
    >
      <Tabs.Screen
        name="index"
        options={{
          title: '首页',
          tabBarLabel: '首页',
          tabBarIcon: ({ color, size }) => (
            <MaterialCommunityIcons name="newspaper-variant-outline" size={22} color={color} />
          ),
        }}
      />
      <Tabs.Screen
        name="podcast"
        options={{
          title: '播客',
          tabBarLabel: '播客',
          tabBarIcon: ({ color, size }) => (
            <MaterialCommunityIcons name="play-circle-outline" size={22} color={color} />
          ),
        }}
      />
      <Tabs.Screen
        name="stocks"
        options={{
          title: '股票',
          tabBarLabel: '股票',
          tabBarIcon: ({ color, size }) => (
            <MaterialCommunityIcons name="chart-line" size={22} color={color} />
          ),
        }}
      />
      <Tabs.Screen
        name="settings"
        options={{
          title: '设置',
          tabBarLabel: '设置',
          tabBarIcon: ({ color, size }) => (
            <MaterialCommunityIcons name="cog-outline" size={22} color={color} />
          ),
        }}
      />
      {/* 报告详情页 - 隐藏在 tab 栏中但保留底部导航 */}
      <Tabs.Screen
        name="report"
        options={{
          href: null, // 不显示在底部 tab 栏
        }}
      />
    </Tabs>
  );
}
