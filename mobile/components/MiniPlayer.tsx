import React, { useRef, useEffect, useState, useCallback } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  Image,
  Platform,
  GestureResponderEvent,
} from 'react-native';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import { useAudioStore } from '@/stores/audioStore';
import { useAppTheme } from '@/theme/ThemeContext';
import { router } from 'expo-router';

interface MiniPlayerProps {
  onPress?: () => void;
}

export default function MiniPlayer({ onPress }: MiniPlayerProps) {
  const { colors, isDark } = useAppTheme();
  const {
    isPlaying,
    currentPosition,
    duration,
    currentReportId,
    currentReportTitle,
    currentReportDate,
    currentReportType,
    pause,
    resume,
  } = useAudioStore();

  const [isDragging, setIsDragging] = useState(false);
  const [dragProgress, setDragProgress] = useState(0);
  const trackRef = useRef<View>(null);
  const trackRectRef = useRef<{ left: number; width: number } | null>(null);

  // 如果没有播放内容，不显示
  if (!currentReportId) {
    return null;
  }

  const progress = duration > 0 ? currentPosition / duration : 0;

  // 格式化标题
  const getDisplayTitle = () => {
    if (currentReportDate) {
      const date = new Date(currentReportDate);
      const month = date.getMonth() + 1;
      const day = date.getDate();
      const typeLabel = currentReportType === 'evening' ? '晚报' : '早报';
      return `财经${typeLabel}—${month}月${day}日`;
    }
    return currentReportTitle || '财经播客';
  };

  const handlePlayPause = () => {
    if (isPlaying) {
      pause();
    } else {
      resume();
    }
  };

  const handleNavigateToPodcast = () => {
    if (onPress) {
      onPress();
    } else {
      router.push('/(tabs)/podcast');
    }
  };

  // 计算进度值
  const calculateProgress = useCallback((clientX: number): number => {
    if (!trackRectRef.current || trackRectRef.current.width <= 0) return progress;
    const { left, width } = trackRectRef.current;
    const relativeX = clientX - left;
    return Math.max(0, Math.min(relativeX / width, 1));
  }, [progress]);

  // Web 平台使用原生事件处理进度条拖动
  useEffect(() => {
    if (Platform.OS !== 'web') return;

    const trackElement = trackRef.current as unknown as HTMLElement | null;
    if (!trackElement) return;

    const updateRect = () => {
      const rect = trackElement.getBoundingClientRect();
      trackRectRef.current = { left: rect.left, width: rect.width };
    };

    const handleMouseDown = (e: MouseEvent) => {
      e.preventDefault();
      e.stopPropagation();
      updateRect();
      setIsDragging(true);
      const newProgress = calculateProgress(e.clientX);
      setDragProgress(newProgress);
      if (duration > 0) {
        useAudioStore.getState().seekTo(newProgress * duration);
      }
    };

    const handleMouseMove = (e: MouseEvent) => {
      if (!isDragging) return;
      e.preventDefault();
      const newProgress = calculateProgress(e.clientX);
      setDragProgress(newProgress);
    };

    const handleMouseUp = (e: MouseEvent) => {
      if (!isDragging) return;
      e.preventDefault();
      const newProgress = calculateProgress(e.clientX);
      if (duration > 0) {
        useAudioStore.getState().seekTo(newProgress * duration);
      }
      setIsDragging(false);
    };

    trackElement.addEventListener('mousedown', handleMouseDown);
    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('mouseup', handleMouseUp);

    return () => {
      trackElement.removeEventListener('mousedown', handleMouseDown);
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
    };
  }, [isDragging, duration, calculateProgress]);

  const displayProgress = isDragging ? dragProgress : progress;

  const styles = createStyles(colors, isDark);

  return (
    <View style={styles.container}>
      {/* 顶部进度条 - 增大触摸区域 */}
      <View
        ref={trackRef}
        style={styles.progressTouchArea}
        onStartShouldSetResponder={() => true}
        onMoveShouldSetResponder={() => true}
        onResponderGrant={(e: GestureResponderEvent) => {
          if (Platform.OS === 'web') return;
          setIsDragging(true);
          // 获取触摸位置
          const touch = e.nativeEvent;
          trackRef.current?.measure?.((x, y, width, height, pageX, pageY) => {
            if (width > 0) {
              const relativeX = touch.pageX - pageX;
              const newProgress = Math.max(0, Math.min(relativeX / width, 1));
              setDragProgress(newProgress);
            }
          });
        }}
        onResponderMove={(e: GestureResponderEvent) => {
          if (Platform.OS === 'web') return;
          const touch = e.nativeEvent;
          trackRef.current?.measure?.((x, y, width, height, pageX, pageY) => {
            if (width > 0) {
              const relativeX = touch.pageX - pageX;
              const newProgress = Math.max(0, Math.min(relativeX / width, 1));
              setDragProgress(newProgress);
            }
          });
        }}
        onResponderRelease={(e: GestureResponderEvent) => {
          if (Platform.OS === 'web') return;
          const touch = e.nativeEvent;
          trackRef.current?.measure?.((x, y, width, height, pageX, pageY) => {
            if (width > 0 && duration > 0) {
              const relativeX = touch.pageX - pageX;
              const newProgress = Math.max(0, Math.min(relativeX / width, 1));
              useAudioStore.getState().seekTo(newProgress * duration);
            }
          });
          setIsDragging(false);
        }}
      >
        <View style={styles.progressBar}>
          <View
            style={[
              styles.progressFill,
              {
                width: `${displayProgress * 100}%`,
                backgroundColor: colors.primary,
              },
            ]}
          />
        </View>
      </View>

      {/* 主内容区 */}
      <TouchableOpacity
        style={styles.content}
        onPress={handleNavigateToPodcast}
        activeOpacity={0.7}
      >
        {/* 左侧：小熊图标 */}
        <View style={[styles.iconContainer, { backgroundColor: colors.primaryContainer }]}>
          <Image
            source={require('@/assets/icon.png')}
            style={styles.bearIcon}
            resizeMode="cover"
          />
        </View>

        {/* 中间：标题 */}
        <View style={styles.titleContainer}>
          <Text style={[styles.title, { color: colors.onSurface }]} numberOfLines={1}>
            {getDisplayTitle()}
          </Text>
        </View>

        {/* 右侧：播放/暂停按钮 */}
        <TouchableOpacity
          style={[styles.playButton, { borderColor: colors.primary }]}
          onPress={handlePlayPause}
          hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }}
        >
          <MaterialCommunityIcons
            name={isPlaying ? 'pause' : 'play'}
            size={22}
            color={colors.primary}
            style={!isPlaying ? { marginLeft: 2 } : undefined}
          />
        </TouchableOpacity>
      </TouchableOpacity>
    </View>
  );
}

function createStyles(colors: any, isDark: boolean) {
  return StyleSheet.create({
    container: {
      backgroundColor: isDark ? colors.surfaceContainer : '#FFFFFF',
      borderTopWidth: StyleSheet.hairlineWidth,
      borderTopColor: isDark ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.08)',
      ...Platform.select({
        ios: {
          shadowColor: '#000',
          shadowOffset: { width: 0, height: -2 },
          shadowOpacity: 0.1,
          shadowRadius: 8,
        },
        android: {
          elevation: 8,
        },
      }),
    },
    progressTouchArea: {
      width: '100%',
      paddingVertical: 10, // 增大触摸区域
      justifyContent: 'center',
    },
    progressBar: {
      height: 4,
      backgroundColor: isDark ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.08)',
      width: '100%',
      borderRadius: 2,
    },
    progressFill: {
      height: '100%',
      borderRadius: 1.5,
    },
    content: {
      flexDirection: 'row',
      alignItems: 'center',
      paddingHorizontal: 12,
      paddingVertical: 8,
      gap: 12,
    },
    iconContainer: {
      width: 44,
      height: 44,
      borderRadius: 8,
      overflow: 'hidden',
      alignItems: 'center',
      justifyContent: 'center',
    },
    bearIcon: {
      width: 44,
      height: 44,
    },
    titleContainer: {
      flex: 1,
      justifyContent: 'center',
    },
    title: {
      fontSize: 14,
      fontWeight: '600',
      letterSpacing: -0.2,
    },
    playButton: {
      width: 36,
      height: 36,
      borderRadius: 18,
      borderWidth: 2,
      alignItems: 'center',
      justifyContent: 'center',
    },
  });
}
