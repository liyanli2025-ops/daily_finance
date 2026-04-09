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
  Modal,
  TextInput,
  FlatList,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import { router } from 'expo-router';
import { useStockStore } from '@/stores/stockStore';
import { api } from '@/services/api';
import { useAppTheme } from '@/theme/ThemeContext';

const { width: SCREEN_WIDTH } = Dimensions.get('window');
const isIOSWeb = Platform.OS === 'web' && typeof navigator !== 'undefined' && /iPhone|iPad/.test(navigator.userAgent);
const TAB_BAR_HEIGHT = Platform.OS === 'ios' ? 88 : isIOSWeb ? 72 : 64;
const MINI_PLAYER_HEIGHT = 76;

interface MarketIndex {
  code: string;
  name: string;
  current: number;
  change: number;
  change_pct: number;
  volume: number;
  amount: number;
  high: number;
  low: number;
  open: number;
}

export default function StocksScreen() {
  const { colors, isDark } = useAppTheme();
  const {
    watchlist,
    searchResults,
    isLoading,
    isSearching,
    fetchWatchlist,
    searchStocks,
    addToWatchlist,
    removeFromWatchlist,
  } = useStockStore();

  const [searchVisible, setSearchVisible] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [refreshing, setRefreshing] = useState(false);
  const [indices, setIndices] = useState<MarketIndex[]>([]);
  const [indicesLoading, setIndicesLoading] = useState(true);
  const [indicesError, setIndicesError] = useState<string | null>(null);
  const [isPredicting, setIsPredicting] = useState(false);
  const [snackbarVisible, setSnackbarVisible] = useState(false);
  const [snackbarMessage, setSnackbarMessage] = useState('');

  const handleAIPrediction = async () => {
    setIsPredicting(true);
    try {
      const result = await api.generateWatchlistPredictions();
      if (result.status === 'success') {
        setSnackbarMessage(`✅ ${result.message}`);
        await fetchWatchlist();
      } else {
        setSnackbarMessage(`❌ ${result.message || '预测失败'}`);
      }
    } catch (error: any) {
      console.error('AI 预测失败:', error);
      setSnackbarMessage(`❌ AI 预测失败: ${error.message || '请稍后重试'}`);
    } finally {
      setIsPredicting(false);
      setSnackbarVisible(true);
      setTimeout(() => setSnackbarVisible(false), 3000);
    }
  };

  const fetchIndices = async () => {
    try {
      setIndicesLoading(true);
      setIndicesError(null);
      const res = await api.getMarketIndices();
      if (res.status === 'success' && res.data.length > 0) {
        setIndices(res.data);
      } else if (res.status === 'error') {
        setIndicesError(res.message || '获取失败');
      } else {
        setIndicesError('暂无数据');
      }
    } catch (e: any) {
      console.error('获取指数数据失败', e);
      setIndicesError('网络请求失败，请下拉刷新重试');
    } finally {
      setIndicesLoading(false);
    }
  };

  useEffect(() => {
    fetchWatchlist();
    fetchIndices();
    const interval = setInterval(() => {
      const now = new Date();
      const hour = now.getHours();
      const minute = now.getMinutes();
      if ((hour === 9 && minute >= 15) || (hour > 9 && hour < 15) || (hour === 15 && minute <= 5)) {
        fetchWatchlist();
        fetchIndices();
      }
    }, 30000);
    return () => clearInterval(interval);
  }, []);

  const onRefresh = async () => {
    setRefreshing(true);
    try {
      await api.refreshWatchlist();
    } catch (e) {
      console.log('刷新行情失败，继续获取列表');
    }
    await Promise.all([fetchWatchlist(), fetchIndices()]);
    setRefreshing(false);
  };

  const handleSearch = async (query: string) => {
    setSearchQuery(query);
    if (query.length >= 1) {
      await searchStocks(query);
    }
  };

  const handleAddStock = async (stock: { code: string; name: string; market: string }) => {
    await addToWatchlist(stock);
    setSearchVisible(false);
    setSearchQuery('');
  };

  const getPredictionColor = (prediction?: string) => {
    switch (prediction) {
      case 'bullish': return '#F44336';
      case 'bearish': return '#4CAF50';
      default: return colors.onSurfaceVariant;
    }
  };

  const getPredictionText = (prediction?: string) => {
    switch (prediction) {
      case 'bullish': return '看多';
      case 'bearish': return '看空';
      default: return '中性';
    }
  };

  const styles = createStyles(colors, isDark);

  return (
    <View style={styles.container}>
      {/* 氛围背景 */}
      <View style={styles.atmosphereContainer} pointerEvents="none">
        <View style={[styles.blob, styles.blobPrimary]} />
        <View style={[styles.blob, styles.blobSecondary]} />
      </View>

      {/* 顶部导航 */}
      <SafeAreaView edges={['top']} style={styles.headerSafe}>
        <View style={styles.header}>
          <Text style={[styles.headerTitle, { color: colors.onSurface }]}>股票</Text>
          <View style={styles.headerRight}>
            <TouchableOpacity
              style={styles.headerButton}
              onPress={() => setSearchVisible(true)}
            >
              <MaterialCommunityIcons name="magnify" size={22} color={colors.onSurfaceVariant} />
            </TouchableOpacity>
            <TouchableOpacity
              style={[styles.addButton, { backgroundColor: colors.primary }]}
              onPress={() => setSearchVisible(true)}
            >
              <MaterialCommunityIcons name="plus" size={18} color="#fff" />
            </TouchableOpacity>
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
        {/* 市场概览 */}
        <View style={styles.sectionHeader}>
          <Text style={[styles.sectionTitle, { color: colors.onSurface }]}>市场概览</Text>
          <Text style={[styles.sectionSubtitle, { color: colors.onSurfaceVariant }]}>实时指数行情</Text>
        </View>

        <View style={styles.indexGrid}>
          {indicesLoading ? (
            <View style={styles.indicesLoadingContainer}>
              <ActivityIndicator size="small" color={colors.primary} />
              <Text style={[styles.loadingHint, { color: colors.onSurfaceVariant }]}>加载指数数据...</Text>
            </View>
          ) : indices.length > 0 ? (
            indices.slice(0, 5).map((idx) => (
              <View
                key={idx.code}
                style={[styles.indexCard, {
                  backgroundColor: isDark ? colors.glassBackground : colors.glassBackground,
                  borderColor: isDark ? colors.glassBorder : colors.glassBorder,
                }]}
              >
                <Text style={[styles.indexName, { color: colors.onSurfaceVariant }]} numberOfLines={1}>
                  {idx.name}
                </Text>
                <Text style={[styles.indexValue, { color: colors.onSurface }]}>
                  {idx.current.toFixed(2)}
                </Text>
                <Text style={[styles.indexChange, { color: idx.change_pct >= 0 ? '#F44336' : '#4CAF50' }]}>
                  {idx.change_pct >= 0 ? '+' : ''}{idx.change_pct.toFixed(2)}%
                </Text>
              </View>
            ))
          ) : (
            <View style={styles.indicesErrorContainer}>
              <MaterialCommunityIcons name="chart-line" size={32} color={colors.onSurfaceVariant} />
              <Text style={[styles.errorText, { color: colors.onSurfaceVariant }]}>{indicesError || '暂无指数数据'}</Text>
              <TouchableOpacity onPress={fetchIndices} style={[styles.retryButton, { borderColor: colors.primary }]}>
                <Text style={[styles.retryText, { color: colors.primary }]}>点击重试</Text>
              </TouchableOpacity>
            </View>
          )}
        </View>

        {/* 自选股列表 */}
        <View style={styles.watchlistHeader}>
          <View>
            <Text style={[styles.sectionTitle, { color: colors.onSurface }]}>我的自选</Text>
            <Text style={[styles.sectionSubtitle, { color: colors.onSurfaceVariant }]}>{watchlist.length} 只股票</Text>
          </View>
          {watchlist.length > 0 && (
            <TouchableOpacity
              style={[styles.aiButton, {
                backgroundColor: isPredicting
                  ? (isDark ? 'rgba(182,160,255,0.15)' : 'rgba(124,77,255,0.1)')
                  : (isDark ? 'rgba(182,160,255,0.1)' : 'rgba(124,77,255,0.08)'),
                borderColor: isDark ? 'rgba(182,160,255,0.2)' : 'rgba(124,77,255,0.15)',
              }]}
              onPress={handleAIPrediction}
              disabled={isPredicting}
              activeOpacity={0.7}
            >
              {isPredicting ? (
                <ActivityIndicator size={12} color={colors.primary} />
              ) : (
                <MaterialCommunityIcons name="robot-outline" size={14} color={colors.primary} />
              )}
              <Text style={[styles.aiButtonText, { color: colors.primary }]}>
                {isPredicting ? '分析中...' : 'AI 预测'}
              </Text>
            </TouchableOpacity>
          )}
        </View>

        {isLoading ? (
          <View style={styles.centerContainer}>
            <ActivityIndicator size="large" color={colors.primary} />
            <Text style={[styles.loadingHint, { color: colors.onSurfaceVariant, marginTop: 16 }]}>正在获取自选股...</Text>
          </View>
        ) : watchlist.length === 0 ? (
          <View style={[styles.emptyCard, {
            backgroundColor: isDark ? colors.glassBackground : colors.glassBackground,
            borderColor: isDark ? colors.glassBorder : colors.glassBorder,
          }]}>
            <MaterialCommunityIcons name="star-outline" size={48} color={colors.onSurfaceVariant} />
            <Text style={[styles.emptyTitle, { color: colors.onSurfaceVariant }]}>暂无自选股</Text>
            <Text style={[styles.emptySubtitle, { color: colors.outline }]}>添加股票开始跟踪行情</Text>
            <TouchableOpacity
              style={[styles.emptyAddButton, { backgroundColor: colors.primary }]}
              onPress={() => setSearchVisible(true)}
            >
              <MaterialCommunityIcons name="plus" size={16} color="#fff" />
              <Text style={styles.emptyAddText}>添加自选股</Text>
            </TouchableOpacity>
          </View>
        ) : (
          <View style={styles.stockList}>
            {watchlist.map((stock) => {
              const priceColor = (stock.change_percent ?? 0) >= 0 ? '#F44336' : '#4CAF50';
              const handleCardPress = () => {
                console.log('[Stocks] 点击自选股:', stock.code, stock.market);
                router.push({ pathname: '/stock/[code]', params: { code: stock.code, market: stock.market } });
              };
              const cardStyle = [styles.stockCard, {
                backgroundColor: isDark ? colors.glassBackground : colors.glassBackground,
                borderColor: isDark ? colors.glassBorder : colors.glassBorder,
              }];

              const cardContent = (
                <>
                  <View style={styles.stockMain}>
                    <View style={styles.stockInfo}>
                      <Text style={[styles.stockName, { color: colors.onSurface }]}>{stock.name}</Text>
                      <View style={styles.stockCodeRow}>
                        <Text style={[styles.stockCode, { color: colors.onSurfaceVariant }]}>{stock.code}</Text>
                        <View style={[styles.marketTag, {
                          backgroundColor: stock.market === 'A'
                            ? (isDark ? 'rgba(255,87,51,0.15)' : 'rgba(255,87,51,0.1)')
                            : (isDark ? 'rgba(33,150,243,0.15)' : 'rgba(33,150,243,0.1)')
                        }]}>
                          <Text style={[styles.marketTagText, {
                            color: stock.market === 'A' ? '#FF5733' : '#2196F3'
                          }]}>
                            {stock.market === 'A' ? 'A股' : '港股'}
                          </Text>
                        </View>
                      </View>
                    </View>
                    <View style={styles.stockPrice}>
                      <Text style={[styles.priceValue, { color: priceColor }]}>
                        {stock.current_price != null ? stock.current_price.toFixed(2) : '--'}
                      </Text>
                      <Text style={[styles.priceChange, { color: priceColor }]}>
                        {stock.change_percent != null
                          ? `${stock.change_percent >= 0 ? '+' : ''}${stock.change_percent.toFixed(2)}%`
                          : '--'}
                      </Text>
                    </View>
                  </View>

                  {/* AI 预测行 */}
                  <View style={[styles.predictionRow, { borderTopColor: isDark ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.05)' }]}>
                    <View style={styles.predictionInfo}>
                      <MaterialCommunityIcons
                        name="robot-outline"
                        size={14}
                        color={getPredictionColor(stock.latest_prediction)}
                      />
                      <Text style={[styles.predictionText, { color: getPredictionColor(stock.latest_prediction) }]}>
                        AI预测: {getPredictionText(stock.latest_prediction)}
                      </Text>
                      {stock.latest_confidence !== undefined && (
                        <Text style={[styles.confidenceText, { color: colors.onSurfaceVariant }]}>
                          置信度 {Math.round(stock.latest_confidence * 100)}%
                        </Text>
                      )}
                    </View>
                    <TouchableOpacity
                      onPress={(e) => {
                        e.stopPropagation();
                        removeFromWatchlist(stock.id);
                      }}
                      hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }}
                      activeOpacity={0.5}
                    >
                      <MaterialCommunityIcons name="close" size={16} color={colors.onSurfaceVariant} />
                    </TouchableOpacity>
                  </View>
                </>
              );

              // Web 平台用原生 div onClick 确保点击一定能触发
              if (Platform.OS === 'web') {
                return (
                  <div
                    key={stock.id}
                    onClick={handleCardPress}
                    style={{ cursor: 'pointer' }}
                  >
                    <View style={cardStyle}>
                      {cardContent}
                    </View>
                  </div>
                );
              }

              return (
                <TouchableOpacity
                  key={stock.id}
                  activeOpacity={0.7}
                  onPress={handleCardPress}
                  style={cardStyle}
                >
                  {cardContent}
                </TouchableOpacity>
              );
            })}
          </View>
        )}

        {/* 底部安全区域 - 给 tab 栏 + MiniPlayer 留空间 */}
        <View style={{ height: 160 }} />
      </ScrollView>

      {/* 搜索股票弹窗 */}
      <Modal
        visible={searchVisible}
        transparent
        animationType="slide"
        onRequestClose={() => setSearchVisible(false)}
      >
        <TouchableOpacity
          style={styles.modalOverlay}
          activeOpacity={1}
          onPress={() => { setSearchVisible(false); setSearchQuery(''); }}
        >
          <TouchableOpacity activeOpacity={1} style={[styles.modalSheet, {
            backgroundColor: isDark ? colors.surfaceContainer : colors.surface,
          }]}>
            {/* 拖拽指示条 */}
            <View style={styles.modalHandle}>
              <View style={[styles.handleBar, { backgroundColor: isDark ? 'rgba(255,255,255,0.2)' : 'rgba(0,0,0,0.15)' }]} />
            </View>

            <View style={styles.modalHeader}>
              <Text style={[styles.modalTitle, { color: colors.onSurface }]}>添加自选股</Text>
              <TouchableOpacity onPress={() => { setSearchVisible(false); setSearchQuery(''); }}>
                <MaterialCommunityIcons name="close" size={22} color={colors.onSurfaceVariant} />
              </TouchableOpacity>
            </View>

            {/* 搜索栏 */}
            <View style={[styles.searchBar, {
              backgroundColor: isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.04)',
              borderColor: isDark ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.08)',
            }]}>
              <MaterialCommunityIcons name="magnify" size={18} color={colors.onSurfaceVariant} />
              <TextInput
                style={[styles.searchInput, { color: colors.onSurface }]}
                placeholder="输入股票代码或名称"
                placeholderTextColor={colors.onSurfaceVariant}
                value={searchQuery}
                onChangeText={handleSearch}
                autoFocus
              />
              {searchQuery.length > 0 && (
                <TouchableOpacity onPress={() => { setSearchQuery(''); }}>
                  <MaterialCommunityIcons name="close-circle" size={16} color={colors.onSurfaceVariant} />
                </TouchableOpacity>
              )}
            </View>

            {/* 快捷标签 */}
            <View style={styles.quickTags}>
              {['茅台', '腾讯', '比亚迪', '宁德时代', '小米', '阿里'].map((name) => (
                <TouchableOpacity
                  key={name}
                  style={[styles.quickTag, {
                    backgroundColor: isDark ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.04)',
                    borderColor: isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.06)',
                  }]}
                  onPress={() => handleSearch(name)}
                >
                  <Text style={[styles.quickTagText, { color: colors.onSurfaceVariant }]}>{name}</Text>
                </TouchableOpacity>
              ))}
            </View>

            {/* 搜索结果 */}
            <ScrollView style={styles.searchResults} showsVerticalScrollIndicator={false}>
              {isSearching ? (
                <View style={styles.searchCenter}>
                  <ActivityIndicator size="small" color={colors.primary} />
                  <Text style={[styles.searchHint, { color: colors.onSurfaceVariant }]}>正在搜索...</Text>
                </View>
              ) : searchQuery.length > 0 && searchResults.length === 0 ? (
                <View style={styles.searchCenter}>
                  <Text style={[styles.searchHint, { color: colors.onSurfaceVariant }]}>未找到"{searchQuery}"</Text>
                </View>
              ) : searchResults.length > 0 ? (
                <>
                  <Text style={[styles.searchResultHint, { color: colors.onSurfaceVariant }]}>点击添加到自选 ↓</Text>
                  {searchResults.map((result, index) => (
                    <TouchableOpacity
                      key={index}
                      style={[styles.searchResultItem, {
                        backgroundColor: isDark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.02)',
                      }]}
                      onPress={() => handleAddStock(result)}
                    >
                      <View>
                        <Text style={[styles.searchResultName, { color: colors.onSurface }]}>{result.name}</Text>
                        <Text style={[styles.searchResultCode, { color: colors.onSurfaceVariant }]}>
                          {result.code} · {result.market === 'A' ? 'A股' : '港股'}
                        </Text>
                      </View>
                      <MaterialCommunityIcons name="plus-circle" size={22} color={colors.primary} />
                    </TouchableOpacity>
                  ))}
                </>
              ) : null}
            </ScrollView>
          </TouchableOpacity>
        </TouchableOpacity>
      </Modal>

      {/* 消息提示 */}
      {snackbarVisible && (
        <View style={[styles.snackbar, {
          backgroundColor: isDark ? colors.surfaceContainerHigh : '#323232',
          bottom: TAB_BAR_HEIGHT + MINI_PLAYER_HEIGHT + 8,
        }]}>
          <Text style={styles.snackbarText}>{snackbarMessage}</Text>
        </View>
      )}
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
      width: SCREEN_WIDTH * 0.5,
      height: SCREEN_WIDTH * 0.5,
      top: -SCREEN_WIDTH * 0.1,
      right: -SCREEN_WIDTH * 0.1,
      backgroundColor: isDark ? 'rgba(182,160,255,0.05)' : 'rgba(124,77,255,0.05)',
    },
    blobSecondary: {
      width: SCREEN_WIDTH * 0.4,
      height: SCREEN_WIDTH * 0.4,
      bottom: '30%',
      left: -SCREEN_WIDTH * 0.08,
      backgroundColor: isDark ? 'rgba(51,103,255,0.04)' : 'rgba(124,77,255,0.03)',
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
    headerTitle: { fontSize: 28, fontWeight: '800', letterSpacing: -0.5 },
    headerRight: { flexDirection: 'row', alignItems: 'center', gap: 12 },
    headerButton: { padding: 4 },
    addButton: {
      width: 30,
      height: 30,
      borderRadius: 15,
      alignItems: 'center',
      justifyContent: 'center',
    },

    scrollView: { flex: 1, zIndex: 10 },
    scrollContent: { paddingHorizontal: 24 },

    // Section
    sectionHeader: { marginBottom: 12, marginTop: 4 },
    sectionTitle: { fontSize: 22, fontWeight: '800', letterSpacing: -0.3 },
    sectionSubtitle: { fontSize: 13, fontWeight: '500', marginTop: 2 },

    // Index cards
    indexGrid: {
      flexDirection: 'row',
      flexWrap: 'wrap',
      gap: 8,
      marginBottom: 24,
    },
    indexCard: {
      minWidth: '30%',
      flex: 1,
      padding: 12,
      borderRadius: 14,
      borderWidth: StyleSheet.hairlineWidth,
    },
    indexName: { fontSize: 11, fontWeight: '500', marginBottom: 4 },
    indexValue: { fontSize: 16, fontWeight: '700' },
    indexChange: { fontSize: 12, fontWeight: '600', marginTop: 2 },
    indicesLoadingContainer: {
      flex: 1,
      alignItems: 'center',
      justifyContent: 'center',
      paddingVertical: 20,
    },
    indicesErrorContainer: {
      flex: 1,
      alignItems: 'center',
      justifyContent: 'center',
      paddingVertical: 16,
    },
    errorText: { fontSize: 13, marginTop: 8, textAlign: 'center' },
    retryButton: {
      marginTop: 8,
      paddingHorizontal: 14,
      paddingVertical: 6,
      borderRadius: 12,
      borderWidth: 1,
    },
    retryText: { fontSize: 12, fontWeight: '600' },
    loadingHint: { fontSize: 13, marginTop: 8 },

    // Watchlist header
    watchlistHeader: {
      flexDirection: 'row',
      justifyContent: 'space-between',
      alignItems: 'center',
      marginBottom: 14,
    },

    // AI Button — 统一风格
    aiButton: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 5,
      paddingHorizontal: 12,
      paddingVertical: 7,
      borderRadius: 999,
      borderWidth: 1,
    },
    aiButtonText: {
      fontSize: 11,
      fontWeight: '700',
      letterSpacing: 0.3,
    },

    // Center loading/empty
    centerContainer: {
      alignItems: 'center',
      paddingVertical: 60,
    },

    // Empty state
    emptyCard: {
      borderRadius: 20,
      borderWidth: StyleSheet.hairlineWidth,
      padding: 40,
      alignItems: 'center',
    },
    emptyTitle: { fontSize: 16, fontWeight: '600', marginTop: 16 },
    emptySubtitle: { fontSize: 13, marginTop: 6 },
    emptyAddButton: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 6,
      marginTop: 20,
      paddingHorizontal: 20,
      paddingVertical: 10,
      borderRadius: 999,
    },
    emptyAddText: { fontSize: 14, fontWeight: '600', color: '#fff' },

    // Stock list
    stockList: { gap: 10 },
    stockCard: {
      borderRadius: 16,
      borderWidth: StyleSheet.hairlineWidth,
      overflow: 'hidden',
      padding: 16,
    },
    stockMain: {
      flexDirection: 'row',
      justifyContent: 'space-between',
      alignItems: 'flex-start',
    },
    stockInfo: { flex: 1 },
    stockName: { fontSize: 16, fontWeight: '700' },
    stockCodeRow: { flexDirection: 'row', alignItems: 'center', gap: 8, marginTop: 4 },
    stockCode: { fontSize: 12, fontWeight: '500' },
    marketTag: {
      paddingHorizontal: 7,
      paddingVertical: 2,
      borderRadius: 6,
    },
    marketTagText: { fontSize: 10, fontWeight: '700' },
    stockPrice: { alignItems: 'flex-end' },
    priceValue: { fontSize: 22, fontWeight: '700' },
    priceChange: { fontSize: 13, fontWeight: '600', marginTop: 2 },

    // Prediction row
    predictionRow: {
      flexDirection: 'row',
      justifyContent: 'space-between',
      alignItems: 'center',
      marginTop: 12,
      paddingTop: 12,
      borderTopWidth: StyleSheet.hairlineWidth,
    },
    predictionInfo: { flexDirection: 'row', alignItems: 'center', gap: 4 },
    predictionText: { fontSize: 12, fontWeight: '500' },
    confidenceText: { fontSize: 12, marginLeft: 6 },

    // Modal (search)
    modalOverlay: {
      flex: 1,
      justifyContent: 'flex-end',
      backgroundColor: 'rgba(0,0,0,0.4)',
    },
    modalSheet: {
      maxHeight: '80%',
      borderTopLeftRadius: 24,
      borderTopRightRadius: 24,
      paddingBottom: Platform.OS === 'ios' ? 34 : 20,
      ...Platform.select({
        ios: {
          shadowColor: '#000',
          shadowOffset: { width: 0, height: -8 },
          shadowOpacity: 0.25,
          shadowRadius: 24,
        },
        android: { elevation: 24 },
      }),
    },
    modalHandle: {
      alignItems: 'center',
      paddingVertical: 12,
    },
    handleBar: {
      width: 36,
      height: 4,
      borderRadius: 2,
    },
    modalHeader: {
      flexDirection: 'row',
      justifyContent: 'space-between',
      alignItems: 'center',
      paddingHorizontal: 24,
      paddingBottom: 16,
    },
    modalTitle: { fontSize: 18, fontWeight: '700' },

    // Search bar
    searchBar: {
      flexDirection: 'row',
      alignItems: 'center',
      marginHorizontal: 24,
      paddingHorizontal: 14,
      paddingVertical: 10,
      borderRadius: 14,
      borderWidth: 1,
      gap: 8,
      marginBottom: 12,
    },
    searchInput: {
      flex: 1,
      fontSize: 15,
      padding: 0,
    },

    // Quick tags
    quickTags: {
      flexDirection: 'row',
      flexWrap: 'wrap',
      gap: 8,
      paddingHorizontal: 24,
      marginBottom: 16,
    },
    quickTag: {
      paddingHorizontal: 12,
      paddingVertical: 6,
      borderRadius: 999,
      borderWidth: StyleSheet.hairlineWidth,
    },
    quickTagText: { fontSize: 12, fontWeight: '500' },

    // Search results
    searchResults: {
      maxHeight: 300,
      paddingHorizontal: 24,
    },
    searchCenter: {
      alignItems: 'center',
      paddingVertical: 20,
    },
    searchHint: { fontSize: 13, marginTop: 8 },
    searchResultHint: { fontSize: 12, marginBottom: 8 },
    searchResultItem: {
      flexDirection: 'row',
      justifyContent: 'space-between',
      alignItems: 'center',
      padding: 14,
      borderRadius: 12,
      marginBottom: 6,
    },
    searchResultName: { fontSize: 15, fontWeight: '600' },
    searchResultCode: { fontSize: 12, marginTop: 2 },

    // Snackbar
    snackbar: {
      position: 'absolute',
      left: 24,
      right: 24,
      paddingHorizontal: 16,
      paddingVertical: 12,
      borderRadius: 12,
      zIndex: 999,
    },
    snackbarText: { color: '#fff', fontSize: 13, fontWeight: '500' },
  });
}
