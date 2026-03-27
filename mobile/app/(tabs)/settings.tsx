import React, { useState } from 'react';
import {
  View,
  ScrollView,
  StyleSheet,
  Alert,
  Text,
  TouchableOpacity,
  Switch,
  Platform,
  Dimensions,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import { useSettingsStore } from '@/stores/settingsStore';
import { useAppTheme } from '@/theme/ThemeContext';

const { width: SCREEN_WIDTH } = Dimensions.get('window');

export default function SettingsScreen() {
  const { colors, isDark, themeMode, setThemeMode } = useAppTheme();
  const {
    notificationEnabled,
    reportHour,
    reportMinute,
    defaultPlaybackRate,
    autoDownload,
    followMarkets,
    setNotificationEnabled,
    setDefaultPlaybackRate,
    setAutoDownload,
    setFollowMarkets,
  } = useSettingsStore();

  const formatTime = (hour: number, minute: number) => {
    return `${hour.toString().padStart(2, '0')}:${minute.toString().padStart(2, '0')}`;
  };

  const playbackRates = [0.75, 1, 1.25, 1.5, 2];
  const cyclePlaybackRate = () => {
    const idx = playbackRates.indexOf(defaultPlaybackRate);
    const next = (idx + 1) % playbackRates.length;
    setDefaultPlaybackRate(playbackRates[next]);
  };

  const styles = createStyles(colors, isDark);

  return (
    <View style={styles.container}>
      {/* 氛围背景 */}
      <View style={styles.atmosphereContainer}>
        <View style={[styles.blob, styles.blobPrimary]} />
      </View>

      <SafeAreaView edges={['top']} style={styles.headerSafe}>
        <View style={styles.header}>
          <Text style={[styles.headerTitle, { color: colors.onSurface }]}>设置</Text>
        </View>
      </SafeAreaView>

      <ScrollView style={styles.scrollView} contentContainerStyle={styles.scrollContent} showsVerticalScrollIndicator={false}>

        {/* === 外观 === */}
        <Text style={[styles.sectionLabel, { color: colors.primary }]}>外观</Text>
        <View style={[styles.card, { backgroundColor: isDark ? colors.glassBackground : colors.glassBackground, borderColor: isDark ? colors.glassBorder : colors.glassBorder }]}>
          {/* 主题切换 */}
          <Text style={[styles.itemTitle, { color: colors.onSurface }]}>主题模式</Text>
          <View style={styles.themeRow}>
            {([
              { key: 'light', label: '浅色', icon: 'white-balance-sunny' },
              { key: 'dark', label: '深色', icon: 'moon-waning-crescent' },
              { key: 'system', label: '跟随系统', icon: 'cellphone' },
            ] as const).map((item) => (
              <TouchableOpacity
                key={item.key}
                style={[
                  styles.themeOption,
                  {
                    backgroundColor: themeMode === item.key
                      ? (isDark ? 'rgba(182,160,255,0.15)' : 'rgba(124,77,255,0.1)')
                      : (isDark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.03)'),
                    borderColor: themeMode === item.key ? colors.primary : 'transparent',
                  },
                ]}
                onPress={() => setThemeMode(item.key)}
              >
                <MaterialCommunityIcons
                  name={item.icon as any}
                  size={20}
                  color={themeMode === item.key ? colors.primary : colors.onSurfaceVariant}
                />
                <Text style={[
                  styles.themeOptionText,
                  { color: themeMode === item.key ? colors.primary : colors.onSurfaceVariant },
                ]}>
                  {item.label}
                </Text>
              </TouchableOpacity>
            ))}
          </View>
        </View>

        {/* === 推送设置 === */}
        <Text style={[styles.sectionLabel, { color: colors.primary }]}>推送设置</Text>
        <View style={[styles.card, { backgroundColor: isDark ? colors.glassBackground : colors.glassBackground, borderColor: isDark ? colors.glassBorder : colors.glassBorder }]}>
          <SettingRow
            colors={colors}
            isDark={isDark}
            icon="bell-outline"
            title="推送通知"
            subtitle="报告生成后通知"
            right={
              <Switch
                value={notificationEnabled}
                onValueChange={setNotificationEnabled}
                trackColor={{ false: isDark ? '#333' : '#ddd', true: `${colors.primary}80` }}
                thumbColor={notificationEnabled ? colors.primary : (isDark ? '#666' : '#ccc')}
              />
            }
          />
          <View style={[styles.separator, { backgroundColor: isDark ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.05)' }]} />
          <SettingRow
            colors={colors}
            isDark={isDark}
            icon="clock-outline"
            title="推送时间"
            subtitle={`每天 ${formatTime(reportHour, reportMinute)}`}
            right={<MaterialCommunityIcons name="chevron-right" size={20} color={colors.onSurfaceVariant} />}
          />
        </View>

        {/* === 内容偏好 === */}
        <Text style={[styles.sectionLabel, { color: colors.primary }]}>内容偏好</Text>
        <View style={[styles.card, { backgroundColor: isDark ? colors.glassBackground : colors.glassBackground, borderColor: isDark ? colors.glassBorder : colors.glassBorder }]}>
          <SettingRow
            colors={colors}
            isDark={isDark}
            icon="alpha-a-box"
            title="A股市场"
            subtitle="接收A股新闻和分析"
            right={
              <Switch
                value={followMarkets.includes('A')}
                onValueChange={(value) => {
                  const markets = value ? [...followMarkets, 'A'] : followMarkets.filter((m) => m !== 'A');
                  setFollowMarkets(markets);
                }}
                trackColor={{ false: isDark ? '#333' : '#ddd', true: `${colors.primary}80` }}
                thumbColor={followMarkets.includes('A') ? colors.primary : (isDark ? '#666' : '#ccc')}
              />
            }
          />
          <View style={[styles.separator, { backgroundColor: isDark ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.05)' }]} />
          <SettingRow
            colors={colors}
            isDark={isDark}
            icon="alpha-h-box"
            title="港股市场"
            subtitle="接收港股新闻和分析"
            right={
              <Switch
                value={followMarkets.includes('HK')}
                onValueChange={(value) => {
                  const markets = value ? [...followMarkets, 'HK'] : followMarkets.filter((m) => m !== 'HK');
                  setFollowMarkets(markets);
                }}
                trackColor={{ false: isDark ? '#333' : '#ddd', true: `${colors.primary}80` }}
                thumbColor={followMarkets.includes('HK') ? colors.primary : (isDark ? '#666' : '#ccc')}
              />
            }
          />
        </View>

        {/* === 播客设置 === */}
        <Text style={[styles.sectionLabel, { color: colors.primary }]}>播客设置</Text>
        <View style={[styles.card, { backgroundColor: isDark ? colors.glassBackground : colors.glassBackground, borderColor: isDark ? colors.glassBorder : colors.glassBorder }]}>
          <TouchableOpacity onPress={cyclePlaybackRate}>
            <SettingRow
              colors={colors}
              isDark={isDark}
              icon="speedometer"
              title="默认倍速"
              subtitle={`${defaultPlaybackRate}x`}
              right={<MaterialCommunityIcons name="chevron-right" size={20} color={colors.onSurfaceVariant} />}
            />
          </TouchableOpacity>
          <View style={[styles.separator, { backgroundColor: isDark ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.05)' }]} />
          <SettingRow
            colors={colors}
            isDark={isDark}
            icon="download-outline"
            title="自动下载"
            subtitle="Wi-Fi下自动下载新播客"
            right={
              <Switch
                value={autoDownload}
                onValueChange={setAutoDownload}
                trackColor={{ false: isDark ? '#333' : '#ddd', true: `${colors.primary}80` }}
                thumbColor={autoDownload ? colors.primary : (isDark ? '#666' : '#ccc')}
              />
            }
          />
        </View>

        {/* === 关于 === */}
        <Text style={[styles.sectionLabel, { color: colors.primary }]}>关于</Text>
        <View style={[styles.card, { backgroundColor: isDark ? colors.glassBackground : colors.glassBackground, borderColor: isDark ? colors.glassBorder : colors.glassBorder }]}>
          <SettingRow
            colors={colors}
            isDark={isDark}
            icon="information-outline"
            title="版本"
            subtitle="1.0.0 (MVP)"
          />
          <View style={[styles.separator, { backgroundColor: isDark ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.05)' }]} />
          <TouchableOpacity onPress={() => Alert.alert('使用说明', '每天早上 7 点，系统自动生成财经日报和播客。在首页查看报告，播客页收听音频，自选股页追踪个股。')}>
            <SettingRow
              colors={colors}
              isDark={isDark}
              icon="help-circle-outline"
              title="使用说明"
              subtitle="了解如何使用"
              right={<MaterialCommunityIcons name="chevron-right" size={20} color={colors.onSurfaceVariant} />}
            />
          </TouchableOpacity>
        </View>

        <View style={{ height: 120 }} />
      </ScrollView>
    </View>
  );
}

// 设置行组件
function SettingRow({ colors, isDark, icon, title, subtitle, right }: any) {
  return (
    <View style={settingRowStyles.row}>
      <View style={[settingRowStyles.iconWrap, { backgroundColor: isDark ? 'rgba(182,160,255,0.08)' : 'rgba(124,77,255,0.06)' }]}>
        <MaterialCommunityIcons name={icon} size={18} color={colors.primary} />
      </View>
      <View style={settingRowStyles.content}>
        <Text style={[settingRowStyles.title, { color: colors.onSurface }]}>{title}</Text>
        {subtitle && <Text style={[settingRowStyles.subtitle, { color: colors.onSurfaceVariant }]}>{subtitle}</Text>}
      </View>
      {right && <View style={settingRowStyles.right}>{right}</View>}
    </View>
  );
}

const settingRowStyles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 14,
    paddingHorizontal: 16,
  },
  iconWrap: {
    width: 32,
    height: 32,
    borderRadius: 10,
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 14,
  },
  content: {
    flex: 1,
  },
  title: {
    fontSize: 15,
    fontWeight: '600',
  },
  subtitle: {
    fontSize: 12,
    marginTop: 2,
  },
  right: {
    marginLeft: 8,
  },
});

function createStyles(colors: any, isDark: boolean) {
  return StyleSheet.create({
    container: { flex: 1, backgroundColor: colors.background },
    atmosphereContainer: { ...StyleSheet.absoluteFillObject, overflow: 'hidden' },
    blob: { position: 'absolute', borderRadius: 999 },
    blobPrimary: {
      width: SCREEN_WIDTH * 0.5,
      height: SCREEN_WIDTH * 0.5,
      top: -SCREEN_WIDTH * 0.1,
      right: -SCREEN_WIDTH * 0.1,
      backgroundColor: isDark ? 'rgba(182,160,255,0.05)' : 'rgba(124,77,255,0.05)',
    },
    headerSafe: { zIndex: 50 },
    header: { paddingHorizontal: 24, paddingVertical: 12 },
    headerTitle: { fontSize: 28, fontWeight: '800', letterSpacing: -0.5 },
    scrollView: { flex: 1, zIndex: 10 },
    scrollContent: { paddingHorizontal: 24 },

    sectionLabel: {
      fontSize: 11,
      fontWeight: '800',
      letterSpacing: 1.5,
      textTransform: 'uppercase',
      marginTop: 24,
      marginBottom: 10,
      marginLeft: 4,
    },
    card: {
      borderRadius: 16,
      borderWidth: StyleSheet.hairlineWidth,
      overflow: 'hidden',
    },
    separator: {
      height: StyleSheet.hairlineWidth,
      marginLeft: 62,
    },

    themeRow: {
      flexDirection: 'row',
      gap: 8,
      paddingHorizontal: 16,
      paddingBottom: 16,
      paddingTop: 4,
    },
    themeOption: {
      flex: 1,
      alignItems: 'center',
      paddingVertical: 12,
      borderRadius: 12,
      borderWidth: 1.5,
      gap: 4,
    },
    themeOptionText: {
      fontSize: 11,
      fontWeight: '600',
    },
    itemTitle: {
      fontSize: 13,
      fontWeight: '600',
      paddingHorizontal: 16,
      paddingTop: 14,
      paddingBottom: 8,
    },
  });
}
