import React, { useState } from 'react';
import { View, StyleSheet, Dimensions } from 'react-native';
import { Text, SegmentedButtons, useTheme } from 'react-native-paper';
import { LineChart, BarChart } from 'react-native-chart-kit';

const screenWidth = Dimensions.get('window').width;

interface KLineData {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

interface TechnicalIndicators {
  ma5?: number[];
  ma10?: number[];
  ma20?: number[];
  macd?: {
    dif: number[];
    dea: number[];
    macd: number[];
  };
  rsi?: number[];
  kdj?: {
    k: number[];
    d: number[];
    j: number[];
  };
}

interface ChartViewProps {
  stockCode: string;
  stockName: string;
  klineData?: KLineData[];
  indicators?: TechnicalIndicators;
  compact?: boolean;
}

export default function ChartView({
  stockCode,
  stockName,
  klineData = [],
  indicators,
  compact = false,
}: ChartViewProps) {
  const theme = useTheme();
  const [chartType, setChartType] = useState<string>('price');
  const [period, setPeriod] = useState<string>('day');

  // 生成模拟数据用于展示
  const generateMockData = () => {
    const labels = ['3/6', '3/7', '3/8', '3/9', '3/10', '3/11', '3/12'];
    const prices = [25.6, 26.2, 25.8, 26.5, 27.1, 26.8, 27.3];
    const volumes = [1250, 1420, 1180, 1560, 1780, 1450, 1620];
    const ma5 = [25.2, 25.5, 25.8, 26.1, 26.3, 26.5, 26.7];
    const ma10 = [24.8, 25.0, 25.3, 25.5, 25.8, 26.1, 26.3];
    
    return { labels, prices, volumes, ma5, ma10 };
  };

  const mockData = generateMockData();

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
      r: '4',
      strokeWidth: '2',
      stroke: '#2563EB',
    },
    propsForBackgroundLines: {
      stroke: 'rgba(148, 163, 184, 0.2)',
    },
  };

  const chartWidth = compact ? screenWidth - 64 : screenWidth - 32;
  const chartHeight = compact ? 150 : 220;

  if (compact) {
    // 紧凑模式：仅显示价格走势
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
            labels: mockData.labels,
            datasets: [
              {
                data: mockData.prices,
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
            {stockName}
          </Text>
          <Text variant="bodySmall" style={{ color: theme.colors.outline }}>
            {stockCode}
          </Text>
        </View>
      </View>

      {/* 周期选择 */}
      <View style={styles.periodSelector}>
        <SegmentedButtons
          value={period}
          onValueChange={setPeriod}
          buttons={[
            { value: 'day', label: '日K' },
            { value: 'week', label: '周K' },
            { value: 'month', label: '月K' },
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
            { value: 'macd', label: 'MACD' },
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
              labels: mockData.labels,
              datasets: [
                {
                  data: mockData.prices,
                  color: (opacity = 1) => `rgba(37, 99, 235, ${opacity})`,
                  strokeWidth: 2,
                },
                {
                  data: mockData.ma5,
                  color: (opacity = 1) => `rgba(245, 158, 11, ${opacity})`,
                  strokeWidth: 1,
                },
                {
                  data: mockData.ma10,
                  color: (opacity = 1) => `rgba(239, 68, 68, ${opacity})`,
                  strokeWidth: 1,
                },
              ],
              legend: ['价格', 'MA5', 'MA10'],
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
              <Text variant="labelSmall">价格</Text>
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
              labels: mockData.labels,
              datasets: [
                {
                  data: mockData.volumes.map(v => v / 100), // 缩放显示
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

      {chartType === 'macd' && (
        <View style={styles.chartSection}>
          <LineChart
            data={{
              labels: mockData.labels,
              datasets: [
                {
                  data: [0.12, 0.15, 0.08, 0.18, 0.22, 0.16, 0.20],
                  color: (opacity = 1) => `rgba(37, 99, 235, ${opacity})`,
                  strokeWidth: 2,
                },
                {
                  data: [0.10, 0.12, 0.10, 0.13, 0.17, 0.15, 0.17],
                  color: (opacity = 1) => `rgba(245, 158, 11, ${opacity})`,
                  strokeWidth: 2,
                },
              ],
              legend: ['DIF', 'DEA'],
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
              <Text variant="labelSmall">DIF</Text>
            </View>
            <View style={styles.legendItem}>
              <View style={[styles.legendDot, { backgroundColor: '#F59E0B' }]} />
              <Text variant="labelSmall">DEA</Text>
            </View>
          </View>
        </View>
      )}

      {/* 技术指标摘要 */}
      <View style={styles.indicatorSummary}>
        <View style={styles.indicatorItem}>
          <Text variant="labelSmall" style={{ color: theme.colors.outline }}>
            MA5
          </Text>
          <Text variant="bodyMedium" style={{ fontWeight: '600' }}>
            26.70
          </Text>
        </View>
        <View style={styles.indicatorItem}>
          <Text variant="labelSmall" style={{ color: theme.colors.outline }}>
            MA10
          </Text>
          <Text variant="bodyMedium" style={{ fontWeight: '600' }}>
            26.30
          </Text>
        </View>
        <View style={styles.indicatorItem}>
          <Text variant="labelSmall" style={{ color: theme.colors.outline }}>
            RSI
          </Text>
          <Text variant="bodyMedium" style={{ fontWeight: '600', color: '#22C55E' }}>
            58.5
          </Text>
        </View>
        <View style={styles.indicatorItem}>
          <Text variant="labelSmall" style={{ color: theme.colors.outline }}>
            MACD
          </Text>
          <Text variant="bodyMedium" style={{ fontWeight: '600', color: '#EF4444' }}>
            -0.02
          </Text>
        </View>
      </View>
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
});
