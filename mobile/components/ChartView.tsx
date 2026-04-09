import React, { useState, useEffect } from 'react';
import { View, StyleSheet, Dimensions, ActivityIndicator, Platform } from 'react-native';
import { Text, SegmentedButtons, useTheme } from 'react-native-paper';
import Svg, { Rect, Line, Path, Text as SvgText } from 'react-native-svg';
import { api } from '@/services/api';
import { useAppTheme } from '@/theme/ThemeContext';

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

// 计算 MA 均线
function calcMA(closes: number[], n: number): (number | null)[] {
  const result: (number | null)[] = [];
  for (let i = 0; i < closes.length; i++) {
    if (i < n - 1) {
      result.push(null);
    } else {
      const sum = closes.slice(i - n + 1, i + 1).reduce((a, b) => a + b, 0);
      result.push(sum / n);
    }
  }
  return result;
}

// 蜡烛图组件
function CandlestickChart({
  data,
  width,
  height,
  colors: themeColors,
  isDark,
}: {
  data: KLineItem[];
  width: number;
  height: number;
  colors: any;
  isDark: boolean;
}) {
  if (data.length === 0) return null;

  const candleAreaHeight = height * 0.65;
  const volumeAreaHeight = height * 0.25;
  const gapHeight = height * 0.04;
  const labelHeight = height * 0.06;
  const paddingLeft = 45;
  const paddingRight = 10;
  const paddingTop = 8;
  const chartWidth = width - paddingLeft - paddingRight;

  const candleWidth = Math.max(2, Math.min(8, (chartWidth / data.length) * 0.6));
  const candleGap = chartWidth / data.length;

  // 价格范围
  const allHigh = data.map((d) => d.high_price);
  const allLow = data.map((d) => d.low_price);
  const priceMax = Math.max(...allHigh);
  const priceMin = Math.min(...allLow);
  const pricePadding = (priceMax - priceMin) * 0.08 || 1;
  const yMax = priceMax + pricePadding;
  const yMin = priceMin - pricePadding;

  // 成交量范围
  const volMax = Math.max(...data.map((d) => d.volume)) || 1;

  // MA 均线
  const closes = data.map((d) => d.close_price);
  const ma5 = calcMA(closes, 5);
  const ma10 = calcMA(closes, 10);
  const ma20 = calcMA(closes, 20);

  const priceToY = (p: number) =>
    paddingTop + ((yMax - p) / (yMax - yMin)) * candleAreaHeight;

  const volToY = (v: number) =>
    paddingTop + candleAreaHeight + gapHeight + volumeAreaHeight * (1 - v / volMax);

  const idxToX = (i: number) => paddingLeft + candleGap * i + candleGap / 2;

  // 生成 MA 路径
  const buildMAPath = (maData: (number | null)[]) => {
    let path = '';
    for (let i = 0; i < maData.length; i++) {
      const val = maData[i];
      if (val === null) continue;
      const x = idxToX(i);
      const y = priceToY(val);
      path += path === '' ? `M${x},${y}` : `L${x},${y}`;
    }
    return path;
  };

  // 价格网格线
  const gridLines = 4;
  const gridPrices: number[] = [];
  for (let i = 0; i <= gridLines; i++) {
    gridPrices.push(yMin + ((yMax - yMin) * i) / gridLines);
  }

  // 日期标签
  const labelStep = Math.max(1, Math.ceil(data.length / 5));
  const dateLabels: { x: number; label: string }[] = [];
  for (let i = 0; i < data.length; i += labelStep) {
    const d = data[i].trade_date;
    if (d && d.includes('-')) {
      const parts = d.split('-');
      dateLabels.push({
        x: idxToX(i),
        label: `${parseInt(parts[1])}/${parseInt(parts[2])}`,
      });
    }
  }

  const gridColor = isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)';
  const labelColor = isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.35)';
  const upColor = '#EF4444';
  const downColor = '#22C55E';

  return (
    <Svg width={width} height={height}>
      {/* 价格区网格线 */}
      {gridPrices.map((price, i) => (
        <React.Fragment key={`grid-${i}`}>
          <Line
            x1={paddingLeft}
            y1={priceToY(price)}
            x2={width - paddingRight}
            y2={priceToY(price)}
            stroke={gridColor}
            strokeWidth={1}
          />
          <SvgText
            x={paddingLeft - 4}
            y={priceToY(price) + 3}
            fontSize={9}
            fill={labelColor}
            textAnchor="end"
          >
            {price.toFixed(2)}
          </SvgText>
        </React.Fragment>
      ))}

      {/* 成交量区分隔线 */}
      <Line
        x1={paddingLeft}
        y1={paddingTop + candleAreaHeight + gapHeight}
        x2={width - paddingRight}
        y2={paddingTop + candleAreaHeight + gapHeight}
        stroke={gridColor}
        strokeWidth={1}
      />

      {/* MA 均线 */}
      {ma20.some((v) => v !== null) && (
        <Path d={buildMAPath(ma20)} stroke="rgba(147,51,234,0.5)" strokeWidth={1} fill="none" />
      )}
      {ma10.some((v) => v !== null) && (
        <Path d={buildMAPath(ma10)} stroke="rgba(239,68,68,0.6)" strokeWidth={1} fill="none" />
      )}
      {ma5.some((v) => v !== null) && (
        <Path d={buildMAPath(ma5)} stroke="rgba(245,158,11,0.7)" strokeWidth={1.2} fill="none" />
      )}

      {/* 蜡烛图 */}
      {data.map((item, i) => {
        const x = idxToX(i);
        const isUp = item.close_price >= item.open_price;
        const color = isUp ? upColor : downColor;
        const bodyTop = priceToY(Math.max(item.open_price, item.close_price));
        const bodyBottom = priceToY(Math.min(item.open_price, item.close_price));
        const bodyHeight = Math.max(1, bodyBottom - bodyTop);

        return (
          <React.Fragment key={`candle-${i}`}>
            {/* 上影线 */}
            <Line
              x1={x}
              y1={priceToY(item.high_price)}
              x2={x}
              y2={bodyTop}
              stroke={color}
              strokeWidth={1}
            />
            {/* 下影线 */}
            <Line
              x1={x}
              y1={bodyBottom}
              x2={x}
              y2={priceToY(item.low_price)}
              stroke={color}
              strokeWidth={1}
            />
            {/* 实体 */}
            <Rect
              x={x - candleWidth / 2}
              y={bodyTop}
              width={candleWidth}
              height={bodyHeight}
              fill={isUp ? color : color}
              stroke={color}
              strokeWidth={0.5}
              rx={0.5}
            />
          </React.Fragment>
        );
      })}

      {/* 成交量柱状图 */}
      {data.map((item, i) => {
        const x = idxToX(i);
        const isUp = item.close_price >= item.open_price;
        const color = isUp ? 'rgba(239,68,68,0.5)' : 'rgba(34,197,94,0.5)';
        const barTop = volToY(item.volume);
        const barBottom = paddingTop + candleAreaHeight + gapHeight + volumeAreaHeight;
        const barHeight = Math.max(1, barBottom - barTop);

        return (
          <Rect
            key={`vol-${i}`}
            x={x - candleWidth / 2}
            y={barTop}
            width={candleWidth}
            height={barHeight}
            fill={color}
            rx={0.5}
          />
        );
      })}

      {/* 日期标签 */}
      {dateLabels.map((dl, i) => (
        <SvgText
          key={`date-${i}`}
          x={dl.x}
          y={height - 2}
          fontSize={9}
          fill={labelColor}
          textAnchor="middle"
        >
          {dl.label}
        </SvgText>
      ))}
    </Svg>
  );
}

export default function ChartView({
  stockCode,
  stockName,
  market = 'A',
  compact = false,
}: ChartViewProps) {
  const { colors, isDark } = useAppTheme();
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

  const displayData = klineData.slice(compact ? -15 : -40);
  const chartWidth = compact ? screenWidth - 64 : screenWidth - 40;
  const chartHeight = compact ? 150 : 260;

  // MA 计算（用全部数据计算，只取显示部分）
  const allCloses = klineData.map((d) => d.close_price);
  const allMA5 = calcMA(allCloses, 5);
  const allMA10 = calcMA(allCloses, 10);
  const latestMA5 = allMA5[allMA5.length - 1];
  const latestMA10 = allMA10[allMA10.length - 1];

  if (isLoading) {
    return (
      <View style={[compact ? styles.compactContainer : styles.container, {
        backgroundColor: isDark ? colors.glassBackground : colors.glassBackground,
        borderColor: isDark ? colors.glassBorder : colors.glassBorder,
      }]}>
        <View style={styles.loadingContainer}>
          <ActivityIndicator size="small" color={colors.primary} />
          <Text style={{ color: colors.onSurfaceVariant, marginTop: 8, fontSize: 12 }}>
            加载K线数据...
          </Text>
        </View>
      </View>
    );
  }

  if (error || displayData.length === 0) {
    return (
      <View style={[compact ? styles.compactContainer : styles.container, {
        backgroundColor: isDark ? colors.glassBackground : colors.glassBackground,
        borderColor: isDark ? colors.glassBorder : colors.glassBorder,
      }]}>
        <View style={styles.loadingContainer}>
          <Text style={{ color: colors.onSurfaceVariant, fontSize: 12 }}>
            {error || '暂无K线数据'}
          </Text>
        </View>
      </View>
    );
  }

  if (compact) {
    return (
      <View style={[styles.compactContainer, {
        backgroundColor: isDark ? colors.glassBackground : colors.glassBackground,
        borderColor: isDark ? colors.glassBorder : colors.glassBorder,
      }]}>
        <CandlestickChart
          data={displayData}
          width={chartWidth}
          height={chartHeight}
          colors={colors}
          isDark={isDark}
        />
      </View>
    );
  }

  return (
    <View style={[styles.container, {
      backgroundColor: isDark ? colors.glassBackground : colors.glassBackground,
      borderColor: isDark ? colors.glassBorder : colors.glassBorder,
    }]}>
      {/* 标题 */}
      <Text style={[styles.title, { color: colors.onSurface }]}>📈 K线走势</Text>

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

      {/* 均线图例 */}
      <View style={styles.legendContainer}>
        <View style={styles.legendItem}>
          <View style={[styles.legendLine, { backgroundColor: 'rgba(245,158,11,0.8)' }]} />
          <Text style={[styles.legendText, { color: colors.onSurfaceVariant }]}>MA5</Text>
        </View>
        <View style={styles.legendItem}>
          <View style={[styles.legendLine, { backgroundColor: 'rgba(239,68,68,0.7)' }]} />
          <Text style={[styles.legendText, { color: colors.onSurfaceVariant }]}>MA10</Text>
        </View>
        <View style={styles.legendItem}>
          <View style={[styles.legendLine, { backgroundColor: 'rgba(147,51,234,0.6)' }]} />
          <Text style={[styles.legendText, { color: colors.onSurfaceVariant }]}>MA20</Text>
        </View>
        <View style={styles.legendItem}>
          <View style={[styles.legendDot, { backgroundColor: '#EF4444' }]} />
          <Text style={[styles.legendText, { color: colors.onSurfaceVariant }]}>涨</Text>
        </View>
        <View style={styles.legendItem}>
          <View style={[styles.legendDot, { backgroundColor: '#22C55E' }]} />
          <Text style={[styles.legendText, { color: colors.onSurfaceVariant }]}>跌</Text>
        </View>
      </View>

      {/* 蜡烛图 */}
      <CandlestickChart
        data={displayData}
        width={chartWidth}
        height={chartHeight}
        colors={colors}
        isDark={isDark}
      />

      {/* 技术指标摘要 */}
      {klineData.length > 0 && (
        <View style={[styles.indicatorSummary, {
          borderTopColor: isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)',
        }]}>
          <View style={styles.indicatorItem}>
            <Text style={[styles.indicatorLabel, { color: colors.onSurfaceVariant }]}>MA5</Text>
            <Text style={[styles.indicatorValue, { color: colors.onSurface }]}>
              {latestMA5 !== null ? latestMA5.toFixed(2) : '--'}
            </Text>
          </View>
          <View style={styles.indicatorItem}>
            <Text style={[styles.indicatorLabel, { color: colors.onSurfaceVariant }]}>MA10</Text>
            <Text style={[styles.indicatorValue, { color: colors.onSurface }]}>
              {latestMA10 !== null ? latestMA10.toFixed(2) : '--'}
            </Text>
          </View>
          <View style={styles.indicatorItem}>
            <Text style={[styles.indicatorLabel, { color: colors.onSurfaceVariant }]}>最新收盘</Text>
            <Text style={[styles.indicatorValue, { color: colors.onSurface }]}>
              {klineData[klineData.length - 1].close_price.toFixed(2)}
            </Text>
          </View>
          <View style={styles.indicatorItem}>
            <Text style={[styles.indicatorLabel, { color: colors.onSurfaceVariant }]}>成交量</Text>
            <Text style={[styles.indicatorValue, { color: colors.onSurface }]}>
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
    borderRadius: 20,
    borderWidth: StyleSheet.hairlineWidth,
    marginBottom: 16,
    ...Platform.select({
      web: { boxShadow: '0 4px 20px rgba(0,0,0,0.06)' },
    }),
  },
  compactContainer: {
    padding: 12,
    borderRadius: 16,
    borderWidth: StyleSheet.hairlineWidth,
  },
  title: {
    fontSize: 17,
    fontWeight: '800',
    letterSpacing: -0.3,
    marginBottom: 12,
  },
  periodSelector: {
    marginBottom: 12,
  },
  segmentedButton: {
    borderRadius: 8,
  },
  legendContainer: {
    flexDirection: 'row',
    justifyContent: 'center',
    gap: 14,
    marginBottom: 8,
  },
  legendItem: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
  },
  legendLine: {
    width: 14,
    height: 2,
    borderRadius: 1,
  },
  legendDot: {
    width: 8,
    height: 8,
    borderRadius: 1,
  },
  legendText: {
    fontSize: 10,
    fontWeight: '600',
  },
  indicatorSummary: {
    flexDirection: 'row',
    justifyContent: 'space-around',
    paddingTop: 14,
    borderTopWidth: 1,
    marginTop: 8,
  },
  indicatorItem: {
    alignItems: 'center',
  },
  indicatorLabel: {
    fontSize: 10,
    fontWeight: '600',
    letterSpacing: 0.3,
    marginBottom: 2,
  },
  indicatorValue: {
    fontSize: 14,
    fontWeight: '800',
  },
  loadingContainer: {
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 40,
  },
});
