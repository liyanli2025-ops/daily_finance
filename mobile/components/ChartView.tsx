import React, { useState, useEffect } from 'react';
import { View, StyleSheet, Dimensions, ActivityIndicator } from 'react-native';
import { Text, SegmentedButtons, useTheme } from 'react-native-paper';
import { LineChart, BarChart } from 'react-native-chart-kit';
import { api } from '@/services/api';

const screenWidth = Dimensions.get('window').width;

interface KLineItem {
  trade_date: string;
  open_price: number;
  high_price: number;
  low_price: number;
  close_price: number;
  volume: number;
  amount?: number;
}

interface ChartViewProps {
  stockCode: string;
  stockName: string;
  market?: string;
  compact?: boolean;
}

export default function ChartView({
  stockCode,
  stockName,
  market = 'A',
  compact = false,
}: ChartViewProps) {
  const theme = useTheme();
  const [chartType, setChartType] = useState<string>('price');
  const [period, setPeriod] = useState<string>('daily');
  const [klineData, setKlineData] = useState<KLineItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchKlineData();
  }, [stockCode, market, period]);

  const fetchKlineData = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await api.getStockKline(stockCode, market, period, compact ? 20 : 60);
      if (data && data.length > 0) {
        setKlineData(data);
      } else {
        setError('暂无数据');
      }
    } catch (e: any) {
      console.error('获取K线数据失败:', e);
      setError('加载失败');
    }
    setIsLoading(false);
  };

  // 从 K 线数据中提取图表所需格式
  const getChartData = () => {
    if (klineData.length === 0) {
      return { labels: [], prices: [], volumes: [], ma5: [], ma10: [] };
    }

    // 取最近的数据点（紧凑模式取 15，正常取最多 30 以保持可读性）
    const displayCount = compact ? 15 : Math.min(klineData.length, 30);
    const sliced = klineData.slice(-displayCount);

    const labels = sliced.map((k) => {
      const d = k.trade_date;
      // 格式化日期 "2025-04-09" → "4/9"
      if (d && d.includes('-')) {
        const parts = d.split('-');
        return `${parseInt(parts[1])}/${parseInt(parts[2])}`;
      }
      return d;
    });

    const prices = sliced.map((k) => k.close_price);
    const volumes = sliced.map((k) => k.volume);

    // 计算 MA5 和 MA10
    const allClose = klineData.map((k) => k.close_price);
    const calcMA = (data: number[], n: number) => {
      const result: number[] = [];
      for (let i = 0; i < data.length; i++) {
        if (i < n - 1) {
          result.push(data[i]);
        } else {
          const sum = data.slice(i - n + 1, i + 1).reduce((a, b) => a + b, 0);
          result.push(sum / n);
        }
      }
      return result.slice(-displayCount);
    };

    const ma5 = calcMA(allClose, 5);
    const ma10 = calcMA(allClose, 10);

    // 只在标签数较多时每隔几个显示
    const step = labels.length > 10 ? Math.ceil(labels.length / 6) : 1;
    const sparseLabels = labels.map((l, i) => (i % step === 0 ? l : ''));

    return { labels: sparseLabels, prices, volumes, ma5, ma10 };
  };

  const chartData = getChartData();

  const chartConfig = {
    backgroundColor: theme.colors.surface,
    backgroundGradientFrom: theme.colors.surface,
    backgroundGradientTo: theme.colors.surface,
    decimalPlaces: 2,
    color: (opacity = 1) => `rgba(37, 99, 235, ${opacity})`,
    labelColor: (opacity = 1) => `rgba(148, 163, 184, ${opacity})`,
    style: {
      borderRadius: 12,
    },
    propsForDots: {
      r: '3',
      strokeWidth: '1.5',
      stroke: '#2563EB',
    },
    propsForBackgroundLines: {
      stroke: 'rgba(148, 163, 184, 0.2)',
    },
  };

  const chartWidth = compact ? screenWidth - 64 : screenWidth - 32;
  const chartHeight = compact ? 150 : 220;

  if (isLoading) {
    return (
      <View style={[compact ? styles.compactContainer : styles.container, { backgroundColor: theme.colors.surface }]}>
        <View style={styles.loadingContainer}>
          <ActivityIndicator size="small" color={theme.colors.primary} />
          <Text variant="bodySmall" style={{ color: theme.colors.outline, marginTop: 8 }}>
            加载K线数据...
          </Text>
        </View>
      </View>
    );
  }

  if (error || chartData.prices.length === 0) {
    return (
      <View style={[compact ? styles.compactContainer : styles.container, { backgroundColor: theme.colors.surface }]}>
        <View style={styles.loadingContainer}>
          <Text variant="bodySmall" style={{ color: theme.colors.outline }}>
            {error || '暂无K线数据'}
          </Text>
        </View>
      </View>
    );
  }

  if (compact) {
    return (
      <View style={[styles.compactContainer, { backgroundColor: theme.colors.surface }]}>
        <View style={styles.compactHeader}>
          <Text variant="titleSmall" style={styles.stockName}>
            {stockName}
          </Text>
          <Text variant="bodySmall" style={{ color: theme.colors.outline }}>
            {stockCode}
          </Text>
        </View>
        <LineChart
          data={{
            labels: chartData.labels,
            datasets: [
              {
                data: chartData.prices,
                color: (opacity = 1) => `rgba(37, 99, 235, ${opacity})`,
                strokeWidth: 2,
              },
            ],
          }}
          width={chartWidth}
          height={chartHeight}
          chartConfig={chartConfig}
          bezier
          withHorizontalLabels={false}
          withVerticalLabels={false}
          withDots={false}
          withInnerLines={false}
          withOuterLines={false}
          style={styles.chart}
        />
      </View>
    );
  }

  return (
    <View style={[styles.container, { backgroundColor: theme.colors.surface }]}>
      {/* 标题栏 */}
      <View style={styles.header}>
        <View>
          <Text variant="titleMedium" style={styles.stockName}>
            📈 K线走势
          </Text>
        </View>
      </View>

      {/* 周期选择 */}
      <View style={styles.periodSelector}>
        <SegmentedButtons
          value={period}
          onValueChange={setPeriod}
          buttons={[
            { value: 'daily', label: '日K' },
            { value: 'weekly', label: '周K' },
            { value: 'monthly', label: '月K' },
          ]}
          density="small"
          style={styles.segmentedButton}
        />
      </View>

      {/* 图表类型选择 */}
      <View style={styles.chartTypeSelector}>
        <SegmentedButtons
          value={chartType}
          onValueChange={setChartType}
          buttons={[
            { value: 'price', label: '价格' },
            { value: 'volume', label: '成交量' },
          ]}
          density="small"
          style={styles.segmentedButton}
        />
      </View>

      {/* 图表展示 */}
      {chartType === 'price' && (
        <View style={styles.chartSection}>
          <LineChart
            data={{
              labels: chartData.labels,
              datasets: [
                {
                  data: chartData.prices,
                  color: (opacity = 1) => `rgba(37, 99, 235, ${opacity})`,
                  strokeWidth: 2,
                },
                {
                  data: chartData.ma5,
                  color: (opacity = 1) => `rgba(245, 158, 11, ${opacity})`,
                  strokeWidth: 1,
                },
                {
                  data: chartData.ma10,
                  color: (opacity = 1) => `rgba(239, 68, 68, ${opacity})`,
                  strokeWidth: 1,
                },
              ],
              legend: ['收盘价', 'MA5', 'MA10'],
            }}
            width={chartWidth}
            height={chartHeight}
            chartConfig={chartConfig}
            bezier
            style={styles.chart}
          />
          <View style={styles.legendContainer}>
            <View style={styles.legendItem}>
              <View style={[styles.legendDot, { backgroundColor: '#2563EB' }]} />
              <Text variant="labelSmall">收盘价</Text>
            </View>
            <View style={styles.legendItem}>
              <View style={[styles.legendDot, { backgroundColor: '#F59E0B' }]} />
              <Text variant="labelSmall">MA5</Text>
            </View>
            <View style={styles.legendItem}>
              <View style={[styles.legendDot, { backgroundColor: '#EF4444' }]} />
              <Text variant="labelSmall">MA10</Text>
            </View>
          </View>
        </View>
      )}

      {chartType === 'volume' && (
        <View style={styles.chartSection}>
          <BarChart
            data={{
              labels: chartData.labels,
              datasets: [
                {
                  data: chartData.volumes.map(v => v > 0 ? v / 10000 : 0),
                },
              ],
            }}
            width={chartWidth}
            height={chartHeight}
            chartConfig={{
              ...chartConfig,
              color: (opacity = 1) => `rgba(34, 197, 94, ${opacity})`,
            }}
            yAxisLabel=""
            yAxisSuffix="万"
            style={styles.chart}
          />
          <Text variant="bodySmall" style={styles.volumeHint}>
            单位：万手
          </Text>
        </View>
      )}

      {/* 技术指标摘要（从真实数据计算） */}
      {klineData.length > 0 && (
        <View style={styles.indicatorSummary}>
          <View style={styles.indicatorItem}>
            <Text variant="labelSmall" style={{ color: theme.colors.outline }}>
              MA5
            </Text>
            <Text variant="bodyMedium" style={{ fontWeight: '600' }}>
              {chartData.ma5.length > 0 ? chartData.ma5[chartData.ma5.length - 1].toFixed(2) : '--'}
            </Text>
          </View>
          <View style={styles.indicatorItem}>
            <Text variant="labelSmall" style={{ color: theme.colors.outline }}>
              MA10
            </Text>
            <Text variant="bodyMedium" style={{ fontWeight: '600' }}>
              {chartData.ma10.length > 0 ? chartData.ma10[chartData.ma10.length - 1].toFixed(2) : '--'}
            </Text>
          </View>
          <View style={styles.indicatorItem}>
            <Text variant="labelSmall" style={{ color: theme.colors.outline }}>
              最新收盘
            </Text>
            <Text variant="bodyMedium" style={{ fontWeight: '600' }}>
              {klineData[klineData.length - 1].close_price.toFixed(2)}
            </Text>
          </View>
          <View style={styles.indicatorItem}>
            <Text variant="labelSmall" style={{ color: theme.colors.outline }}>
              成交量
            </Text>
            <Text variant="bodyMedium" style={{ fontWeight: '600' }}>
              {(klineData[klineData.length - 1].volume / 10000).toFixed(0)}万
            </Text>
          </View>
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    padding: 16,
    borderRadius: 12,
    marginVertical: 8,
  },
  compactContainer: {
    padding: 12,
    borderRadius: 12,
  },
  compactHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 8,
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    marginBottom: 12,
  },
  stockName: {
    fontWeight: '600',
  },
  periodSelector: {
    marginBottom: 12,
  },
  chartTypeSelector: {
    marginBottom: 12,
  },
  segmentedButton: {
    borderRadius: 8,
  },
  chartSection: {
    alignItems: 'center',
    marginVertical: 8,
  },
  chart: {
    borderRadius: 8,
    marginVertical: 8,
  },
  legendContainer: {
    flexDirection: 'row',
    justifyContent: 'center',
    gap: 20,
    marginTop: 8,
  },
  legendItem: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
  },
  legendDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
  },
  volumeHint: {
    textAlign: 'center',
    opacity: 0.6,
    marginTop: 4,
  },
  indicatorSummary: {
    flexDirection: 'row',
    justifyContent: 'space-around',
    paddingTop: 16,
    borderTopWidth: 1,
    borderTopColor: 'rgba(255, 255, 255, 0.1)',
    marginTop: 8,
  },
  indicatorItem: {
    alignItems: 'center',
  },
  loadingContainer: {
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 40,
  },
});
