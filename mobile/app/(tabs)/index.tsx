import React, { useEffect, useState } from 'react';
import { View, ScrollView, StyleSheet, RefreshControl } from 'react-native';
import { Text, Card, Chip, Button, useTheme, ActivityIndicator } from 'react-native-paper';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import { router } from 'expo-router';
import { useReportStore } from '@/stores/reportStore';
import ReportCard from '@/components/ReportCard';

export default function HomeScreen() {
  const theme = useTheme();
  const { todayReport, recentReports, isLoading, fetchTodayReport, fetchRecentReports } = useReportStore();
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
    return date.toLocaleDateString('zh-CN', {
      month: 'long',
      day: 'numeric',
      weekday: 'long'
    });
  };

  return (
    <ScrollView
      style={[styles.container, { backgroundColor: theme.colors.background }]}
      refreshControl={
        <RefreshControl
          refreshing={refreshing}
          onRefresh={onRefresh}
          tintColor={theme.colors.primary}
        />
      }
    >
      {/* 日期标题 */}
      <View style={styles.header}>
        <Text variant="headlineMedium" style={styles.dateText}>
          {formatDate(new Date().toISOString())}
        </Text>
        <Text variant="bodyMedium" style={{ color: theme.colors.outline }}>
          财经深度日报
        </Text>
      </View>

      {/* 今日报告卡片 */}
      {isLoading ? (
        <View style={styles.loadingContainer}>
          <ActivityIndicator size="large" color={theme.colors.primary} />
          <Text style={{ marginTop: 16, color: theme.colors.outline }}>
            正在获取今日报告...
          </Text>
        </View>
      ) : todayReport ? (
        <Card
          style={[styles.mainCard, { backgroundColor: theme.colors.surfaceVariant }]}
          onPress={() => router.push(`/report/${todayReport.id}`)}
        >
          <Card.Content>
            <View style={styles.cardHeader}>
              <Chip
                icon="fire"
                style={{ backgroundColor: theme.colors.primaryContainer }}
                textStyle={{ color: theme.colors.primary }}
              >
                今日报告
              </Chip>
              {todayReport.podcast_status === 'ready' && (
                <Chip
                  icon="podcast"
                  style={{ backgroundColor: theme.colors.secondaryContainer }}
                  textStyle={{ color: theme.colors.secondary }}
                >
                  播客已就绪
                </Chip>
              )}
            </View>
            
            <Text variant="titleLarge" style={styles.reportTitle}>
              {todayReport.title}
            </Text>
            
            <Text variant="bodyMedium" style={styles.reportSummary} numberOfLines={4}>
              {todayReport.summary}
            </Text>

            {/* 今日核心观点预览 */}
            {todayReport.core_opinions && todayReport.core_opinions.length > 0 && (
              <View style={styles.coreOpinionsPreview}>
                <Text variant="labelMedium" style={{ color: theme.colors.primary, fontWeight: '600', marginBottom: 8 }}>
                  🎯 今日核心观点
                </Text>
                <Text variant="bodySmall" style={{ opacity: 0.9, lineHeight: 18 }} numberOfLines={2}>
                  {todayReport.core_opinions[0]}
                </Text>
              </View>
            )}

            <View style={styles.reportMeta}>
              <View style={styles.metaItem}>
                <MaterialCommunityIcons name="clock-outline" size={16} color={theme.colors.outline} />
                <Text style={styles.metaText}>
                  {todayReport.reading_time || 10} 分钟阅读
                </Text>
              </View>
              <View style={styles.metaItem}>
                <MaterialCommunityIcons name="newspaper" size={16} color={theme.colors.outline} />
                <Text style={styles.metaText}>
                  {todayReport.news_count || 0} 条新闻
                </Text>
              </View>
              {todayReport.cross_border_count && todayReport.cross_border_count > 0 && (
                <View style={styles.metaItem}>
                  <MaterialCommunityIcons name="earth" size={16} color={theme.colors.secondary} />
                  <Text style={[styles.metaText, { color: theme.colors.secondary }]}>
                    {todayReport.cross_border_count} 跨界热点
                  </Text>
                </View>
              )}
            </View>

            <Button
              mode="contained"
              style={styles.readButton}
              onPress={() => router.push(`/report/${todayReport.id}`)}
            >
              阅读完整报告
            </Button>
          </Card.Content>
        </Card>
      ) : (
        <Card style={[styles.mainCard, { backgroundColor: theme.colors.surfaceVariant }]}>
          <Card.Content style={styles.emptyCard}>
            <MaterialCommunityIcons name="file-document-outline" size={64} color={theme.colors.outline} />
            <Text variant="titleMedium" style={{ marginTop: 16, color: theme.colors.outline }}>
              今日报告尚未生成
            </Text>
            <Text variant="bodySmall" style={{ marginTop: 8, color: theme.colors.outline }}>
              报告将在每天早上 6:00 自动生成
            </Text>
          </Card.Content>
        </Card>
      )}

      {/* 跨界热点预览 */}
      {todayReport?.cross_border_events && todayReport.cross_border_events.length > 0 && (
        <View style={styles.section}>
          <Text variant="titleMedium" style={styles.sectionTitle}>
            🌍 跨界热点
          </Text>
          {todayReport.cross_border_events.slice(0, 2).map((event: any, index: number) => (
            <Card
              key={index}
              style={[styles.crossBorderCard, { backgroundColor: theme.colors.surface }]}
              onPress={() => router.push(`/report/${todayReport.id}`)}
            >
              <Card.Content>
                <View style={styles.crossBorderHeader}>
                  <Chip
                    compact
                    style={{ 
                      backgroundColor: 
                        event.category === 'geopolitical' ? '#6366F1' :
                        event.category === 'tech' ? '#22C55E' :
                        event.category === 'social' ? '#F59E0B' :
                        '#EF4444'
                    }}
                    textStyle={{ color: '#fff', fontSize: 10 }}
                  >
                    {event.category === 'geopolitical' ? '地缘政治' :
                     event.category === 'tech' ? '科技' :
                     event.category === 'social' ? '社会舆论' : '自然灾害'}
                  </Chip>
                </View>
                <Text variant="titleSmall" style={{ marginTop: 8, fontWeight: '600' }}>
                  {event.title}
                </Text>
                <Text variant="bodySmall" style={{ marginTop: 4, color: theme.colors.outline }} numberOfLines={2}>
                  {event.summary}
                </Text>
                {event.beneficiaries && event.beneficiaries.length > 0 && (
                  <View style={styles.beneficiariesRow}>
                    <Text variant="labelSmall" style={{ color: '#22C55E' }}>
                      受益：{event.beneficiaries.slice(0, 3).join('、')}
                    </Text>
                  </View>
                )}
              </Card.Content>
            </Card>
          ))}
        </View>
      )}

      {/* 重点新闻 */}
      {todayReport?.highlights && todayReport.highlights.length > 0 && (
        <View style={styles.section}>
          <Text variant="titleMedium" style={styles.sectionTitle}>
            📰 重点新闻
          </Text>
          {todayReport.highlights.slice(0, 5).map((highlight, index) => (
            <Card
              key={index}
              style={[styles.highlightCard, { backgroundColor: theme.colors.surface }]}
            >
              <Card.Content>
                <View style={styles.highlightHeader}>
                  <Chip
                    style={{
                      backgroundColor:
                        highlight.sentiment === 'positive'
                          ? '#1B5E20'
                          : highlight.sentiment === 'negative'
                          ? '#B71C1C'
                          : theme.colors.outline
                    }}
                    textStyle={{ color: '#fff', fontSize: 10 }}
                  >
                    {highlight.sentiment === 'positive'
                      ? '利好'
                      : highlight.sentiment === 'negative'
                      ? '利空'
                      : '中性'}
                  </Chip>
                  <Text variant="bodySmall" style={{ color: theme.colors.outline }}>
                    {highlight.source}
                  </Text>
                </View>
                <Text variant="titleSmall" style={{ marginTop: 8 }}>
                  {highlight.title}
                </Text>
                <Text variant="bodySmall" style={{ marginTop: 4, color: theme.colors.outline }}>
                  {highlight.summary}
                </Text>
              </Card.Content>
            </Card>
          ))}
        </View>
      )}

      {/* 历史报告 */}
      {recentReports.length > 0 && (
        <View style={styles.section}>
          <Text variant="titleMedium" style={styles.sectionTitle}>
            📚 历史报告
          </Text>
          {recentReports.slice(0, 5).map((report) => (
            <ReportCard key={report.id} report={report} />
          ))}
        </View>
      )}

      <View style={{ height: 32 }} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    padding: 16,
  },
  header: {
    marginBottom: 20,
  },
  dateText: {
    fontWeight: '700',
    marginBottom: 4,
  },
  loadingContainer: {
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 60,
  },
  mainCard: {
    marginBottom: 20,
    borderRadius: 16,
  },
  cardHeader: {
    flexDirection: 'row',
    gap: 8,
    marginBottom: 12,
  },
  reportTitle: {
    fontWeight: '700',
    marginBottom: 8,
  },
  reportSummary: {
    lineHeight: 22,
    opacity: 0.8,
  },
  reportMeta: {
    flexDirection: 'row',
    gap: 20,
    marginTop: 16,
    marginBottom: 16,
  },
  metaItem: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
  },
  metaText: {
    fontSize: 13,
    opacity: 0.7,
  },
  readButton: {
    borderRadius: 8,
  },
  emptyCard: {
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 40,
  },
  section: {
    marginTop: 8,
  },
  sectionTitle: {
    fontWeight: '600',
    marginBottom: 12,
  },
  highlightCard: {
    marginBottom: 12,
    borderRadius: 12,
  },
  highlightHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  coreOpinionsPreview: {
    marginTop: 16,
    padding: 12,
    backgroundColor: 'rgba(37, 99, 235, 0.1)',
    borderRadius: 8,
    borderLeftWidth: 3,
    borderLeftColor: '#2563EB',
  },
  crossBorderCard: {
    marginBottom: 12,
    borderRadius: 12,
  },
  crossBorderHeader: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  beneficiariesRow: {
    marginTop: 8,
    paddingTop: 8,
    borderTopWidth: 1,
    borderTopColor: 'rgba(0,0,0,0.05)',
  },
});
