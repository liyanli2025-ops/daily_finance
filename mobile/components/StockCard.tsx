import React from 'react';
import { View, StyleSheet, Pressable } from 'react-native';
import { Card, Text, Chip, IconButton, useTheme } from 'react-native-paper';
import { MaterialCommunityIcons } from '@expo/vector-icons';

interface Stock {
  id: string;
  code: string;
  name: string;
  market: 'A' | 'HK';
  current_price?: number;
  change_percent?: number;
  latest_prediction?: 'bullish' | 'neutral' | 'bearish';
  latest_confidence?: number;
}

interface StockCardProps {
  stock: Stock;
  onPress?: () => void;
  onRemove?: () => void;
}

export default function StockCard({ stock, onPress, onRemove }: StockCardProps) {
  const theme = useTheme();

  const getPredictionColor = (prediction?: string) => {
    switch (prediction) {
      case 'bullish':
        return '#4CAF50';
      case 'bearish':
        return '#F44336';
      default:
        return theme.colors.outline;
    }
  };

  const getPredictionText = (prediction?: string) => {
    switch (prediction) {
      case 'bullish':
        return '看多';
      case 'bearish':
        return '看空';
      default:
        return '中性';
    }
  };

  const priceColor = (stock.change_percent ?? 0) >= 0 ? '#4CAF50' : '#F44336';

  return (
    <Card
      style={[styles.card, { backgroundColor: theme.colors.surface }]}
      onPress={onPress}
    >
      <Card.Content style={styles.content}>
        <View style={styles.mainInfo}>
          {/* 股票名称和代码 */}
          <View style={styles.nameSection}>
            <Text variant="titleMedium" style={styles.stockName}>
              {stock.name}
            </Text>
            <View style={styles.codeRow}>
              <Text variant="bodySmall" style={{ color: theme.colors.outline }}>
                {stock.code}
              </Text>
              <Chip
                compact
                style={[styles.marketChip, { 
                  backgroundColor: stock.market === 'A' 
                    ? 'rgba(255, 87, 51, 0.15)' 
                    : 'rgba(33, 150, 243, 0.15)' 
                }]}
                textStyle={{ 
                  fontSize: 10, 
                  color: stock.market === 'A' ? '#FF5733' : '#2196F3' 
                }}
              >
                {stock.market === 'A' ? 'A股' : '港股'}
              </Chip>
            </View>
          </View>

          {/* 价格信息 */}
          <View style={styles.priceSection}>
            <Text variant="titleLarge" style={[styles.price, { color: priceColor }]}>
              {stock.current_price?.toFixed(2) ?? '--'}
            </Text>
            <Text variant="bodySmall" style={{ color: priceColor }}>
              {stock.change_percent !== undefined 
                ? `${stock.change_percent >= 0 ? '+' : ''}${stock.change_percent.toFixed(2)}%`
                : '--'}
            </Text>
          </View>
        </View>

        {/* AI 预测 */}
        <View style={styles.predictionSection}>
          <View style={styles.predictionInfo}>
            <MaterialCommunityIcons
              name="robot"
              size={16}
              color={getPredictionColor(stock.latest_prediction)}
            />
            <Text
              variant="bodySmall"
              style={{ color: getPredictionColor(stock.latest_prediction), marginLeft: 4 }}
            >
              AI预测: {getPredictionText(stock.latest_prediction)}
            </Text>
            {stock.latest_confidence !== undefined && (
              <Text variant="bodySmall" style={{ color: theme.colors.outline, marginLeft: 8 }}>
                置信度 {Math.round(stock.latest_confidence * 100)}%
              </Text>
            )}
          </View>

          {onRemove && (
            <IconButton
              icon="close"
              size={16}
              iconColor={theme.colors.outline}
              onPress={onRemove}
              style={styles.removeButton}
            />
          )}
        </View>
      </Card.Content>
    </Card>
  );
}

const styles = StyleSheet.create({
  card: {
    borderRadius: 12,
  },
  content: {
    paddingVertical: 12,
  },
  mainInfo: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
  },
  nameSection: {
    flex: 1,
  },
  stockName: {
    fontWeight: '600',
  },
  codeRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginTop: 4,
    gap: 8,
  },
  marketChip: {
    height: 20,
  },
  priceSection: {
    alignItems: 'flex-end',
  },
  price: {
    fontWeight: '700',
  },
  predictionSection: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginTop: 12,
    paddingTop: 12,
    borderTopWidth: 1,
    borderTopColor: 'rgba(255, 255, 255, 0.1)',
  },
  predictionInfo: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  removeButton: {
    margin: 0,
  },
});
