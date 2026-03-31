import React, { useState, useRef, useEffect, useCallback } from 'react';
import { View, StyleSheet, Pressable, Platform, LayoutChangeEvent, GestureResponderEvent } from 'react-native';
import { Text, useTheme, ProgressBar } from 'react-native-paper';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import { useAudioStore } from '@/stores/audioStore';

interface AudioPlayerProps {
  reportId: string;
  reportTitle: string;
  audioUrl: string;
  duration?: number;
  compact?: boolean;
}

// 可拖动的进度条组件
function SeekableProgressBar({
  progress,
  duration,
  onSeek,
  primaryColor,
  trackColor,
}: {
  progress: number;
  duration: number;
  onSeek: (position: number) => void;
  primaryColor: string;
  trackColor: string;
}) {
  const [isDragging, setIsDragging] = useState(false);
  const [dragProgress, setDragProgress] = useState(0);
  const trackRef = useRef<View>(null);
  const trackRectRef = useRef<{ left: number; width: number } | null>(null);

  // 计算进度值
  const calculateProgress = useCallback((clientX: number): number => {
    if (!trackRectRef.current || trackRectRef.current.width <= 0) return progress;
    const { left, width } = trackRectRef.current;
    const relativeX = clientX - left;
    return Math.max(0, Math.min(relativeX / width, 1));
  }, [progress]);

  // Web 平台使用原生事件
  useEffect(() => {
    if (Platform.OS !== 'web') return;

    // 在 Web 上，React Native Web 会将 View ref 直接映射到 DOM 元素
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
      // 立即 seek 到点击位置
      if (duration > 0) {
        onSeek(newProgress * duration);
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
        onSeek(newProgress * duration);
      }
      setIsDragging(false);
    };

    // Touch events for mobile web
    const handleTouchStart = (e: TouchEvent) => {
      if (e.touches.length !== 1) return;
      e.preventDefault();
      e.stopPropagation();
      updateRect();
      setIsDragging(true);
      const touch = e.touches[0];
      const newProgress = calculateProgress(touch.clientX);
      setDragProgress(newProgress);
      if (duration > 0) {
        onSeek(newProgress * duration);
      }
    };

    const handleTouchMove = (e: TouchEvent) => {
      if (!isDragging || e.touches.length !== 1) return;
      e.preventDefault();
      const touch = e.touches[0];
      const newProgress = calculateProgress(touch.clientX);
      setDragProgress(newProgress);
    };

    const handleTouchEnd = (e: TouchEvent) => {
      if (!isDragging) return;
      e.preventDefault();
      const touch = e.changedTouches[0];
      const newProgress = calculateProgress(touch.clientX);
      if (duration > 0) {
        onSeek(newProgress * duration);
      }
      setIsDragging(false);
    };

    trackElement.addEventListener('mousedown', handleMouseDown);
    trackElement.addEventListener('touchstart', handleTouchStart, { passive: false });
    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('mouseup', handleMouseUp);
    window.addEventListener('touchmove', handleTouchMove, { passive: false });
    window.addEventListener('touchend', handleTouchEnd);

    return () => {
      trackElement.removeEventListener('mousedown', handleMouseDown);
      trackElement.removeEventListener('touchstart', handleTouchStart);
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
      window.removeEventListener('touchmove', handleTouchMove);
      window.removeEventListener('touchend', handleTouchEnd);
    };
  }, [isDragging, duration, onSeek, calculateProgress]);

  // Native 平台使用 Responder 系统
  const handleResponderGrant = (e: GestureResponderEvent) => {
    if (Platform.OS === 'web') return;
    setIsDragging(true);
    const locationX = e.nativeEvent.locationX;
    const width = e.nativeEvent.layout?.width || 1;
    const newProgress = Math.max(0, Math.min(locationX / width, 1));
    setDragProgress(newProgress);
  };

  const handleResponderMove = (e: GestureResponderEvent) => {
    if (Platform.OS === 'web' || !isDragging) return;
    const locationX = e.nativeEvent.locationX;
    const width = e.nativeEvent.layout?.width || 1;
    const newProgress = Math.max(0, Math.min(locationX / width, 1));
    setDragProgress(newProgress);
  };

  const handleResponderRelease = (e: GestureResponderEvent) => {
    if (Platform.OS === 'web') return;
    if (isDragging && duration > 0) {
      const locationX = e.nativeEvent.locationX;
      const width = e.nativeEvent.layout?.width || 1;
      const newProgress = Math.max(0, Math.min(locationX / width, 1));
      onSeek(newProgress * duration);
    }
    setIsDragging(false);
  };

  const displayProgress = isDragging ? dragProgress : progress;

  return (
    <View style={styles.seekableWrapper}>
      <View
        ref={trackRef}
        style={[styles.seekableTrack, { backgroundColor: trackColor }]}
        onStartShouldSetResponder={() => Platform.OS !== 'web'}
        onMoveShouldSetResponder={() => Platform.OS !== 'web'}
        onResponderGrant={handleResponderGrant}
        onResponderMove={handleResponderMove}
        onResponderRelease={handleResponderRelease}
        onResponderTerminate={() => setIsDragging(false)}
      >
        {/* 填充部分 */}
        <View
          style={[
            styles.seekableFill,
            {
              width: `${displayProgress * 100}%`,
              backgroundColor: primaryColor,
            },
          ]}
          pointerEvents="none"
        />
        {/* 拖动把手 */}
        <View
          style={[
            styles.seekableThumb,
            {
              left: `${displayProgress * 100}%`,
              backgroundColor: primaryColor,
              opacity: isDragging ? 1 : 0.9,
              transform: [{ scale: isDragging ? 1.3 : 1 }],
            },
          ]}
          pointerEvents="none"
        />
      </View>
    </View>
  );
}

export default function AudioPlayer({
  reportId,
  reportTitle,
  audioUrl,
  duration = 0,
  compact = false,
}: AudioPlayerProps) {
  const theme = useTheme();
  const {
    isPlaying,
    currentPosition,
    duration: audioDuration,
    currentReportId,
    play,
    pause,
    seekTo,
  } = useAudioStore();

  const isCurrentTrack = currentReportId === reportId;
  const isTrackPlaying = isCurrentTrack && isPlaying;

  // 使用实际音频时长或传入的默认时长
  const effectiveDuration = isCurrentTrack && audioDuration > 0 ? audioDuration : duration;
  const effectivePosition = isCurrentTrack ? currentPosition : 0;
  const progress = effectiveDuration > 0 ? effectivePosition / effectiveDuration : 0;

  const formatTime = (seconds: number) => {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  const handlePlayPause = () => {
    if (isTrackPlaying) {
      pause();
    } else {
      play(reportId, audioUrl);
    }
  };

  const handleSeek = (position: number) => {
    // 如果不是当前轨道，先开始播放
    if (!isCurrentTrack) {
      play(reportId, audioUrl).then(() => {
        seekTo(position);
      });
    } else {
      seekTo(position);
    }
  };

  if (compact) {
    return (
      <Pressable
        style={[styles.compactContainer, { backgroundColor: theme.colors.surfaceVariant }]}
        onPress={handlePlayPause}
      >
        <View style={[styles.compactIcon, { backgroundColor: theme.colors.primaryContainer }]}>
          <MaterialCommunityIcons
            name={isTrackPlaying ? 'pause' : 'play'}
            size={20}
            color={theme.colors.primary}
          />
        </View>
        <View style={styles.compactInfo}>
          <Text variant="bodySmall" numberOfLines={1}>
            {reportTitle}
          </Text>
          <Text variant="bodySmall" style={{ color: theme.colors.outline }}>
            {formatTime(effectiveDuration)}
          </Text>
        </View>
        {isCurrentTrack && (
          <View style={styles.compactProgress}>
            <ProgressBar
              progress={progress}
              color={theme.colors.primary}
              style={{ height: 2, borderRadius: 1 }}
            />
          </View>
        )}
      </Pressable>
    );
  }

  return (
    <View style={[styles.container, { backgroundColor: theme.colors.surfaceVariant }]}>
      <View style={styles.header}>
        <MaterialCommunityIcons name="podcast" size={24} color={theme.colors.primary} />
        <Text variant="titleSmall" style={styles.title}>
          播客音频
        </Text>
      </View>

      <View style={styles.controls}>
        <Pressable
          style={[styles.playButton, { backgroundColor: theme.colors.primaryContainer }]}
          onPress={handlePlayPause}
        >
          <MaterialCommunityIcons
            name={isTrackPlaying ? 'pause' : 'play'}
            size={32}
            color={theme.colors.primary}
          />
        </Pressable>

        <View style={styles.progressSection}>
          {/* 可拖动的进度条 */}
          <SeekableProgressBar
            progress={progress}
            duration={effectiveDuration}
            onSeek={handleSeek}
            primaryColor={theme.colors.primary}
            trackColor={theme.colors.outline + '30'}
          />
          <View style={styles.timeRow}>
            <Text variant="bodySmall" style={{ color: theme.colors.outline }}>
              {formatTime(effectivePosition)}
            </Text>
            <Text variant="bodySmall" style={{ color: theme.colors.outline }}>
              {formatTime(effectiveDuration)}
            </Text>
          </View>
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    padding: 16,
    borderRadius: 12,
    marginVertical: 12,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 12,
  },
  title: {
    marginLeft: 8,
    fontWeight: '600',
  },
  controls: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  playButton: {
    width: 56,
    height: 56,
    borderRadius: 28,
    alignItems: 'center',
    justifyContent: 'center',
  },
  progressSection: {
    flex: 1,
    marginLeft: 16,
  },
  progressBar: {
    height: 4,
    borderRadius: 2,
  },
  timeRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginTop: 8,
  },
  compactContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: 12,
    borderRadius: 12,
  },
  compactIcon: {
    width: 36,
    height: 36,
    borderRadius: 18,
    alignItems: 'center',
    justifyContent: 'center',
  },
  compactInfo: {
    flex: 1,
    marginLeft: 12,
  },
  compactProgress: {
    position: 'absolute',
    bottom: 0,
    left: 0,
    right: 0,
  },
  // 可拖动进度条样式
  seekableWrapper: {
    paddingVertical: 10, // 增加可点击区域
    ...(Platform.OS === 'web' ? { cursor: 'pointer' } : {}),
  },
  seekableTrack: {
    height: 6,
    borderRadius: 3,
    position: 'relative',
    justifyContent: 'center',
    overflow: 'visible',
  },
  seekableFill: {
    position: 'absolute',
    left: 0,
    top: 0,
    bottom: 0,
    borderRadius: 3,
  },
  seekableThumb: {
    position: 'absolute',
    width: 16,
    height: 16,
    borderRadius: 8,
    marginLeft: -8,
    top: -5, // (16 - 6) / 2 = 5，使圆点垂直居中在进度条上
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.2,
    shadowRadius: 3,
    elevation: 3,
  },
});
