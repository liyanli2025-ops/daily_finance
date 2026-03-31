import React, { useEffect, useState } from 'react';
import { View, ScrollView, StyleSheet, RefreshControl, Alert } from 'react-native';
import {
  Text,
  Card,
  FAB,
  Searchbar,
  Chip,
  Portal,
  Modal,
  Button,
  useTheme,
  ActivityIndicator,
  Snackbar,
} from 'react-native-paper';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import { router } from 'expo-router';
import { useStockStore } from '@/stores/stockStore';
import { api } from '@/services/api';
import StockCard from '@/components/StockCard';

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
  const theme = useTheme();
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

  // AI 预测处理函数
  const handleAIPrediction = async () => {
    setIsPredicting(true);
    try {
      const result = await api.generateWatchlistPredictions();
      if (result.status === 'success') {
        setSnackbarMessage(`✅ ${result.message}`);
        // 刷新列表以显示新的预测结果
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

    // 交易时间内自动刷新（每30秒）
    const interval = setInterval(() => {
      const now = new Date();
      const hour = now.getHours();
      const minute = now.getMinutes();
      // 9:15 - 15:05 之间自动刷新
      if ((hour === 9 && minute >= 15) || (hour > 9 && hour < 15) || (hour === 15 && minute <= 5)) {
        fetchWatchlist();
        fetchIndices();
      }
    }, 30000);

    return () => clearInterval(interval);
  }, []);

  const onRefresh = async () => {
    setRefreshing(true);
    // 先刷新自选股行情数据，再获取最新列表
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
        {/* 市场概览 */}
        <View style={styles.marketOverview}>
          <Text variant="titleMedium" style={styles.sectionTitle}>
            📊 市场概览
          </Text>
          <View style={styles.indexContainer}>
            {indicesLoading ? (
              <View style={styles.indicesLoadingContainer}>
                <ActivityIndicator size="small" color={theme.colors.primary} />
                <Text variant="bodySmall" style={{ color: theme.colors.outline, marginTop: 8 }}>
                  加载指数数据...
                </Text>
              </View>
            ) : indices.length > 0 ? (
              indices.slice(0, 5).map((idx) => (
                <Card
                  key={idx.code}
                  style={[styles.indexCard, { backgroundColor: theme.colors.surface }]}
                >
                  <Card.Content>
                    <Text variant="bodySmall" style={{ color: theme.colors.outline }} numberOfLines={1}>
                      {idx.name}
                    </Text>
                    <Text variant="titleMedium" style={{ fontWeight: '700', marginTop: 4 }}>
                      {idx.current.toFixed(2)}
                    </Text>
                    <Text
                      variant="bodySmall"
                      style={{
                        color: idx.change_pct >= 0 ? '#F44336' : '#4CAF50',  // 红涨绿跌
                        fontWeight: '600',
                        marginTop: 2,
                      }}
                    >
                      {idx.change_pct >= 0 ? '+' : ''}{idx.change_pct.toFixed(2)}%
                    </Text>
                  </Card.Content>
                </Card>
              ))
            ) : (
              <View style={styles.indicesErrorContainer}>
                <MaterialCommunityIcons
                  name="chart-line"
                  size={32}
                  color={theme.colors.outline}
                />
                <Text variant="bodySmall" style={{ color: theme.colors.outline, marginTop: 8, textAlign: 'center' }}>
                  {indicesError || '暂无指数数据'}
                </Text>
                <Button
                  mode="text"
                  compact
                  onPress={fetchIndices}
                  style={{ marginTop: 4 }}
                >
                  点击重试
                </Button>
              </View>
            )}
          </View>
        </View>

        {/* 自选股列表 */}
        <View style={styles.watchlistSection}>
          <View style={styles.sectionHeader}>
            <View style={{ flexDirection: 'row', alignItems: 'center' }}>
              <Text variant="titleMedium" style={styles.sectionTitle}>
                ⭐ 我的自选
              </Text>
              <Text variant="bodySmall" style={{ color: theme.colors.outline, marginLeft: 8 }}>
                {watchlist.length} 只
              </Text>
            </View>
            {watchlist.length > 0 && (
              <Button
                mode="outlined"
                compact
                icon="robot"
                onPress={handleAIPrediction}
                loading={isPredicting}
                disabled={isPredicting}
                style={{ borderRadius: 20 }}
                labelStyle={{ fontSize: 12 }}
              >
                {isPredicting ? 'AI分析中...' : 'AI预测'}
              </Button>
            )}
          </View>

          {isLoading ? (
            <View style={styles.loadingContainer}>
              <ActivityIndicator size="large" color={theme.colors.primary} />
            </View>
          ) : watchlist.length === 0 ? (
            <View style={styles.emptyContainer}>
              <MaterialCommunityIcons
                name="star-outline"
                size={64}
                color={theme.colors.outline}
              />
              <Text variant="titleMedium" style={{ color: theme.colors.outline, marginTop: 16 }}>
                暂无自选股
              </Text>
              <Text
                variant="bodySmall"
                style={{ color: theme.colors.outline, marginTop: 8, textAlign: 'center' }}
              >
                点击右下角 + 按钮添加股票
              </Text>
            </View>
          ) : (
            <View style={styles.stockGrid}>
              {watchlist.map((stock) => (
              <StockCard
                  key={stock.id}
                  stock={stock}
                  onPress={() => {}} // 暂时禁用，详情页待完善
                  onRemove={() => removeFromWatchlist(stock.id)}
                />
              ))}
            </View>
          )}
        </View>

        <View style={{ height: 80 }} />
      </ScrollView>

      {/* 添加股票按钮 */}
      <FAB
        icon="plus"
        style={[styles.fab, { backgroundColor: theme.colors.primary }]}
        color="#fff"
        onPress={() => setSearchVisible(true)}
      />

      {/* 搜索股票弹窗 */}
      <Portal>
        <Modal
          visible={searchVisible}
          onDismiss={() => {
            setSearchVisible(false);
            setSearchQuery('');
          }}
          contentContainerStyle={[
            styles.modalContent,
            { backgroundColor: theme.colors.surface },
          ]}
        >
          <Text variant="titleLarge" style={{ marginBottom: 16 }}>
            添加自选股
          </Text>

          <Searchbar
            placeholder="输入股票代码或名称"
            onChangeText={handleSearch}
            value={searchQuery}
            style={{ marginBottom: 16 }}
            autoFocus
          />

          {/* 快捷标签 */}
          <View style={styles.quickTags}>
            <Chip
              style={{ marginRight: 8 }}
              onPress={() => handleSearch('茅台')}
            >
              贵州茅台
            </Chip>
            <Chip
              style={{ marginRight: 8 }}
              onPress={() => handleSearch('腾讯')}
            >
              腾讯控股
            </Chip>
            <Chip onPress={() => handleSearch('比亚迪')}>
              比亚迪
            </Chip>
          </View>

          {/* 搜索结果 */}
          {isSearching ? (
            <View style={styles.searchLoading}>
              <ActivityIndicator size="small" color={theme.colors.primary} />
              <Text variant="bodySmall" style={{ color: theme.colors.outline, marginTop: 8 }}>
                正在搜索...
              </Text>
            </View>
          ) : searchQuery.length > 0 && searchResults.length === 0 ? (
            <View style={styles.searchLoading}>
              <Text variant="bodySmall" style={{ color: theme.colors.outline }}>
                未找到"{searchQuery}"，请稍后重试
              </Text>
            </View>
          ) : (
            <ScrollView style={styles.searchResults}>
              {searchResults.length > 0 && (
                <Text variant="bodySmall" style={{ color: theme.colors.outline, marginBottom: 8 }}>
                  点击添加到自选 ↓
                </Text>
              )}
              {searchResults.map((result, index) => (
                <Card
                  key={index}
                  style={[styles.searchResultCard, { backgroundColor: theme.colors.surfaceVariant }]}
                  onPress={() => handleAddStock(result)}
                >
                  <Card.Content style={styles.searchResultContent}>
                    <View>
                      <Text variant="titleSmall">{result.name}</Text>
                      <Text variant="bodySmall" style={{ color: theme.colors.outline }}>
                        {result.code} · {result.market === 'A' ? 'A股' : '港股'}
                      </Text>
                    </View>
                    <MaterialCommunityIcons
                      name="plus-circle"
                      size={24}
                      color={theme.colors.primary}
                    />
                  </Card.Content>
                </Card>
              ))}
            </ScrollView>
          )}

          <Button
            mode="outlined"
            onPress={() => {
              setSearchVisible(false);
              setSearchQuery('');
            }}
            style={{ marginTop: 16 }}
          >
            取消
          </Button>
        </Modal>
      </Portal>

      {/* 消息提示 */}
      <Snackbar
        visible={snackbarVisible}
        onDismiss={() => setSnackbarVisible(false)}
        duration={4000}
        action={{
          label: '关闭',
          onPress: () => setSnackbarVisible(false),
        }}
      >
        {snackbarMessage}
      </Snackbar>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  scrollView: {
    flex: 1,
    padding: 16,
  },
  marketOverview: {
    marginBottom: 24,
  },
  sectionTitle: {
    fontWeight: '600',
    marginBottom: 12,
  },
  indexContainer: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
  indexCard: {
    minWidth: '30%',
    flex: 1,
    borderRadius: 12,
  },
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
  watchlistSection: {
    flex: 1,
  },
  sectionHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 12,
  },
  loadingContainer: {
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 60,
  },
  emptyContainer: {
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 60,
  },
  stockGrid: {
    gap: 12,
  },
  fab: {
    position: 'absolute',
    right: 16,
    bottom: 80,
    borderRadius: 16,
  },
  modalContent: {
    margin: 20,
    padding: 20,
    borderRadius: 16,
    maxHeight: '80%',
  },
  quickTags: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    marginBottom: 16,
  },
  searchLoading: {
    paddingVertical: 20,
    alignItems: 'center',
  },
  searchResults: {
    maxHeight: 300,
  },
  searchResultCard: {
    marginBottom: 8,
    borderRadius: 12,
  },
  searchResultContent: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
});
