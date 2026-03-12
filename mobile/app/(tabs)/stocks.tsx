import React, { useEffect, useState } from 'react';
import { View, ScrollView, StyleSheet, RefreshControl } from 'react-native';
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
} from 'react-native-paper';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import { router } from 'expo-router';
import { useStockStore } from '@/stores/stockStore';
import StockCard from '@/components/StockCard';

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

  useEffect(() => {
    fetchWatchlist();
  }, []);

  const onRefresh = async () => {
    setRefreshing(true);
    await fetchWatchlist();
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
            {[
              { name: '上证指数', value: '3089.23', change: '+0.52%', up: true },
              { name: '深证成指', value: '9456.78', change: '-0.23%', up: false },
              { name: '恒生指数', value: '17234.56', change: '+1.05%', up: true },
            ].map((index, i) => (
              <Card
                key={i}
                style={[styles.indexCard, { backgroundColor: theme.colors.surface }]}
              >
                <Card.Content>
                  <Text variant="bodySmall" style={{ color: theme.colors.outline }}>
                    {index.name}
                  </Text>
                  <Text variant="titleMedium" style={{ fontWeight: '700', marginTop: 4 }}>
                    {index.value}
                  </Text>
                  <Text
                    variant="bodySmall"
                    style={{
                      color: index.up ? '#4CAF50' : '#F44336',
                      fontWeight: '600',
                      marginTop: 2,
                    }}
                  >
                    {index.change}
                  </Text>
                </Card.Content>
              </Card>
            ))}
          </View>
        </View>

        {/* 自选股列表 */}
        <View style={styles.watchlistSection}>
          <View style={styles.sectionHeader}>
            <Text variant="titleMedium" style={styles.sectionTitle}>
              ⭐ 我的自选
            </Text>
            <Text variant="bodySmall" style={{ color: theme.colors.outline }}>
              {watchlist.length} 只股票
            </Text>
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
                  onPress={() => router.push(`/stock/${stock.code}?market=${stock.market}`)}
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
            </View>
          ) : (
            <ScrollView style={styles.searchResults}>
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
    gap: 12,
  },
  indexCard: {
    flex: 1,
    borderRadius: 12,
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
    bottom: 16,
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
