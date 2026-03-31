import { Tabs, useSegments } from 'expo-router';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import { StyleSheet, Platform, View } from 'react-native';
import { useAppTheme } from '@/theme/ThemeContext';
import { useAudioStore } from '@/stores/audioStore';
import MiniPlayer from '@/components/MiniPlayer';

export default function TabLayout() {
  const { colors, isDark } = useAppTheme();
  const segments = useSegments();
  const { currentReportId } = useAudioStore();
  
  // 判断当前是否在播客页面
  const isPodcastTab = segments.includes('podcast');
  
  // 是否显示迷你播放器：有播放内容且不在播客页面
  const showMiniPlayer = currentReportId && !isPodcastTab;
  
  // 迷你播放器的高度
  const miniPlayerHeight = showMiniPlayer ? 60 : 0;

  return (
    <View style={{ flex: 1 }}>
      <Tabs
        screenOptions={{
          headerShown: false,
          tabBarActiveTintColor: colors.tabBarActive,
          tabBarInactiveTintColor: colors.tabBarInactive,
          tabBarStyle: {
            position: 'absolute',
            backgroundColor: colors.tabBarBackground,
            borderTopColor: showMiniPlayer ? 'transparent' : colors.tabBarBorder,
            borderTopWidth: showMiniPlayer ? 0 : StyleSheet.hairlineWidth,
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
          // 当显示迷你播放器时，为内容区域添加额外的底部边距
          sceneContainerStyle: showMiniPlayer ? {
            paddingBottom: miniPlayerHeight,
          } : undefined,
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
      
      {/* 迷你播放器 - 显示在 Tab Bar 上方 */}
      {showMiniPlayer && (
        <View style={[
          styles.miniPlayerContainer,
          { 
            bottom: Platform.OS === 'ios' ? 88 : 64,
          }
        ]}>
          <MiniPlayer />
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  miniPlayerContainer: {
    position: 'absolute',
    left: 0,
    right: 0,
    zIndex: 100,
  },
});
