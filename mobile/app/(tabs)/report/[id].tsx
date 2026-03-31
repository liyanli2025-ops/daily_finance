import React, { useEffect } from 'react';
import { View, ScrollView, StyleSheet, Share } from 'react-native';
import { Text, useTheme, IconButton, Chip, Divider, ActivityIndicator } from 'react-native-paper';
import { useLocalSearchParams, router } from 'expo-router';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import Markdown from 'react-native-markdown-display';
import { useReportStore } from '@/stores/reportStore';
import AudioPlayer from '@/components/AudioPlayer';

export default function ReportDetailScreen() {
  const theme = useTheme();
  const { id } = useLocalSearchParams<{ id: string }>();
  const { currentReport, todayReport, isLoading, fetchReport } = useReportStore();

  // 优先使用todayReport，如果ID匹配的话
  const report = currentReport?.id === id ? currentReport : 
                 todayReport?.id === id ? todayReport : 
                 currentReport;

  useEffect(() => {
    if (id && (!report || report.id !== id)) {
      fetchReport(id);
    }
  }, [id]);

  const handleShare = async () => {
    if (report) {
      try {
        await Share.share({
          title: report.title,
          message: `${report.title}\n\n${report.summary}\n\n来自财经日报App`,
        });
      } catch (error) {
        console.error('分享失败:', error);
      }
    }
  };

  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr);
    return date.toLocaleDateString('zh-CN', {
      year: 'numeric',
      month: 'long',
      day: 'numeric',
      weekday: 'long',
    });
  };

  const markdownStyles = {
    body: {
      color: theme.colors.onSurface,
      fontSize: 16,
      lineHeight: 30, // 26 → 30，行间距更大
    },
    heading1: {
      color: theme.colors.onSurface,
      fontSize: 24,
      fontWeight: '700' as const,
      marginTop: 36, // 24 → 36
      marginBottom: 16, // 12 → 16
    },
    heading2: {
      color: theme.colors.onSurface,
      fontSize: 20,
      fontWeight: '600' as const,
      marginTop: 32, // 20 → 32
      marginBottom: 14, // 10 → 14
    },
    heading3: {
      color: theme.colors.onSurface,
      fontSize: 18,
      fontWeight: '600' as const,
      marginTop: 24, // 16 → 24
      marginBottom: 10, // 8 → 10
    },
    paragraph: {
      marginBottom: 20, // 12 → 20
    },
    bullet_list: {
      marginBottom: 16, // 12 → 16
    },
    ordered_list: {
      marginBottom: 16, // 12 → 16
    },
    list_item: {
      marginBottom: 8, // 4 → 8
    },
    blockquote: {
      backgroundColor: theme.colors.surfaceVariant,
      borderLeftColor: theme.colors.primary,
      borderLeftWidth: 4,
      paddingHorizontal: 16,
      paddingVertical: 12, // 8 → 12
      marginVertical: 20, // 12 → 20
    },
    code_inline: {
      backgroundColor: theme.colors.surfaceVariant,
      color: theme.colors.primary,
      paddingHorizontal: 6,
      paddingVertical: 2,
      borderRadius: 4,
      fontFamily: 'monospace',
    },
    fence: {
      backgroundColor: theme.colors.surfaceVariant,
      borderRadius: 8,
      padding: 16, // 12 → 16
      marginVertical: 20, // 12 → 20
    },
    strong: {
      fontWeight: '700' as const,
      letterSpacing: 0.3, // 加粗字间距
    },
    em: {
      fontStyle: 'italic' as const,
    },
    hr: {
      backgroundColor: theme.colors.outline,
      height: 1,
      marginVertical: 28, // 16 → 28
    },
  };

  if (isLoading) {
    return (
      <View style={[styles.loadingContainer, { backgroundColor: theme.colors.background }]}>
        <ActivityIndicator size="large" color={theme.colors.primary} />
        <Text style={{ marginTop: 16, color: theme.colors.outline }}>
          正在加载报告...
        </Text>
      </View>
    );
  }

  if (!report) {
    return (
      <View style={[styles.loadingContainer, { backgroundColor: theme.colors.background }]}>
        <MaterialCommunityIcons name="file-document-outline" size={64} color={theme.colors.outline} />
        <Text variant="titleMedium" style={{ marginTop: 16, color: theme.colors.outline }}>
          报告不存在
        </Text>
      </View>
    );
  }

  return (
    <View style={[styles.container, { backgroundColor: theme.colors.background }]}>
      {/* 顶部操作栏 */}
      <View style={[styles.toolbar, { backgroundColor: theme.colors.surface }]}>
        <IconButton
          icon="arrow-left"
          iconColor={theme.colors.onSurface}
          onPress={() => router.back()}
        />
        <View style={styles.toolbarActions}>
          {report.podcast_status === 'ready' && (
            <IconButton
              icon="podcast"
              iconColor={theme.colors.secondary}
              onPress={() => router.push('/podcast')}
            />
          )}
          <IconButton
            icon="share-variant"
            iconColor={theme.colors.onSurface}
            onPress={handleShare}
          />
        </View>
      </View>

      <ScrollView style={styles.scrollView} showsVerticalScrollIndicator={false}>
        {/* 报告头部 */}
        <View style={styles.header}>
          <Text variant="headlineSmall" style={styles.title}>
            {report.title}
          </Text>
          <View style={styles.metaRow}>
            <Text variant="bodyMedium" style={{ color: theme.colors.outline }}>
              {formatDate(report.report_date)}
            </Text>
          </View>
          <View style={styles.statsRow}>
            <Chip icon="clock-outline" compact style={styles.statChip}>
              {report.reading_time || 10} 分钟阅读
            </Chip>
            <Chip icon="newspaper" compact style={styles.statChip}>
              {report.news_count || 0} 条新闻
            </Chip>
            <Chip icon="text" compact style={styles.statChip}>
              {report.word_count || 0} 字
            </Chip>
          </View>
        </View>

        {/* 播客播放器 */}
        {report.podcast_status === 'ready' && report.podcast_url && (
          <View style={styles.playerSection}>
            <AudioPlayer
              reportId={report.id}
              reportTitle={report.title}
              audioUrl={report.podcast_url}
              duration={report.podcast_duration || 0}
              reportDate={report.report_date}
              reportType={report.report_type as 'morning' | 'evening'}
            />
          </View>
        )}

        {/* 摘要 */}
        <View style={[styles.summarySection, { backgroundColor: theme.colors.surfaceVariant }]}>
          <Text variant="titleSmall" style={styles.sectionLabel}>
            📋 摘要
          </Text>
          <Text variant="bodyMedium" style={styles.summaryText}>
            {report.summary}
          </Text>
        </View>

        {/* 核心观点 */}
        {report.core_opinions && report.core_opinions.length > 0 && (
          <View style={[styles.coreOpinionsSection, { backgroundColor: theme.colors.primary + '15' }]}>
            <Text variant="titleSmall" style={styles.sectionLabel}>
              🎯 今日核心观点
            </Text>
            {report.core_opinions.map((opinion: string, index: number) => (
              <View key={index} style={styles.opinionItem}>
                <Text variant="titleSmall" style={{ color: theme.colors.primary }}>
                  {index + 1}.
                </Text>
                <Text variant="bodyMedium" style={styles.opinionText}>
                  {opinion}
                </Text>
              </View>
            ))}
          </View>
        )}

        {/* 跨界热点 */}
        {report.cross_border_events && report.cross_border_events.length > 0 && (
          <View style={styles.crossBorderSection}>
            <Text variant="titleMedium" style={styles.sectionTitle}>
              🌍 跨界热点扫描
            </Text>
            {report.cross_border_events.map((event: any, index: number) => (
              <View key={index} style={[styles.crossBorderCard, { backgroundColor: theme.colors.surface }]}>
                <View style={styles.crossBorderHeader}>
                  <Chip compact style={styles.categoryChip}>
                    {event.category === 'geopolitical' ? '地缘政治' :
                     event.category === 'tech' ? '科技' :
                     event.category === 'social' ? '社会舆论' :
                     event.category === 'disaster' ? '自然灾害' : '其他'}
                  </Chip>
                  <Text variant="titleSmall" style={{ flex: 1, marginLeft: 8 }}>
                    {event.title}
                  </Text>
                </View>
                <Text variant="bodySmall" style={styles.crossBorderSummary}>
                  {event.summary}
                </Text>
                <View style={styles.impactRow}>
                  <View style={styles.impactItem}>
                    <Text variant="labelSmall" style={{ color: '#22C55E' }}>受益</Text>
                    <Text variant="bodySmall">{event.beneficiaries?.join('、') || '暂无'}</Text>
                  </View>
                  <View style={styles.impactItem}>
                    <Text variant="labelSmall" style={{ color: '#EF4444' }}>受损</Text>
                    <Text variant="bodySmall">{event.losers?.join('、') || '暂无'}</Text>
                  </View>
                </View>
              </View>
            ))}
          </View>
        )}

        <Divider style={styles.divider} />

        {/* 正文内容 */}
        <View style={styles.contentSection}>
          <Markdown style={markdownStyles}>{report.content}</Markdown>
        </View>

        {/* 市场分析 */}
        {report.analysis && (
          <View style={styles.analysisSection}>
            <Text variant="titleMedium" style={styles.sectionTitle}>
              📊 市场分析
            </Text>
            
            <View style={[styles.analysisCard, { backgroundColor: theme.colors.surface }]}>
              <View style={styles.analysisRow}>
                <Text variant="bodyMedium">整体情绪：</Text>
                <Chip
                  style={{
                    backgroundColor:
                      report.analysis.overall_sentiment === 'positive'
                        ? '#1B5E20'
                        : report.analysis.overall_sentiment === 'negative'
                        ? '#B71C1C'
                        : theme.colors.outline,
                  }}
                  textStyle={{ color: '#fff', fontSize: 12 }}
                >
                  {report.analysis.overall_sentiment === 'positive'
                    ? '乐观'
                    : report.analysis.overall_sentiment === 'negative'
                    ? '悲观'
                    : '中性'}
                </Chip>
              </View>

              {report.analysis.opportunities.length > 0 && (
                <View style={styles.analysisItem}>
                  <Text variant="bodySmall" style={{ color: theme.colors.outline }}>
                    投资机会
                  </Text>
                  <View style={styles.tagContainer}>
                    {report.analysis.opportunities.map((opp, i) => (
                      <Chip key={i} compact style={styles.tag}>
                        {opp}
                      </Chip>
                    ))}
                  </View>
                </View>
              )}

              {report.analysis.risks.length > 0 && (
                <View style={styles.analysisItem}>
                  <Text variant="bodySmall" style={{ color: theme.colors.outline }}>
                    风险提示
                  </Text>
                  <View style={styles.tagContainer}>
                    {report.analysis.risks.map((risk, i) => (
                      <Chip key={i} compact style={[styles.tag, { backgroundColor: '#B71C1C' }]}>
                        {risk}
                      </Chip>
                    ))}
                  </View>
                </View>
              )}
            </View>
          </View>
        )}

        {/* 底部安全区 - 给底部导航栏让路 */}
        <View style={{ height: 100 }} />
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  loadingContainer: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
  toolbar: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: 4,
    paddingVertical: 8, // 4 → 8
  },
  toolbarActions: {
    flexDirection: 'row',
  },
  scrollView: {
    flex: 1,
    paddingHorizontal: 20, // 16 → 20
  },
  header: {
    paddingTop: 12, // 8 → 12
    paddingBottom: 24, // 16 → 24
  },
  title: {
    fontWeight: '700',
    marginBottom: 12, // 8 → 12
  },
  metaRow: {
    marginBottom: 16, // 12 → 16
  },
  statsRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
  statChip: {
    height: 28,
  },
  playerSection: {
    marginBottom: 24, // 16 → 24
  },
  summarySection: {
    padding: 20, // 16 → 20
    borderRadius: 12,
    marginBottom: 24, // 16 → 24
  },
  sectionLabel: {
    fontWeight: '600',
    marginBottom: 12, // 8 → 12
  },
  summaryText: {
    lineHeight: 26, // 24 → 26
  },
  // 核心观点样式
  coreOpinionsSection: {
    padding: 20, // 16 → 20
    borderRadius: 12,
    marginBottom: 24, // 16 → 24
  },
  opinionItem: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    marginBottom: 16, // 12 → 16
    gap: 10, // 8 → 10
  },
  opinionText: {
    flex: 1,
    lineHeight: 24, // 22 → 24
    fontWeight: '500',
  },
  // 跨界热点样式
  crossBorderSection: {
    marginBottom: 24, // 16 → 24
  },
  crossBorderCard: {
    padding: 16, // 14 → 16
    borderRadius: 12,
    marginBottom: 16, // 12 → 16
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.1,
    shadowRadius: 4,
    elevation: 2,
  },
  crossBorderHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 12, // 10 → 12
  },
  categoryChip: {
    height: 26,
  },
  crossBorderSummary: {
    lineHeight: 22, // 20 → 22
    marginBottom: 16, // 12 → 16
    opacity: 0.85,
  },
  impactRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    gap: 12,
  },
  impactItem: {
    flex: 1,
    padding: 12, // 10 → 12
    borderRadius: 8,
    backgroundColor: 'rgba(0,0,0,0.05)',
  },
  divider: {
    marginBottom: 24, // 16 → 24
  },
  contentSection: {
    paddingBottom: 32, // 24 → 32
  },
  analysisSection: {
    marginTop: 24, // 16 → 24
  },
  sectionTitle: {
    fontWeight: '600',
    marginBottom: 16, // 12 → 16
  },
  analysisCard: {
    padding: 20, // 16 → 20
    borderRadius: 12,
  },
  analysisRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 20, // 16 → 20
  },
  analysisItem: {
    marginBottom: 16, // 12 → 16
  },
  tagContainer: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
    marginTop: 10, // 8 → 10
  },
  tag: {
    height: 28,
  },
});
