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
import { useLocalSearchParams, router } from 'expo-router';
import ChartView from '@/components/ChartView';
import MiniPlayer from '@/components/MiniPlayer';
import { useStockStore } from '@/stores/stockStore';
import { useAudioStore } from '@/stores/audioStore';
import { useAppTheme } from '@/theme/ThemeContext';
import { api } from '@/services/api';

const { width: SCREEN_WIDTH } = Dimensions.get('window');
const isIOSWeb = Platform.OS === 'web' && typeof navigator !== 'undefined' && /iPhone|iPad/.test(navigator.userAgent);
const TAB_BAR_HEIGHT = Platform.OS === 'ios' ? 88 : isIOSWeb ? 72 : 64;
const MINI_PLAYER_HEIGHT = 76;

interface StockDetail {
  code: string;
  name: string;
  market: string;
  current_price: number;
  change: number;
  change_percent: number;
  open_price: number;
  high_price: number;
  low_price: number;
  prev_close: number;
  volume: number;
  amount: number;
  pe_ratio?: number;
  pb_ratio?: number;
  market_cap?: number;
  update_time?: string;
  prediction?: {
    signal: 'bullish' | 'neutral' | 'bearish';
    confidence: number;
    reasoning: string;
    target_price?: number;
    stop_loss?: number;
  };
}

export default function StockDetailScreen() {
  const { colors, isDark } = useAppTheme();
  const { code, market } = useLocalSearchParams<{ code: string; market: string }>();
  const { watchlist, addToWatchlist, removeFromWatchlist } = useStockStore();
  const currentReportId = useAudioStore((state) => state.currentReportId);

  const [stock, setStock] = useState<StockDetail | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [isAnalyzing, setIsAnalyzing] = useState(false);

  const isInWatchlist = watchlist.some((s) => s.code === code && s.market === market);
  const showMiniPlayer = !!currentReportId;

  useEffect(() => {
    fetchStockDetail();
  }, [code, market]);

  const fetchStockDetail = async () => {
    setIsLoading(true);
    try {
      const quoteData = await api.getStockQuote(code!, market!);
      let prediction = undefined;
      try {
        const predData = await api.getStockPrediction(code!, market!);
        if (predData && predData.prediction) {
          prediction = {
            signal: predData.prediction as 'bullish' | 'neutral' | 'bearish',
            confidence: predData.confidence || 0.5,
            reasoning: predData.reasoning || '暂无分析数据',
            target_price: predData.target_price,
            stop_loss: predData.stop_loss,
          };
        }
      } catch (e) {
        console.log('获取 AI 预测失败，跳过:', e);
      }

      setStock({
        code: quoteData.code,
        name: quoteData.name,
        market: market || 'A',
        current_price: quoteData.current_price,
        change: quoteData.change,
        change_percent: quoteData.change_percent,
        open_price: quoteData.open_price,
        high_price: quoteData.high_price,
        low_price: quoteData.low_price,
        prev_close: quoteData.prev_close,
        volume: quoteData.volume,
        amount: quoteData.amount,
        pe_ratio: quoteData.pe_ratio,
        pb_ratio: quoteData.pb_ratio,
        market_cap: quoteData.market_cap,
        update_time: quoteData.update_time,
        prediction,
      });
    } catch (error) {
      console.error('获取股票详情失败:', error);
      setStock(null);
    }
    setIsLoading(false);
  };

  const onRefresh = async () => {
    setRefreshing(true);
    await fetchStockDetail();
    setRefreshing(false);
  };

  const handleToggleWatchlist = async () => {
    if (isInWatchlist) {
      const watchItem = watchlist.find((s) => s.code === code);
      if (watchItem) {
        await removeFromWatchlist(watchItem.id);
      }
    } else if (stock) {
      await addToWatchlist({
        code: stock.code,
        name: stock.name,
        market: stock.market,
      });
    }
  };

  const handleAnalyze = async () => {
    setIsAnalyzing(true);
    try {
      await api.triggerStockAnalysis(code!, market!);
      await fetchStockDetail();
    } catch (error) {
      console.error('分析失败:', error);
    }
    setIsAnalyzing(false);
  };

  const formatNumber = (num: number) => {
    if (num >= 100000000) return `${(num / 100000000).toFixed(2)}亿`;
    if (num >= 10000) return `${(num / 10000).toFixed(2)}万`;
    return num.toFixed(2);
  };

  const getPredictionColor = (signal?: string) => {
    switch (signal) {
      case 'bullish': return colors.bullish || '#22C55E';
      case 'bearish': return colors.bearish || '#EF4444';
      default: return colors.onSurfaceVariant;
    }
  };

  const getPredictionLabel = (signal?: string) => {
    switch (signal) {
      case 'bullish': return '看多';
      case 'bearish': return '看空';
      default: return '中性';
    }
  };

  const styles = createStyles(colors, isDark);

  if (isLoading) {
    return (
      <View style={styles.container}>
        <View style={styles.atmosphereContainer} pointerEvents="none">
          <View style={[styles.blob, styles.blobPrimary]} />
          <View style={[styles.blob, styles.blobSecondary]} />
        </View>
        <SafeAreaView edges={['top']} style={styles.headerSafe}>
          <View style={styles.navBar}>
            <TouchableOpacity style={styles.backButton} onPress={() => router.back()}>
              <MaterialCommunityIcons name="chevron-left" size={28} color={colors.onSurface} />
            </TouchableOpacity>
            <Text style={[styles.navTitle, { color: colors.onSurface }]}>股票详情</Text>
            <View style={{ width: 40 }} />
          </View>
        </SafeAreaView>
        <View style={styles.loadingContainer}>
          <ActivityIndicator size="large" color={colors.primary} />
          <Text style={[styles.loadingText, { color: colors.onSurfaceVariant }]}>正在加载股票数据...</Text>
        </View>
      </View>
    );
  }

  if (!stock) {
    return (
      <View style={styles.container}>
        <View style={styles.atmosphereContainer} pointerEvents="none">
          <View style={[styles.blob, styles.blobPrimary]} />
          <View style={[styles.blob, styles.blobSecondary]} />
        </View>
        <SafeAreaView edges={['top']} style={styles.headerSafe}>
          <View style={styles.navBar}>
            <TouchableOpacity style={styles.backButton} onPress={() => router.back()}>
              <MaterialCommunityIcons name="chevron-left" size={28} color={colors.onSurface} />
            </TouchableOpacity>
            <Text style={[styles.navTitle, { color: colors.onSurface }]}>股票详情</Text>
            <View style={{ width: 40 }} />
          </View>
        </SafeAreaView>
        <View style={styles.loadingContainer}>
          <MaterialCommunityIcons name="chart-line" size={64} color={colors.onSurfaceVariant} />
          <Text style={[styles.emptyTitle, { color: colors.onSurfaceVariant }]}>股票数据加载失败</Text>
        </View>
      </View>
    );
  }

  const priceColor = stock.change_percent >= 0 ? (colors.bearish || '#EF4444') : (colors.bullish || '#22C55E');

  return (
    <View style={styles.container}>
      {/* 氛围背景 */}
      <View style={styles.atmosphereContainer} pointerEvents="none">
        <View style={[styles.blob, styles.blobPrimary]} />
        <View style={[styles.blob, styles.blobSecondary]} />
      </View>

      {/* 顶部导航栏 */}
      <SafeAreaView edges={['top']} style={styles.headerSafe}>
        <View style={styles.navBar}>
          <TouchableOpacity style={styles.backButton} onPress={() => router.back()}>
            <MaterialCommunityIcons name="chevron-left" size={28} color={colors.onSurface} />
          </TouchableOpacity>
          <Text style={[styles.navTitle, { color: colors.onSurface }]}>{stock.name}</Text>
          <TouchableOpacity style={styles.starButton} onPress={handleToggleWatchlist}>
            <MaterialCommunityIcons
              name={isInWatchlist ? 'star' : 'star-outline'}
              size={24}
              color={isInWatchlist ? '#F59E0B' : colors.onSurfaceVariant}
            />
          </TouchableOpacity>
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
        {/* 股票头部 */}
        <View style={styles.stockHeader}>
          <View style={styles.codeRow}>
            <Text style={[styles.stockCode, { color: colors.onSurfaceVariant }]}>{stock.code}</Text>
            <View style={[styles.marketBadge, {
              backgroundColor: stock.market === 'A'
                ? (isDark ? 'rgba(239,68,68,0.15)' : 'rgba(239,68,68,0.1)')
                : (isDark ? 'rgba(33,150,243,0.15)' : 'rgba(33,150,243,0.1)'),
            }]}>
              <Text style={[styles.marketBadgeText, {
                color: stock.market === 'A' ? '#EF4444' : '#2196F3',
              }]}>
                {stock.market === 'A' ? 'A股' : '港股'}
              </Text>
            </View>
          </View>
        </View>

        {/* 价格卡片 */}
        <View style={[styles.glassCard, {
          backgroundColor: isDark ? colors.glassBackground : colors.glassBackground,
          borderColor: isDark ? colors.glassBorder : colors.glassBorder,
        }]}>
          <View style={styles.priceRow}>
            <Text style={[styles.currentPrice, { color: priceColor }]}>
              {stock.current_price.toFixed(2)}
            </Text>
            <View style={styles.changeInfo}>
              <Text style={[styles.changeText, { color: priceColor }]}>
                {stock.change >= 0 ? '+' : ''}{stock.change.toFixed(2)}
              </Text>
              <Text style={[styles.changePct, { color: priceColor }]}>
                {stock.change_percent >= 0 ? '+' : ''}{stock.change_percent.toFixed(2)}%
              </Text>
            </View>
          </View>

          <View style={[styles.divider, { backgroundColor: isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)' }]} />

          <View style={styles.detailGrid}>
            {[
              { label: '今开', value: stock.open_price.toFixed(2) },
              { label: '最高', value: stock.high_price.toFixed(2), color: colors.bearish || '#EF4444' },
              { label: '最低', value: stock.low_price.toFixed(2), color: colors.bullish || '#22C55E' },
              { label: '昨收', value: stock.prev_close.toFixed(2) },
              { label: '成交量', value: formatNumber(stock.volume) },
              { label: '成交额', value: formatNumber(stock.amount) },
            ].map((item, idx) => (
              <View key={idx} style={styles.detailItem}>
                <Text style={[styles.detailLabel, { color: colors.onSurfaceVariant }]}>{item.label}</Text>
                <Text style={[styles.detailValue, { color: item.color || colors.onSurface }]}>{item.value}</Text>
              </View>
            ))}
          </View>
        </View>

        {/* K线图 */}
        <ChartView stockCode={stock.code} stockName={stock.name} market={market || 'A'} />

        {/* 基本面数据 */}
        <View style={[styles.glassCard, {
          backgroundColor: isDark ? colors.glassBackground : colors.glassBackground,
          borderColor: isDark ? colors.glassBorder : colors.glassBorder,
        }]}>
          <Text style={[styles.sectionTitle, { color: colors.onSurface }]}>📊 基本面数据</Text>
          <View style={styles.fundamentalGrid}>
            {[
              { label: '市盈率(PE)', value: stock.pe_ratio?.toFixed(2) || '--' },
              { label: '市净率(PB)', value: stock.pb_ratio?.toFixed(2) || '--' },
              { label: '总市值', value: stock.market_cap ? formatNumber(stock.market_cap) : '--' },
            ].map((item, idx) => (
              <View key={idx} style={styles.fundamentalItem}>
                <Text style={[styles.fundamentalLabel, { color: colors.onSurfaceVariant }]}>{item.label}</Text>
                <Text style={[styles.fundamentalValue, { color: colors.onSurface }]}>{item.value}</Text>
              </View>
            ))}
          </View>
        </View>

        {/* AI 分析预测 */}
        <View style={[styles.glassCard, {
          backgroundColor: isDark ? colors.glassBackground : colors.glassBackground,
          borderColor: isDark ? colors.glassBorder : colors.glassBorder,
        }]}>
          <View style={styles.predictionHeader}>
            <Text style={[styles.sectionTitle, { color: colors.onSurface, marginBottom: 0 }]}>🤖 AI 分析预测</Text>
            <TouchableOpacity
              style={[styles.analyzeBtn, {
                backgroundColor: isDark ? 'rgba(182,160,255,0.12)' : 'rgba(124,77,255,0.08)',
                borderColor: isDark ? 'rgba(182,160,255,0.2)' : 'rgba(124,77,255,0.15)',
              }]}
              onPress={handleAnalyze}
              disabled={isAnalyzing}
            >
              {isAnalyzing ? (
                <ActivityIndicator size="small" color={colors.primary} />
              ) : (
                <>
                  <MaterialCommunityIcons name="refresh" size={14} color={colors.primary} />
                  <Text style={[styles.analyzeBtnText, { color: colors.primary }]}>重新分析</Text>
                </>
              )}
            </TouchableOpacity>
          </View>

          {stock.prediction ? (
            <View>
              <View style={styles.signalRow}>
                <View style={[styles.signalBadge, {
                  backgroundColor: getPredictionColor(stock.prediction.signal) + '15',
                }]}>
                  <Text style={[styles.signalText, { color: getPredictionColor(stock.prediction.signal) }]}>
                    {getPredictionLabel(stock.prediction.signal)}
                  </Text>
                </View>
                <Text style={[styles.confidenceText, { color: colors.onSurfaceVariant }]}>
                  置信度: {Math.round(stock.prediction.confidence * 100)}%
                </Text>
              </View>

              <Text style={[styles.reasoning, { color: colors.onSurface }]}>
                {stock.prediction.reasoning}
              </Text>

              {(stock.prediction.target_price || stock.prediction.stop_loss) && (
                <View style={[styles.priceTargets, {
                  borderTopColor: isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)',
                }]}>
                  {stock.prediction.target_price && (
                    <View style={styles.targetItem}>
                      <Text style={[styles.targetLabel, { color: colors.bullish || '#22C55E' }]}>目标价</Text>
                      <Text style={[styles.targetValue, { color: colors.bullish || '#22C55E' }]}>
                        {stock.prediction.target_price.toFixed(2)}
                      </Text>
                    </View>
                  )}
                  {stock.prediction.stop_loss && (
                    <View style={styles.targetItem}>
                      <Text style={[styles.targetLabel, { color: colors.bearish || '#EF4444' }]}>止损位</Text>
                      <Text style={[styles.targetValue, { color: colors.bearish || '#EF4444' }]}>
                        {stock.prediction.stop_loss.toFixed(2)}
                      </Text>
                    </View>
                  )}
                </View>
              )}
            </View>
          ) : (
            <View style={styles.noPrediction}>
              <MaterialCommunityIcons name="robot-outline" size={48} color={colors.onSurfaceVariant} />
              <Text style={[styles.noPredictionText, { color: colors.onSurfaceVariant }]}>暂无 AI 分析数据</Text>
              <TouchableOpacity
                style={[styles.analyzeMainBtn, { backgroundColor: colors.primary }]}
                onPress={handleAnalyze}
                disabled={isAnalyzing}
              >
                {isAnalyzing ? (
                  <ActivityIndicator size="small" color="#FFFFFF" />
                ) : (
                  <Text style={styles.analyzeMainBtnText}>立即分析</Text>
                )}
              </TouchableOpacity>
            </View>
          )}
        </View>

        {/* 底部安全区域 */}
        <View style={{ height: showMiniPlayer ? 120 : 60 }} />
      </ScrollView>

      {/* MiniPlayer 浮层 */}
      {showMiniPlayer && (
        <View style={styles.miniPlayerContainer}>
          <MiniPlayer />
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
      width: SCREEN_WIDTH * 0.65,
      height: SCREEN_WIDTH * 0.65,
      top: -SCREEN_WIDTH * 0.1,
      right: -SCREEN_WIDTH * 0.15,
      backgroundColor: isDark ? 'rgba(182,160,255,0.06)' : 'rgba(124,77,255,0.06)',
    },
    blobSecondary: {
      width: SCREEN_WIDTH * 0.5,
      height: SCREEN_WIDTH * 0.5,
      bottom: '30%',
      left: -SCREEN_WIDTH * 0.1,
      backgroundColor: isDark ? 'rgba(51,103,255,0.04)' : 'rgba(124,77,255,0.04)',
    },

    // 导航栏
    headerSafe: { zIndex: 50 },
    navBar: {
      flexDirection: 'row',
      justifyContent: 'space-between',
      alignItems: 'center',
      paddingHorizontal: 12,
      paddingVertical: 8,
    },
    backButton: {
      width: 40,
      height: 40,
      borderRadius: 12,
      alignItems: 'center',
      justifyContent: 'center',
      backgroundColor: isDark ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.04)',
    },
    navTitle: {
      fontSize: 17,
      fontWeight: '700',
      letterSpacing: -0.3,
    },
    starButton: {
      width: 40,
      height: 40,
      borderRadius: 12,
      alignItems: 'center',
      justifyContent: 'center',
    },

    scrollView: { flex: 1, zIndex: 10 },
    scrollContent: { paddingHorizontal: 20 },

    // 加载状态
    loadingContainer: {
      flex: 1,
      alignItems: 'center',
      justifyContent: 'center',
    },
    loadingText: { marginTop: 16, fontSize: 14 },
    emptyTitle: { fontSize: 16, fontWeight: '600', marginTop: 16 },

    // 股票头部
    stockHeader: { marginBottom: 12 },
    codeRow: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 8,
    },
    stockCode: {
      fontSize: 14,
      fontWeight: '600',
      letterSpacing: 0.5,
    },
    marketBadge: {
      paddingHorizontal: 8,
      paddingVertical: 2,
      borderRadius: 999,
    },
    marketBadgeText: {
      fontSize: 10,
      fontWeight: '800',
      letterSpacing: 0.5,
    },

    // 玻璃态卡片
    glassCard: {
      borderRadius: 20,
      borderWidth: StyleSheet.hairlineWidth,
      padding: 20,
      marginBottom: 16,
      ...Platform.select({
        ios: { shadowColor: isDark ? '#7C4DFF' : '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.06, shadowRadius: 16 },
        android: { elevation: 3 },
        web: { boxShadow: '0 4px 20px rgba(0,0,0,0.06)' },
      }),
    },

    // 价格
    priceRow: {
      flexDirection: 'row',
      alignItems: 'flex-end',
      justifyContent: 'space-between',
    },
    currentPrice: {
      fontSize: 36,
      fontWeight: '800',
      letterSpacing: -1,
    },
    changeInfo: {
      alignItems: 'flex-end',
    },
    changeText: {
      fontSize: 16,
      fontWeight: '700',
    },
    changePct: {
      fontSize: 16,
      fontWeight: '700',
      marginTop: 2,
    },
    divider: {
      height: 1,
      marginVertical: 16,
    },
    detailGrid: {
      flexDirection: 'row',
      flexWrap: 'wrap',
    },
    detailItem: {
      width: '33.33%',
      paddingVertical: 6,
    },
    detailLabel: {
      fontSize: 11,
      fontWeight: '600',
      letterSpacing: 0.3,
      marginBottom: 2,
    },
    detailValue: {
      fontSize: 15,
      fontWeight: '700',
    },

    // 基本面
    sectionTitle: {
      fontSize: 17,
      fontWeight: '800',
      letterSpacing: -0.3,
      marginBottom: 16,
    },
    fundamentalGrid: {
      flexDirection: 'row',
      justifyContent: 'space-around',
    },
    fundamentalItem: {
      alignItems: 'center',
    },
    fundamentalLabel: {
      fontSize: 11,
      fontWeight: '600',
      letterSpacing: 0.3,
      marginBottom: 4,
    },
    fundamentalValue: {
      fontSize: 18,
      fontWeight: '800',
    },

    // AI 预测
    predictionHeader: {
      flexDirection: 'row',
      justifyContent: 'space-between',
      alignItems: 'center',
      marginBottom: 16,
    },
    analyzeBtn: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 4,
      paddingHorizontal: 12,
      paddingVertical: 6,
      borderRadius: 999,
      borderWidth: StyleSheet.hairlineWidth,
    },
    analyzeBtnText: {
      fontSize: 12,
      fontWeight: '700',
    },
    signalRow: {
      flexDirection: 'row',
      alignItems: 'center',
      marginBottom: 12,
      gap: 12,
    },
    signalBadge: {
      paddingHorizontal: 12,
      paddingVertical: 5,
      borderRadius: 999,
    },
    signalText: {
      fontSize: 13,
      fontWeight: '800',
    },
    confidenceText: {
      fontSize: 12,
      fontWeight: '500',
    },
    reasoning: {
      fontSize: 14,
      lineHeight: 22,
      opacity: 0.9,
    },
    priceTargets: {
      flexDirection: 'row',
      justifyContent: 'space-around',
      marginTop: 16,
      paddingTop: 16,
      borderTopWidth: 1,
    },
    targetItem: {
      alignItems: 'center',
    },
    targetLabel: {
      fontSize: 11,
      fontWeight: '600',
      letterSpacing: 0.3,
      marginBottom: 4,
    },
    targetValue: {
      fontSize: 20,
      fontWeight: '800',
    },
    noPrediction: {
      alignItems: 'center',
      paddingVertical: 24,
    },
    noPredictionText: {
      fontSize: 14,
      marginTop: 12,
    },
    analyzeMainBtn: {
      marginTop: 16,
      paddingHorizontal: 24,
      paddingVertical: 10,
      borderRadius: 999,
    },
    analyzeMainBtnText: {
      color: '#FFFFFF',
      fontSize: 14,
      fontWeight: '700',
    },

    // MiniPlayer
    miniPlayerContainer: {
      position: 'absolute',
      left: 0,
      right: 0,
      bottom: 0,
      zIndex: 100,
    },
  });
}
