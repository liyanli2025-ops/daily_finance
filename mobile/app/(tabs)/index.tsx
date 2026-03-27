import React, { useEffect, useState } from 'react';
import {
  View,
  ScrollView,
  StyleSheet,
  RefreshControl,
  Text,
  TouchableOpacity,
  ActivityIndicator,
  Platform,
  Dimensions,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import { router } from 'expo-router';
import { useReportStore } from '@/stores/reportStore';
import { useAppTheme } from '@/theme/ThemeContext';
import { useAudioStore } from '@/stores/audioStore';

const { width: SCREEN_WIDTH } = Dimensions.get('window');

export default function HomeScreen() {
  const { colors, isDark } = useAppTheme();
  const { todayReport, recentReports, isLoading, fetchTodayReport, fetchRecentReports } = useReportStore();
  const { isPlaying, play, pause, currentReportId } = useAudioStore();
  const [refreshing, setRefreshing] = useState(false);

  useEffect(() => {
    fetchTodayReport();
    fetchRecentReports();
  }, []);

  const onRefresh = async () => {
    setRefreshing(true);
    await Promise.all([fetchTodayReport(), fetchRecentReports()]);
    setRefreshing(false);
  };

  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr);
    return date.toLocaleDateString('zh-CN', { month: 'long', day: 'numeric', weekday: 'long' });
  };

  const formatShortDate = (dateStr: string) => {
    const date = new Date(dateStr);
    return `${date.getFullYear()}年${date.getMonth() + 1}月${date.getDate()}日`;
  };

  const today = new Date();
  const dateStr = formatDate(today.toISOString());

  const styles = createStyles(colors, isDark);

  return (
    <View style={styles.container}>
      {/* 氛围背景 */}
      <View style={styles.atmosphereContainer}>
        <View style={[styles.blob, styles.blobPrimary]} />
        <View style={[styles.blob, styles.blobSecondary]} />
      </View>

      {/* 顶部导航 */}
      <SafeAreaView edges={['top']} style={styles.headerSafe}>
        <View style={styles.header}>
          <View style={styles.headerLeft}>
            <View style={[styles.calendarIcon, { backgroundColor: isDark ? 'rgba(182,160,255,0.1)' : 'rgba(124,77,255,0.08)' }]}>
              <MaterialCommunityIcons name="calendar-today" size={20} color={colors.primary} />
            </View>
            <Text style={[styles.headerTitle, { color: colors.onSurface }]}>首页</Text>
          </View>
          <View style={styles.headerRight}>
            <TouchableOpacity style={styles.headerButton}>
              <MaterialCommunityIcons name="magnify" size={22} color={colors.onSurfaceVariant} />
            </TouchableOpacity>
            <View style={[styles.avatar, { backgroundColor: isDark ? colors.surfaceContainerHigh : colors.surfaceContainerLow, borderColor: isDark ? 'rgba(255,255,255,0.1)' : 'rgba(124,77,255,0.15)' }]}>
              <MaterialCommunityIcons name="account" size={18} color={colors.primary} />
            </View>
          </View>
        </View>
      </SafeAreaView>

      <ScrollView
        style={styles.scrollView}
        contentContainerStyle={styles.scrollContent}
        showsVerticalScrollIndicator={false}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.primary} />
        }
      >
        {/* Hero Header */}
        <View style={styles.heroHeader}>
          <Text style={[styles.heroTitle, { color: colors.onSurface }]}>每日财经播报</Text>
          <Text style={[styles.heroSubtitle, { color: colors.onSurfaceVariant }]}>{dateStr}</Text>
        </View>

        {/* 今日报告 */}
        {isLoading ? (
          <View style={styles.loadingContainer}>
            <ActivityIndicator size="large" color={colors.primary} />
            <Text style={[styles.loadingText, { color: colors.onSurfaceVariant }]}>正在获取今日报告...</Text>
          </View>
        ) : todayReport ? (
          <TouchableOpacity
            style={[styles.todayCard, {
              backgroundColor: isDark ? colors.glassBackground : colors.glassBackground,
              borderColor: isDark ? colors.glassBorder : colors.glassBorder,
            }]}
            activeOpacity={0.8}
            onPress={() => router.push(`/report/${todayReport.id}`)}
          >
            <View style={styles.todayCardInner}>
              <View style={[styles.todayBadge, { backgroundColor: isDark ? 'rgba(182,160,255,0.15)' : 'rgba(124,77,255,0.1)' }]}>
                <MaterialCommunityIcons name="fire" size={12} color={colors.primary} />
                <Text style={[styles.todayBadgeText, { color: colors.primary }]}>今日报告</Text>
              </View>

              <Text style={[styles.todayTitle, { color: colors.onSurface }]} numberOfLines={2}>
                {todayReport.title}
              </Text>

              <Text style={[styles.todaySummary, { color: colors.onSurfaceVariant }]} numberOfLines={3}>
                {todayReport.summary}
              </Text>

              {/* 核心观点预览 */}
              {todayReport.core_opinions && todayReport.core_opinions.length > 0 && (
                <View style={[styles.opinionPreview, {
                  backgroundColor: isDark ? 'rgba(182,160,255,0.06)' : 'rgba(124,77,255,0.04)',
                  borderLeftColor: colors.primary,
                }]}>
                  <Text style={[styles.opinionLabel, { color: colors.primary }]}>🎯 核心观点</Text>
                  <Text style={[styles.opinionText, { color: colors.onSurface }]} numberOfLines={2}>
                    {todayReport.core_opinions[0]}
                  </Text>
                </View>
              )}

              {/* 底部信息 */}
              <View style={styles.todayMeta}>
                <View style={styles.metaItem}>
                  <MaterialCommunityIcons name="clock-outline" size={14} color={colors.onSurfaceVariant} />
                  <Text style={[styles.metaText, { color: colors.onSurfaceVariant }]}>{todayReport.reading_time || 10}分钟</Text>
                </View>
                <View style={styles.metaItem}>
                  <MaterialCommunityIcons name="newspaper" size={14} color={colors.onSurfaceVariant} />
                  <Text style={[styles.metaText, { color: colors.onSurfaceVariant }]}>{todayReport.news_count || 0}条新闻</Text>
                </View>
                {todayReport.podcast_status === 'ready' && (
                  <View style={styles.metaItem}>
                    <MaterialCommunityIcons name="podcast" size={14} color={colors.bullish} />
                    <Text style={[styles.metaText, { color: colors.bullish }]}>播客就绪</Text>
                  </View>
                )}
              </View>
            </View>
          </TouchableOpacity>
        ) : (
          <View style={[styles.emptyCard, {
            backgroundColor: isDark ? colors.glassBackground : colors.glassBackground,
            borderColor: isDark ? colors.glassBorder : colors.glassBorder,
          }]}>
            <MaterialCommunityIcons name="file-document-outline" size={48} color={colors.onSurfaceVariant} />
            <Text style={[styles.emptyTitle, { color: colors.onSurfaceVariant }]}>今日报告尚未生成</Text>
            <Text style={[styles.emptySubtitle, { color: colors.outline }]}>报告将在每天早上 7:00 自动生成</Text>
          </View>
        )}

        {/* 历史播报存档 */}
        <View style={styles.sectionHeader}>
          <Text style={[styles.sectionTitle, { color: colors.onSurface }]}>历史播报存档</Text>
          <Text style={[styles.sectionSubtitle, { color: colors.onSurfaceVariant }]}>回顾往期财经播报</Text>
        </View>

        <View style={styles.archiveList}>
          {recentReports.slice(0, 10).map((report, index) => {
            const isCurrentPlaying = currentReportId === report.id && isPlaying;
            const hasPodcast = report.podcast_status === 'ready';

            return (
              <TouchableOpacity
                key={report.id}
                style={[styles.archiveItem, {
                  backgroundColor: isDark ? colors.glassBackground : colors.glassBackground,
                  borderColor: isDark ? colors.glassBorder : colors.glassBorder,
                }]}
                activeOpacity={0.7}
                onPress={() => router.push(`/report/${report.id}`)}
              >
                <View style={styles.archiveContent}>
                  <Text style={[styles.archiveDate, {
                    color: index === 0 ? colors.primary : colors.onSurfaceVariant,
                  }]}>
                    {formatShortDate(report.report_date)}
                  </Text>
                  <Text style={[styles.archiveTitle, { color: colors.onSurface }]} numberOfLines={1}>
                    {report.title}
                  </Text>
                </View>
                {hasPodcast && (
                  <TouchableOpacity
                    style={[styles.playBtn, {
                      backgroundColor: isCurrentPlaying
                        ? colors.primary
                        : (isDark ? 'rgba(255,255,255,0.05)' : 'rgba(124,77,255,0.08)'),
                    }]}
                    onPress={(e) => {
                      e.stopPropagation();
                      if (isCurrentPlaying) {
                        pause();
                      } else {
                        play(report.id, report.podcast_url || '');
                      }
                    }}
                  >
                    <MaterialCommunityIcons
                      name={isCurrentPlaying ? 'pause' : 'play'}
                      size={20}
                      color={isCurrentPlaying ? '#FFFFFF' : colors.primary}
                    />
                  </TouchableOpacity>
                )}
              </TouchableOpacity>
            );
          })}

          {recentReports.length === 0 && !isLoading && (
            <View style={styles.emptyArchive}>
              <Text style={[styles.emptyArchiveText, { color: colors.onSurfaceVariant }]}>暂无历史报告</Text>
            </View>
          )}
        </View>

        {/* 底部安全区域 */}
        <View style={{ height: 120 }} />
      </ScrollView>
    </View>
  );
}

function createStyles(colors: any, isDark: boolean) {
  return StyleSheet.create({
    container: {
      flex: 1,
      backgroundColor: colors.background,
    },
    atmosphereContainer: {
      ...StyleSheet.absoluteFillObject,
      overflow: 'hidden',
    },
    blob: {
      position: 'absolute',
      borderRadius: 999,
    },
    blobPrimary: {
      width: SCREEN_WIDTH * 0.65,
      height: SCREEN_WIDTH * 0.65,
      top: -SCREEN_WIDTH * 0.1,
      left: -SCREEN_WIDTH * 0.1,
      backgroundColor: isDark ? 'rgba(182,160,255,0.06)' : 'rgba(124,77,255,0.06)',
    },
    blobSecondary: {
      width: SCREEN_WIDTH * 0.5,
      height: SCREEN_WIDTH * 0.5,
      bottom: '20%',
      right: -SCREEN_WIDTH * 0.08,
      backgroundColor: isDark ? 'rgba(51,103,255,0.04)' : 'rgba(124,77,255,0.04)',
    },

    // Header
    headerSafe: { zIndex: 50 },
    header: {
      flexDirection: 'row',
      justifyContent: 'space-between',
      alignItems: 'center',
      paddingHorizontal: 24,
      paddingVertical: 12,
    },
    headerLeft: { flexDirection: 'row', alignItems: 'center', gap: 10 },
    calendarIcon: {
      width: 34,
      height: 34,
      borderRadius: 12,
      alignItems: 'center',
      justifyContent: 'center',
    },
    headerTitle: { fontSize: 18, fontWeight: '700', letterSpacing: -0.3 },
    headerRight: { flexDirection: 'row', alignItems: 'center', gap: 12 },
    headerButton: { padding: 4 },
    avatar: {
      width: 30,
      height: 30,
      borderRadius: 15,
      alignItems: 'center',
      justifyContent: 'center',
      borderWidth: StyleSheet.hairlineWidth,
    },

    scrollView: { flex: 1, zIndex: 10 },
    scrollContent: { paddingHorizontal: 24 },

    // Hero
    heroHeader: { marginBottom: 20, marginTop: 4 },
    heroTitle: { fontSize: 28, fontWeight: '800', letterSpacing: -0.5 },
    heroSubtitle: { fontSize: 13, fontWeight: '500', marginTop: 4 },

    // 加载
    loadingContainer: { alignItems: 'center', paddingVertical: 60 },
    loadingText: { marginTop: 16, fontSize: 14 },

    // 今日报告
    todayCard: {
      borderRadius: 20,
      borderWidth: StyleSheet.hairlineWidth,
      overflow: 'hidden',
      marginBottom: 28,
      ...Platform.select({
        ios: { shadowColor: isDark ? '#7C4DFF' : '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.06, shadowRadius: 16 },
        android: { elevation: 3 },
      }),
    },
    todayCardInner: { padding: 20 },
    todayBadge: {
      flexDirection: 'row',
      alignItems: 'center',
      alignSelf: 'flex-start',
      gap: 4,
      paddingHorizontal: 10,
      paddingVertical: 4,
      borderRadius: 999,
      marginBottom: 12,
    },
    todayBadgeText: { fontSize: 10, fontWeight: '800', letterSpacing: 0.5 },
    todayTitle: { fontSize: 20, fontWeight: '700', lineHeight: 28, marginBottom: 8 },
    todaySummary: { fontSize: 14, lineHeight: 22, marginBottom: 12 },
    opinionPreview: {
      padding: 12,
      borderRadius: 12,
      borderLeftWidth: 3,
      marginBottom: 16,
    },
    opinionLabel: { fontSize: 11, fontWeight: '700', marginBottom: 4 },
    opinionText: { fontSize: 13, lineHeight: 20 },
    todayMeta: { flexDirection: 'row', gap: 16 },
    metaItem: { flexDirection: 'row', alignItems: 'center', gap: 4 },
    metaText: { fontSize: 12 },

    // 空状态
    emptyCard: {
      borderRadius: 20,
      borderWidth: StyleSheet.hairlineWidth,
      padding: 40,
      alignItems: 'center',
      marginBottom: 28,
    },
    emptyTitle: { fontSize: 16, fontWeight: '600', marginTop: 16 },
    emptySubtitle: { fontSize: 13, marginTop: 6 },

    // 存档区
    sectionHeader: { marginBottom: 16 },
    sectionTitle: { fontSize: 22, fontWeight: '800', letterSpacing: -0.3 },
    sectionSubtitle: { fontSize: 13, fontWeight: '500', marginTop: 2 },

    archiveList: { gap: 10 },
    archiveItem: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      padding: 16,
      borderRadius: 16,
      borderWidth: StyleSheet.hairlineWidth,
    },
    archiveContent: { flex: 1, marginRight: 12 },
    archiveDate: { fontSize: 10, fontWeight: '700', letterSpacing: 1, textTransform: 'uppercase', marginBottom: 3 },
    archiveTitle: { fontSize: 15, fontWeight: '600' },

    playBtn: {
      width: 40,
      height: 40,
      borderRadius: 20,
      alignItems: 'center',
      justifyContent: 'center',
    },

    emptyArchive: { paddingVertical: 40, alignItems: 'center' },
    emptyArchiveText: { fontSize: 14 },
  });
}
