import React, { useState, useEffect, useCallback } from 'react';
import {
  View,
  ScrollView,
  StyleSheet,
  TextInput,
  TouchableOpacity,
  Text,
  ActivityIndicator,
  Keyboard,
  Platform,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import { router } from 'expo-router';
import { useAppTheme } from '@/theme/ThemeContext';
import { useReportStore } from '@/stores/reportStore';

export default function SearchScreen() {
  const { colors, isDark } = useAppTheme();
  const { recentReports, fetchRecentReports } = useReportStore();
  const [searchText, setSearchText] = useState('');
  const [isSearching, setIsSearching] = useState(false);
  const [filteredReports, setFilteredReports] = useState<any[]>([]);

  useEffect(() => {
    fetchRecentReports();
  }, []);

  // 搜索逻辑
  const handleSearch = useCallback((text: string) => {
    setSearchText(text);
    
    if (!text.trim()) {
      setFilteredReports([]);
      return;
    }

    setIsSearching(true);
    
    // 简单的本地搜索
    const searchLower = text.toLowerCase();
    const results = recentReports.filter((report: any) => {
      const titleMatch = report.title?.toLowerCase().includes(searchLower);
      const summaryMatch = report.summary?.toLowerCase().includes(searchLower);
      const dateMatch = report.report_date?.includes(text);
      return titleMatch || summaryMatch || dateMatch;
    });
    
    setFilteredReports(results);
    setIsSearching(false);
  }, [recentReports]);

  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr);
    return `${date.getFullYear()}年${date.getMonth() + 1}月${date.getDate()}日`;
  };

  const styles = createStyles(colors, isDark);

  return (
    <View style={styles.container}>
      <SafeAreaView edges={['top']} style={styles.safeArea}>
        {/* 搜索栏 */}
        <View style={styles.searchHeader}>
          <TouchableOpacity 
            style={styles.backButton}
            onPress={() => router.back()}
          >
            <MaterialCommunityIcons name="arrow-left" size={24} color={colors.onSurface} />
          </TouchableOpacity>
          
          <View style={[styles.searchInputContainer, { 
            backgroundColor: isDark ? colors.surfaceContainerHigh : colors.surfaceContainerLow,
            borderColor: isDark ? colors.glassBorder : colors.outline + '30',
          }]}>
            <MaterialCommunityIcons name="magnify" size={20} color={colors.onSurfaceVariant} />
            <TextInput
              style={[styles.searchInput, { color: colors.onSurface }]}
              placeholder="搜索报告标题、日期..."
              placeholderTextColor={colors.onSurfaceVariant}
              value={searchText}
              onChangeText={handleSearch}
              autoFocus
              returnKeyType="search"
              onSubmitEditing={() => Keyboard.dismiss()}
            />
            {searchText.length > 0 && (
              <TouchableOpacity onPress={() => handleSearch('')}>
                <MaterialCommunityIcons name="close-circle" size={18} color={colors.onSurfaceVariant} />
              </TouchableOpacity>
            )}
          </View>
        </View>

        {/* 搜索结果 */}
        <ScrollView 
          style={styles.scrollView}
          contentContainerStyle={styles.scrollContent}
          showsVerticalScrollIndicator={false}
          keyboardShouldPersistTaps="handled"
        >
          {isSearching ? (
            <View style={styles.loadingContainer}>
              <ActivityIndicator size="large" color={colors.primary} />
            </View>
          ) : searchText.trim() === '' ? (
            <View style={styles.emptyState}>
              <MaterialCommunityIcons name="text-search" size={64} color={colors.outline} />
              <Text style={[styles.emptyTitle, { color: colors.onSurfaceVariant }]}>
                搜索历史报告
              </Text>
              <Text style={[styles.emptySubtitle, { color: colors.outline }]}>
                输入关键词搜索标题、摘要或日期
              </Text>
            </View>
          ) : filteredReports.length === 0 ? (
            <View style={styles.emptyState}>
              <MaterialCommunityIcons name="file-search-outline" size={64} color={colors.outline} />
              <Text style={[styles.emptyTitle, { color: colors.onSurfaceVariant }]}>
                未找到相关报告
              </Text>
              <Text style={[styles.emptySubtitle, { color: colors.outline }]}>
                尝试其他关键词
              </Text>
            </View>
          ) : (
            <>
              <Text style={[styles.resultCount, { color: colors.onSurfaceVariant }]}>
                找到 {filteredReports.length} 篇报告
              </Text>
              {filteredReports.map((report: any) => (
                <TouchableOpacity
                  key={report.id}
                  style={[styles.resultItem, {
                    backgroundColor: isDark ? colors.glassBackground : colors.glassBackground,
                    borderColor: isDark ? colors.glassBorder : colors.glassBorder,
                  }]}
                  activeOpacity={0.7}
                  onPress={() => {
                    router.back();
                    setTimeout(() => {
                      router.push(`/(tabs)/report/${report.id}`);
                    }, 100);
                  }}
                >
                  <View style={styles.resultContent}>
                    <Text style={[styles.resultDate, { color: colors.primary }]}>
                      {formatDate(report.report_date)}
                    </Text>
                    <Text style={[styles.resultTitle, { color: colors.onSurface }]} numberOfLines={2}>
                      {report.title}
                    </Text>
                    {report.summary && (
                      <Text style={[styles.resultSummary, { color: colors.onSurfaceVariant }]} numberOfLines={2}>
                        {report.summary}
                      </Text>
                    )}
                    <View style={styles.resultMeta}>
                      {report.podcast_status === 'ready' && (
                        <View style={[styles.metaBadge, { backgroundColor: colors.primary + '20' }]}>
                          <MaterialCommunityIcons name="podcast" size={12} color={colors.primary} />
                          <Text style={[styles.metaText, { color: colors.primary }]}>播客</Text>
                        </View>
                      )}
                      {report.news_count > 0 && (
                        <View style={[styles.metaBadge, { backgroundColor: colors.outline + '20' }]}>
                          <MaterialCommunityIcons name="newspaper" size={12} color={colors.onSurfaceVariant} />
                          <Text style={[styles.metaText, { color: colors.onSurfaceVariant }]}>{report.news_count}条</Text>
                        </View>
                      )}
                    </View>
                  </View>
                  <MaterialCommunityIcons name="chevron-right" size={20} color={colors.onSurfaceVariant} />
                </TouchableOpacity>
              ))}
            </>
          )}

          {/* 底部安全区 */}
          <View style={{ height: 100 }} />
        </ScrollView>
      </SafeAreaView>
    </View>
  );
}

function createStyles(colors: any, isDark: boolean) {
  return StyleSheet.create({
    container: {
      flex: 1,
      backgroundColor: colors.background,
    },
    safeArea: {
      flex: 1,
    },
    searchHeader: {
      flexDirection: 'row',
      alignItems: 'center',
      paddingHorizontal: 16,
      paddingVertical: 12,
      gap: 12,
    },
    backButton: {
      padding: 4,
    },
    searchInputContainer: {
      flex: 1,
      flexDirection: 'row',
      alignItems: 'center',
      paddingHorizontal: 14,
      paddingVertical: 10,
      borderRadius: 16,
      borderWidth: 1,
      gap: 10,
    },
    searchInput: {
      flex: 1,
      fontSize: 16,
      paddingVertical: 0,
      ...Platform.select({
        web: {
          outlineStyle: 'none',
        },
      }),
    },
    scrollView: {
      flex: 1,
    },
    scrollContent: {
      paddingHorizontal: 20,
    },
    loadingContainer: {
      paddingVertical: 60,
      alignItems: 'center',
    },
    emptyState: {
      alignItems: 'center',
      paddingVertical: 80,
      gap: 12,
    },
    emptyTitle: {
      fontSize: 18,
      fontWeight: '600',
    },
    emptySubtitle: {
      fontSize: 14,
    },
    resultCount: {
      fontSize: 13,
      fontWeight: '500',
      marginBottom: 16,
      marginTop: 8,
    },
    resultItem: {
      flexDirection: 'row',
      alignItems: 'center',
      padding: 16,
      borderRadius: 16,
      borderWidth: StyleSheet.hairlineWidth,
      marginBottom: 12,
    },
    resultContent: {
      flex: 1,
      gap: 4,
    },
    resultDate: {
      fontSize: 11,
      fontWeight: '700',
      letterSpacing: 0.5,
    },
    resultTitle: {
      fontSize: 16,
      fontWeight: '600',
      lineHeight: 22,
    },
    resultSummary: {
      fontSize: 13,
      lineHeight: 18,
      marginTop: 4,
    },
    resultMeta: {
      flexDirection: 'row',
      gap: 8,
      marginTop: 8,
    },
    metaBadge: {
      flexDirection: 'row',
      alignItems: 'center',
      paddingHorizontal: 8,
      paddingVertical: 3,
      borderRadius: 8,
      gap: 4,
    },
    metaText: {
      fontSize: 11,
      fontWeight: '500',
    },
  });
}
