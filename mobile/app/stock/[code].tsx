import React, { useEffect, useState } from 'react';
import { View, ScrollView, StyleSheet, RefreshControl } from 'react-native';
import {
  Text,
  Card,
  Chip,
  Button,
  IconButton,
  useTheme,
  ActivityIndicator,
  Divider,
} from 'react-native-paper';
import { useLocalSearchParams, router } from 'expo-router';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import ChartView from '@/components/ChartView';
import { useStockStore } from '@/stores/stockStore';
import { api } from '@/services/api';

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
  const theme = useTheme();
  const { code, market } = useLocalSearchParams<{ code: string; market: string }>();
  const { watchlist, addToWatchlist, removeFromWatchlist } = useStockStore();

  const [stock, setStock] = useState<StockDetail | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [isAnalyzing, setIsAnalyzing] = useState(false);

  const isInWatchlist = watchlist.some((s) => s.code === code && s.market === market);

  useEffect(() => {
    fetchStockDetail();
  }, [code, market]);

  const fetchStockDetail = async () => {
    setIsLoading(true);
    try {
      // 获取实时行情
      const quoteData = await api.getStockQuote(code!, market!);
      
      // 尝试获取 AI 预测（不影响主流程）
      let prediction = undefined;
      try {
        const predData = await api.getStockPrediction(code!, market!);
        if (predData && predData.prediction && predData.prediction !== 'neutral') {
          prediction = {
            signal: predData.prediction as 'bullish' | 'neutral' | 'bearish',
            confidence: predData.confidence || 0.5,
            reasoning: predData.reasoning || '',
            target_price: predData.target_price,
            stop_loss: predData.stop_loss,
          };
        } else if (predData && predData.prediction) {
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
    if (num >= 100000000) {
      return `${(num / 100000000).toFixed(2)}亿`;
    }
    if (num >= 10000) {
      return `${(num / 10000).toFixed(2)}万`;
    }
    return num.toFixed(2);
  };

  const getPredictionColor = (signal?: string) => {
    switch (signal) {
      case 'bullish':
        return '#22C55E';
      case 'bearish':
        return '#EF4444';
      default:
        return theme.colors.outline;
    }
  };

  const getPredictionLabel = (signal?: string) => {
    switch (signal) {
      case 'bullish':
        return '看多';
      case 'bearish':
        return '看空';
      default:
        return '中性';
    }
  };

  if (isLoading) {
    return (
      <View style={[styles.loadingContainer, { backgroundColor: theme.colors.background }]}>
        <ActivityIndicator size="large" color={theme.colors.primary} />
        <Text style={{ marginTop: 16, color: theme.colors.outline }}>
          正在加载股票数据...
        </Text>
      </View>
    );
  }

  if (!stock) {
    return (
      <View style={[styles.loadingContainer, { backgroundColor: theme.colors.background }]}>
        <MaterialCommunityIcons name="chart-line" size={64} color={theme.colors.outline} />
        <Text variant="titleMedium" style={{ marginTop: 16, color: theme.colors.outline }}>
          股票数据加载失败
        </Text>
      </View>
    );
  }

  // 中国A股习惯：红涨绿跌
  const priceColor = stock.change_percent >= 0 ? '#EF4444' : '#22C55E';

  return (
    <View style={[styles.container, { backgroundColor: theme.colors.background }]}>
      <ScrollView
        style={styles.scrollView}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={onRefresh}
            tintColor={theme.colors.primary}
          />
        }
      >
        {/* 股票头部信息 */}
        <View style={styles.header}>
          <View style={styles.stockInfo}>
            <Text variant="headlineMedium" style={styles.stockName}>
              {stock.name}
            </Text>
            <View style={styles.codeRow}>
              <Text variant="bodyMedium" style={{ color: theme.colors.outline }}>
                {stock.code}
              </Text>
              <Chip
                compact
                style={{
                  marginLeft: 8,
                  backgroundColor:
                    stock.market === 'A'
                      ? 'rgba(255, 87, 51, 0.15)'
                      : 'rgba(33, 150, 243, 0.15)',
                }}
                textStyle={{
                  fontSize: 10,
                  color: stock.market === 'A' ? '#FF5733' : '#2196F3',
                }}
              >
                {stock.market === 'A' ? 'A股' : '港股'}
              </Chip>
            </View>
          </View>
          <IconButton
            icon={isInWatchlist ? 'star' : 'star-outline'}
            iconColor={isInWatchlist ? '#F59E0B' : theme.colors.outline}
            size={28}
            onPress={handleToggleWatchlist}
          />
        </View>

        {/* 价格信息 */}
        <Card style={[styles.priceCard, { backgroundColor: theme.colors.surface }]}>
          <Card.Content>
            <View style={styles.priceRow}>
              <Text variant="displaySmall" style={[styles.currentPrice, { color: priceColor }]}>
                {stock.current_price.toFixed(2)}
              </Text>
              <View style={styles.changeInfo}>
                <Text style={[styles.changeText, { color: priceColor }]}>
                  {stock.change >= 0 ? '+' : ''}
                  {stock.change.toFixed(2)}
                </Text>
                <Text style={[styles.changeText, { color: priceColor }]}>
                  {stock.change_percent >= 0 ? '+' : ''}
                  {stock.change_percent.toFixed(2)}%
                </Text>
              </View>
            </View>

            <Divider style={{ marginVertical: 16 }} />

            <View style={styles.detailGrid}>
              <View style={styles.detailItem}>
                <Text variant="labelSmall" style={{ color: theme.colors.outline }}>
                  今开
                </Text>
                <Text variant="bodyMedium">{stock.open_price.toFixed(2)}</Text>
              </View>
              <View style={styles.detailItem}>
                <Text variant="labelSmall" style={{ color: theme.colors.outline }}>
                  最高
                </Text>
                <Text variant="bodyMedium" style={{ color: '#EF4444' }}>
                  {stock.high_price.toFixed(2)}
                </Text>
              </View>
              <View style={styles.detailItem}>
                <Text variant="labelSmall" style={{ color: theme.colors.outline }}>
                  最低
                </Text>
                <Text variant="bodyMedium" style={{ color: '#22C55E' }}>
                  {stock.low_price.toFixed(2)}
                </Text>
              </View>
              <View style={styles.detailItem}>
                <Text variant="labelSmall" style={{ color: theme.colors.outline }}>
                  昨收
                </Text>
                <Text variant="bodyMedium">{stock.prev_close.toFixed(2)}</Text>
              </View>
              <View style={styles.detailItem}>
                <Text variant="labelSmall" style={{ color: theme.colors.outline }}>
                  成交量
                </Text>
                <Text variant="bodyMedium">{formatNumber(stock.volume)}</Text>
              </View>
              <View style={styles.detailItem}>
                <Text variant="labelSmall" style={{ color: theme.colors.outline }}>
                  成交额
                </Text>
                <Text variant="bodyMedium">{formatNumber(stock.amount)}</Text>
              </View>
            </View>
          </Card.Content>
        </Card>

        {/* K线图 */}
        <ChartView stockCode={stock.code} stockName={stock.name} market={market || 'A'} />

        {/* 基本面数据 */}
        <Card style={[styles.fundamentalCard, { backgroundColor: theme.colors.surface }]}>
          <Card.Content>
            <Text variant="titleMedium" style={styles.sectionTitle}>
              📊 基本面数据
            </Text>
            <View style={styles.fundamentalGrid}>
              <View style={styles.fundamentalItem}>
                <Text variant="labelSmall" style={{ color: theme.colors.outline }}>
                  市盈率(PE)
                </Text>
                <Text variant="titleMedium" style={{ fontWeight: '600' }}>
                  {stock.pe_ratio?.toFixed(2) || '--'}
                </Text>
              </View>
              <View style={styles.fundamentalItem}>
                <Text variant="labelSmall" style={{ color: theme.colors.outline }}>
                  市净率(PB)
                </Text>
                <Text variant="titleMedium" style={{ fontWeight: '600' }}>
                  {stock.pb_ratio?.toFixed(2) || '--'}
                </Text>
              </View>
              <View style={styles.fundamentalItem}>
                <Text variant="labelSmall" style={{ color: theme.colors.outline }}>
                  总市值
                </Text>
                <Text variant="titleMedium" style={{ fontWeight: '600' }}>
                  {stock.market_cap ? formatNumber(stock.market_cap) : '--'}
                </Text>
              </View>
            </View>
          </Card.Content>
        </Card>

        {/* AI 分析预测 */}
        <Card style={[styles.predictionCard, { backgroundColor: theme.colors.surface }]}>
          <Card.Content>
            <View style={styles.predictionHeader}>
              <Text variant="titleMedium" style={styles.sectionTitle}>
                🤖 AI 分析预测
              </Text>
              <Button
                mode="outlined"
                compact
                loading={isAnalyzing}
                onPress={handleAnalyze}
                style={{ borderRadius: 20 }}
              >
                重新分析
              </Button>
            </View>

            {stock.prediction ? (
              <>
                <View style={styles.signalRow}>
                  <View style={styles.signalInfo}>
                    <Chip
                      style={{
                        backgroundColor: getPredictionColor(stock.prediction.signal) + '20',
                      }}
                      textStyle={{
                        color: getPredictionColor(stock.prediction.signal),
                        fontWeight: '600',
                      }}
                    >
                      {getPredictionLabel(stock.prediction.signal)}
                    </Chip>
                    <Text variant="bodySmall" style={{ marginLeft: 12, color: theme.colors.outline }}>
                      置信度: {Math.round(stock.prediction.confidence * 100)}%
                    </Text>
                  </View>
                </View>

                <Text variant="bodyMedium" style={styles.reasoning}>
                  {stock.prediction.reasoning}
                </Text>

                {(stock.prediction.target_price || stock.prediction.stop_loss) && (
                  <View style={styles.priceTargets}>
                    {stock.prediction.target_price && (
                      <View style={styles.targetItem}>
                        <Text variant="labelSmall" style={{ color: '#22C55E' }}>
                          目标价
                        </Text>
                        <Text
                          variant="titleMedium"
                          style={{ color: '#22C55E', fontWeight: '700' }}
                        >
                          {stock.prediction.target_price.toFixed(2)}
                        </Text>
                      </View>
                    )}
                    {stock.prediction.stop_loss && (
                      <View style={styles.targetItem}>
                        <Text variant="labelSmall" style={{ color: '#EF4444' }}>
                          止损位
                        </Text>
                        <Text
                          variant="titleMedium"
                          style={{ color: '#EF4444', fontWeight: '700' }}
                        >
                          {stock.prediction.stop_loss.toFixed(2)}
                        </Text>
                      </View>
                    )}
                  </View>
                )}
              </>
            ) : (
              <View style={styles.noPrediction}>
                <MaterialCommunityIcons
                  name="robot-outline"
                  size={48}
                  color={theme.colors.outline}
                />
                <Text variant="bodyMedium" style={{ color: theme.colors.outline, marginTop: 12 }}>
                  暂无 AI 分析数据
                </Text>
                <Button
                  mode="contained"
                  style={{ marginTop: 16 }}
                  loading={isAnalyzing}
                  onPress={handleAnalyze}
                >
                  立即分析
                </Button>
              </View>
            )}
          </Card.Content>
        </Card>

        <View style={{ height: 32 }} />
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
  scrollView: {
    flex: 1,
    paddingHorizontal: 16,
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    paddingTop: 8,
    paddingBottom: 16,
  },
  stockInfo: {
    flex: 1,
  },
  stockName: {
    fontWeight: '700',
  },
  codeRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginTop: 4,
  },
  priceCard: {
    borderRadius: 16,
    marginBottom: 16,
  },
  priceRow: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    justifyContent: 'space-between',
  },
  currentPrice: {
    fontWeight: '700',
  },
  changeInfo: {
    alignItems: 'flex-end',
  },
  changeText: {
    fontSize: 16,
    fontWeight: '600',
  },
  detailGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
  },
  detailItem: {
    width: '33.33%',
    paddingVertical: 8,
  },
  fundamentalCard: {
    borderRadius: 16,
    marginBottom: 16,
  },
  sectionTitle: {
    fontWeight: '600',
    marginBottom: 16,
  },
  fundamentalGrid: {
    flexDirection: 'row',
    justifyContent: 'space-around',
  },
  fundamentalItem: {
    alignItems: 'center',
  },
  predictionCard: {
    borderRadius: 16,
    marginBottom: 16,
  },
  predictionHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 8,
  },
  signalRow: {
    marginBottom: 16,
  },
  signalInfo: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  reasoning: {
    lineHeight: 22,
    opacity: 0.9,
  },
  priceTargets: {
    flexDirection: 'row',
    justifyContent: 'space-around',
    marginTop: 20,
    paddingTop: 16,
    borderTopWidth: 1,
    borderTopColor: 'rgba(255,255,255,0.1)',
  },
  targetItem: {
    alignItems: 'center',
  },
  noPrediction: {
    alignItems: 'center',
    paddingVertical: 24,
  },
});
