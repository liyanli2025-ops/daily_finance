import React, { useState, useRef } from 'react';
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
  const [trackWidth, setTrackWidth] = useState(0);
  const [isDragging, setIsDragging] = useState(false);
  const [dragProgress, setDragProgress] = useState(0);
  const trackRef = useRef<View>(null);

  const handleLayout = (e: LayoutChangeEvent) => {
    setTrackWidth(e.nativeEvent.layout.width);
  };

  // 计算位置并触发 seek
  const calculateAndSeek = (pageX: number) => {
    if (trackWidth <= 0 || duration <= 0) return;
    
    // 获取轨道在页面中的位置
    trackRef.current?.measureInWindow((x) => {
      const relativeX = pageX - x;
      const clampedX = Math.max(0, Math.min(relativeX, trackWidth));
      const newProgress = clampedX / trackWidth;
      const newPosition = newProgress * duration;
      onSeek(newPosition);
    });
  };

  // Web 平台直接处理点击
  const handlePressIn = (e: GestureResponderEvent) => {
    if (Platform.OS === 'web') {
      const pageX = (e.nativeEvent as any).pageX;
      calculateAndSeek(pageX);
    }
    setIsDragging(true);
  };

  const handleMove = (e: GestureResponderEvent) => {
    if (!isDragging || trackWidth <= 0) return;
    
    if (Platform.OS === 'web') {
      const pageX = (e.nativeEvent as any).pageX;
      trackRef.current?.measureInWindow((x) => {
        const relativeX = pageX - x;
        const clampedX = Math.max(0, Math.min(relativeX, trackWidth));
        const newProgress = clampedX / trackWidth;
        setDragProgress(newProgress);
      });
    } else {
      const locationX = e.nativeEvent.locationX;
      const clampedX = Math.max(0, Math.min(locationX, trackWidth));
      const newProgress = clampedX / trackWidth;
      setDragProgress(newProgress);
    }
  };

  const handleRelease = (e: GestureResponderEvent) => {
    if (isDragging && duration > 0) {
      if (Platform.OS === 'web') {
        const pageX = (e.nativeEvent as any).pageX;
        calculateAndSeek(pageX);
      } else {
        const locationX = e.nativeEvent.locationX;
        const clampedX = Math.max(0, Math.min(locationX, trackWidth));
        const newProgress = clampedX / trackWidth;
        const newPosition = newProgress * duration;
        onSeek(newPosition);
      }
    }
    setIsDragging(false);
  };

  const displayProgress = isDragging ? dragProgress : progress;

  return (
    <View
      ref={trackRef}
      style={[styles.seekableTrack, { backgroundColor: trackColor }]}
      onLayout={handleLayout}
      onStartShouldSetResponder={() => true}
      onMoveShouldSetResponder={() => true}
      onResponderGrant={handlePressIn}
      onResponderMove={handleMove}
      onResponderRelease={handleRelease}
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
      />
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
  seekableTrack: {
    height: 6,
    borderRadius: 3,
    position: 'relative',
    justifyContent: 'center',
    cursor: Platform.OS === 'web' ? 'pointer' : undefined,
  },
  seekableFill: {
    position: 'absolute',
    left: 0,
    top: 0,
    height: '100%',
    borderRadius: 3,
  },
  seekableThumb: {
    position: 'absolute',
    width: 14,
    height: 14,
    borderRadius: 7,
    marginLeft: -7,
    top: -4,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.2,
    shadowRadius: 3,
    elevation: 3,
  },
});
