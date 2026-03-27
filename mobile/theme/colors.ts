/**
 * Luminous Lens 设计系统 - 色彩方案
 * 灵感来源：高端玻璃拟态，深紫色主色调
 */

export const LightColors = {
  // 主色
  primary: '#7C4DFF',
  primaryDim: '#6834eb',
  primaryFixed: '#a98fff',
  primaryFixedDim: '#9c7eff',
  primaryContainer: '#a98fff',
  onPrimary: '#FFFFFF',
  onPrimaryContainer: '#280072',

  // 次要色
  secondary: '#7c98ff',
  secondaryDim: '#3367ff',
  secondaryContainer: '#004ee8',
  secondaryFixed: '#c5d0ff',

  // 强调色（金色，用于数据高亮）
  tertiary: '#ffe792',
  tertiaryDim: '#efc900',
  tertiaryContainer: '#ffd709',

  // 错误色
  error: '#ff6e84',
  errorDim: '#d73357',
  errorContainer: '#a70138',
  onErrorContainer: '#ffb2b9',

  // 表面层次（从深到浅，浅色模式）
  background: '#f8f9fc',
  surface: '#fdfdfd',
  surfaceDim: '#e8e9ed',
  surfaceBright: '#fdfdfd',
  surfaceContainerLowest: '#ffffff',
  surfaceContainerLow: '#f2f3f7',
  surfaceContainer: '#ecedf1',
  surfaceContainerHigh: '#e6e7eb',
  surfaceContainerHighest: '#e0e1e5',
  surfaceVariant: '#f0f1f5',

  // 文字色
  onSurface: '#111318',
  onSurfaceVariant: '#5c5e66',
  onBackground: '#111318',

  // 边框与分割
  outline: '#74757a',
  outlineVariant: '#c4c6cf',

  // 反转色
  inverseSurface: '#2e3036',
  inverseOnSurface: '#f0f0f6',
  inversePrimary: '#b6a0ff',

  // 语义色（股票/财经）
  bullish: '#22C55E',     // 看涨/利好 - 绿色
  bearish: '#EF4444',     // 看跌/利空 - 红色
  neutral: '#94A3B8',     // 中性

  // 玻璃效果专用
  glassBackground: 'rgba(255, 255, 255, 0.55)',
  glassBorder: 'rgba(255, 255, 255, 0.5)',
  glassBackgroundStrong: 'rgba(255, 255, 255, 0.7)',
  
  // 渐变色
  gradientStart: '#7e51ff',
  gradientEnd: '#3367ff',

  // TabBar
  tabBarBackground: 'rgba(255, 255, 255, 0.6)',
  tabBarBorder: 'rgba(255, 255, 255, 0.2)',
  tabBarActive: '#7C4DFF',
  tabBarInactive: '#5c5e66',

  // StatusBar
  statusBarStyle: 'dark' as const,
};

export const DarkColors = {
  // 主色
  primary: '#b6a0ff',
  primaryDim: '#7e51ff',
  primaryFixed: '#a98fff',
  primaryFixedDim: '#9c7eff',
  primaryContainer: '#a98fff',
  onPrimary: '#340090',
  onPrimaryContainer: '#280072',

  // 次要色
  secondary: '#7c98ff',
  secondaryDim: '#3367ff',
  secondaryContainer: '#004ee8',
  secondaryFixed: '#c5d0ff',

  // 强调色（金色，用于数据高亮）
  tertiary: '#ffe792',
  tertiaryDim: '#efc900',
  tertiaryContainer: '#ffd709',

  // 错误色
  error: '#ff6e84',
  errorDim: '#d73357',
  errorContainer: '#a70138',
  onErrorContainer: '#ffb2b9',

  // 表面层次（从深到浅，深色模式）
  background: '#08090a',
  surface: '#0c0e12',
  surfaceDim: '#0c0e12',
  surfaceBright: '#292c33',
  surfaceContainerLowest: '#000000',
  surfaceContainerLow: '#111318',
  surfaceContainer: '#171a1f',
  surfaceContainerHigh: '#1d2025',
  surfaceContainerHighest: '#23262c',
  surfaceVariant: '#23262c',

  // 文字色
  onSurface: '#f6f6fc',
  onSurfaceVariant: '#aaabb0',
  onBackground: '#f6f6fc',

  // 边框与分割
  outline: '#74757a',
  outlineVariant: '#46484d',

  // 反转色
  inverseSurface: '#f9f9ff',
  inverseOnSurface: '#53555a',
  inversePrimary: '#6834eb',

  // 语义色（股票/财经）
  bullish: '#4ADE80',     // 看涨/利好 - 绿色（深色模式更亮）
  bearish: '#F87171',     // 看跌/利空 - 红色（深色模式更亮）
  neutral: '#94A3B8',     // 中性

  // 玻璃效果专用
  glassBackground: 'rgba(12, 14, 18, 0.55)',
  glassBorder: 'rgba(255, 255, 255, 0.06)',
  glassBackgroundStrong: 'rgba(12, 14, 18, 0.7)',
  
  // 渐变色
  gradientStart: '#7e51ff',
  gradientEnd: '#3367ff',

  // TabBar
  tabBarBackground: 'rgba(8, 9, 10, 0.6)',
  tabBarBorder: 'rgba(255, 255, 255, 0.05)',
  tabBarActive: '#b6a0ff',
  tabBarInactive: 'rgba(170, 171, 176, 0.6)',

  // StatusBar
  statusBarStyle: 'light' as const,
};

export type AppColors = typeof LightColors;
