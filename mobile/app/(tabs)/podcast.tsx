import React, { useEffect, useRef, useMemo } from 'react';
import {
  View,
  Text,
  StyleSheet,
  Dimensions,
  TouchableOpacity,
  ScrollView,
  Animated,
  Platform,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import { useAudioStore } from '@/stores/audioStore';
import { useReportStore } from '@/stores/reportStore';
import { useAppTheme } from '@/theme/ThemeContext';
import { router } from 'expo-router';

const { width: SCREEN_WIDTH, height: SCREEN_HEIGHT } = Dimensions.get('window');

export default function PodcastScreen() {
  const { colors, isDark } = useAppTheme();
  const { todayReport, recentReports, fetchTodayReport } = useReportStore();
  const {
    isPlaying,
    currentPosition,
    duration,
    playbackRate,
    currentReportId,
    play,
    pause,
    seekTo,
    setPlaybackRate,
  } = useAudioStore();

  const pulseAnim = useRef(new Animated.Value(1)).current;

  useEffect(() => {
    fetchTodayReport();
  }, []);

  // 播放按钮呼吸动画
  useEffect(() => {
    if (isPlaying) {
      const pulse = Animated.loop(
        Animated.sequence([
          Animated.timing(pulseAnim, {
            toValue: 1.08,
            duration: 1500,
            useNativeDriver: true,
          }),
          Animated.timing(pulseAnim, {
            toValue: 1,
            duration: 1500,
            useNativeDriver: true,
          }),
        ])
      );
      pulse.start();
      return () => pulse.stop();
    } else {
      pulseAnim.setValue(1);
    }
  }, [isPlaying]);

  const formatTime = (seconds: number) => {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  const formatTimeRemaining = (seconds: number) => {
    const remaining = Math.max(0, seconds);
    const mins = Math.floor(remaining / 60);
    const secs = Math.floor(remaining % 60);
    return `-${mins}:${secs.toString().padStart(2, '0')}`;
  };

  const playbackRates = [0.75, 1, 1.25, 1.5, 2];

  const handlePlayPause = () => {
    if (isPlaying) {
      pause();
    } else if (todayReport?.podcast_url) {
      play(todayReport.id, todayReport.podcast_url);
    }
  };

  const handleSeek = (forward: boolean) => {
    const offset = forward ? 30 : -10;
    const newPosition = currentPosition + offset;
    seekTo(Math.max(0, Math.min(newPosition, duration)));
  };

  const cyclePlaybackRate = () => {
    const currentIndex = playbackRates.indexOf(playbackRate);
    const nextIndex = (currentIndex + 1) % playbackRates.length;
    setPlaybackRate(playbackRates[nextIndex]);
  };

  const currentReport = todayReport;
  const isPodcastReady = currentReport?.podcast_status === 'ready';
  const progress = duration > 0 ? currentPosition / duration : 0;

  // 模拟播客文本段落（实际应从报告 highlights 中提取）
  const textSegments = useMemo(() => {
    if (!currentReport) return [];
    const segments = [];
    if (currentReport.summary) {
      segments.push(currentReport.summary);
    }
    if (currentReport.highlights) {
      currentReport.highlights.forEach((h: any) => {
        if (h.title) segments.push(h.title);
      });
    }
    if (segments.length === 0) {
      segments.push('等待播客内容生成...');
      segments.push('每天早上 7:00 自动生成财经播客');
      segments.push('包含市场分析、操作建议、自选股解读等内容');
    }
    return segments;
  }, [currentReport]);

  // 基于播放进度确定当前高亮段落
  const activeSegmentIndex = useMemo(() => {
    if (textSegments.length === 0) return 0;
    return Math.min(
      Math.floor(progress * textSegments.length),
      textSegments.length - 1
    );
  }, [progress, textSegments.length]);

  const today = new Date();
  const dateStr = `${today.getMonth() + 1}月${today.getDate()}日`;

  const styles = createStyles(colors, isDark);

  return (
    <View style={styles.container}>
      {/* 氛围背景 */}
      <View style={styles.atmosphereContainer}>
        <View style={[styles.blob, styles.blobPrimary]} />
        <View style={[styles.blob, styles.blobSecondary]} />
        {isDark && <View style={[styles.blob, styles.blobTertiary]} />}
      </View>

      {/* 顶部导航栏 */}
      <SafeAreaView edges={['top']} style={styles.headerSafe}>
        <View style={styles.header}>
          <View style={styles.headerLeft}>
            <View style={[styles.avatar, { backgroundColor: isDark ? colors.surfaceContainerHigh : colors.surfaceContainerLow }]}>
              <MaterialCommunityIcons name="account" size={20} color={colors.primary} />
            </View>
            <Text style={[styles.headerDate, { color: colors.primary }]}>{dateStr}</Text>
          </View>
          <TouchableOpacity onPress={() => {}}>
            <MaterialCommunityIcons name="magnify" size={24} color={colors.onSurfaceVariant} />
          </TouchableOpacity>
        </View>
      </SafeAreaView>

      {/* 主内容：滚动文本区 */}
      <ScrollView
        style={styles.textCanvas}
        contentContainerStyle={styles.textCanvasContent}
        showsVerticalScrollIndicator={false}
      >
        {isPodcastReady && currentReport && (
          <View style={styles.tagRow}>
            <View style={[styles.tag, { backgroundColor: isDark ? 'rgba(182,160,255,0.1)' : 'rgba(124,77,255,0.08)', borderColor: isDark ? 'rgba(182,160,255,0.2)' : 'rgba(124,77,255,0.15)' }]}>
              <Text style={[styles.tagText, { color: colors.primary }]}>
                AI 财经播报 · {dateStr}
              </Text>
            </View>
          </View>
        )}

        {currentReport && (
          <Text style={[styles.episodeTitle, { color: colors.onSurface }]}>
            {currentReport.title || '每日财经早报'}
          </Text>
        )}

        {/* 文本段落（歌词式显示） */}
        <View style={styles.segmentsContainer}>
          {textSegments.map((text, index) => {
            const isActive = index === activeSegmentIndex;
            const isPast = index < activeSegmentIndex;
            const isFuture = index > activeSegmentIndex;

            return (
              <Text
                key={index}
                style={[
                  styles.segmentText,
                  isActive && {
                    color: colors.primary,
                    fontSize: 26,
                    fontWeight: '700',
                    opacity: 1,
                  },
                  isPast && {
                    color: colors.onSurfaceVariant,
                    opacity: 0.3,
                  },
                  isFuture && {
                    color: colors.onSurfaceVariant,
                    opacity: isDark ? 0.15 : 0.2,
                  },
                ]}
              >
                {text}
              </Text>
            );
          })}
        </View>

        {/* 底部空间留给播放器 */}
        <View style={{ height: 280 }} />
      </ScrollView>

      {/* 底部播放器控制面板 */}
      <View style={styles.playerOverlay}>
        <View style={[styles.playerPanel, {
          backgroundColor: isDark ? colors.glassBackgroundStrong : colors.glassBackgroundStrong,
          borderColor: isDark ? colors.glassBorder : colors.glassBorder,
        }]}>
          {/* 进度条 */}
          <View style={styles.progressBarContainer}>
            <View style={[styles.progressTrack, { backgroundColor: isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.08)' }]}>
              <View
                style={[
                  styles.progressFill,
                  {
                    width: `${progress * 100}%`,
                    backgroundColor: colors.primary,
                  },
                ]}
              />
              <View
                style={[
                  styles.progressThumb,
                  {
                    left: `${progress * 100}%`,
                    backgroundColor: colors.primary,
                    borderColor: colors.surface,
                  },
                ]}
              />
            </View>
          </View>

          {/* 时间与标签 */}
          <View style={styles.timeRow}>
            <Text style={[styles.timeText, { color: colors.onSurfaceVariant }]}>
              {formatTime(currentPosition)}
            </Text>
            <View style={[styles.syncBadge, {
              backgroundColor: isDark ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.04)',
              borderColor: isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.06)',
            }]}>
              <MaterialCommunityIcons name="broadcast" size={10} color={colors.tertiary} />
              <Text style={[styles.syncText, { color: colors.onSurface }]}>AI 播报</Text>
            </View>
            <Text style={[styles.timeText, { color: colors.onSurfaceVariant }]}>
              {duration > 0 ? formatTimeRemaining(duration - currentPosition) : '--:--'}
            </Text>
          </View>

          {/* 控制按钮 */}
          <View style={styles.controlsRow}>
            {/* 倍速 */}
            <TouchableOpacity
              style={[styles.sideButton, {
                backgroundColor: isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.05)',
              }]}
              onPress={cyclePlaybackRate}
              disabled={!isPodcastReady}
            >
              <Text style={[styles.rateText, { color: colors.onSurfaceVariant }]}>
                {playbackRate}x
              </Text>
            </TouchableOpacity>

            {/* 核心播放控制 */}
            <View style={styles.coreControls}>
              <TouchableOpacity
                onPress={() => handleSeek(false)}
                disabled={!isPodcastReady}
                style={styles.seekButton}
              >
                <MaterialCommunityIcons
                  name="rewind-10"
                  size={26}
                  color={isPodcastReady ? colors.onSurfaceVariant : colors.outline}
                />
              </TouchableOpacity>

              <Animated.View style={{ transform: [{ scale: pulseAnim }] }}>
                <TouchableOpacity
                  style={[styles.playButton, { backgroundColor: colors.primary }]}
                  onPress={handlePlayPause}
                  disabled={!isPodcastReady}
                  activeOpacity={0.85}
                >
                  <MaterialCommunityIcons
                    name={isPlaying ? 'pause' : 'play'}
                    size={36}
                    color={isDark ? colors.onPrimary : '#FFFFFF'}
                    style={!isPlaying ? { marginLeft: 3 } : undefined}
                  />
                </TouchableOpacity>
              </Animated.View>

              <TouchableOpacity
                onPress={() => handleSeek(true)}
                disabled={!isPodcastReady}
                style={styles.seekButton}
              >
                <MaterialCommunityIcons
                  name="fast-forward-30"
                  size={26}
                  color={isPodcastReady ? colors.onSurfaceVariant : colors.outline}
                />
              </TouchableOpacity>
            </View>

            {/* 播放列表 */}
            <TouchableOpacity
              style={[styles.sideButton, {
                backgroundColor: isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.05)',
              }]}
              onPress={() => {
                // 导航到历史列表（当前Tab下滚动到往期）
              }}
            >
              <MaterialCommunityIcons
                name="playlist-play"
                size={22}
                color={colors.onSurfaceVariant}
              />
            </TouchableOpacity>
          </View>
        </View>
      </View>
    </View>
  );
}

function createStyles(colors: any, isDark: boolean) {
  return StyleSheet.create({
    container: {
      flex: 1,
      backgroundColor: colors.background,
    },

    // 氛围背景
    atmosphereContainer: {
      ...StyleSheet.absoluteFillObject,
      overflow: 'hidden',
    },
    blob: {
      position: 'absolute',
      borderRadius: 999,
    },
    blobPrimary: {
      width: SCREEN_WIDTH * 0.7,
      height: SCREEN_WIDTH * 0.7,
      top: -SCREEN_WIDTH * 0.15,
      left: -SCREEN_WIDTH * 0.15,
      backgroundColor: isDark ? 'rgba(182,160,255,0.08)' : 'rgba(124,77,255,0.08)',
    },
    blobSecondary: {
      width: SCREEN_WIDTH * 0.6,
      height: SCREEN_WIDTH * 0.6,
      bottom: SCREEN_HEIGHT * 0.1,
      right: -SCREEN_WIDTH * 0.1,
      backgroundColor: isDark ? 'rgba(51,103,255,0.06)' : 'rgba(124,77,255,0.05)',
    },
    blobTertiary: {
      width: SCREEN_WIDTH * 0.35,
      height: SCREEN_WIDTH * 0.35,
      top: SCREEN_HEIGHT * 0.3,
      right: SCREEN_WIDTH * 0.1,
      backgroundColor: 'rgba(255,231,146,0.04)',
    },

    // 顶部导航
    headerSafe: {
      zIndex: 50,
    },
    header: {
      flexDirection: 'row',
      justifyContent: 'space-between',
      alignItems: 'center',
      paddingHorizontal: 24,
      paddingVertical: 12,
    },
    headerLeft: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 12,
    },
    avatar: {
      width: 36,
      height: 36,
      borderRadius: 18,
      alignItems: 'center',
      justifyContent: 'center',
      borderWidth: StyleSheet.hairlineWidth,
      borderColor: isDark ? 'rgba(255,255,255,0.1)' : 'rgba(124,77,255,0.15)',
    },
    headerDate: {
      fontSize: 17,
      fontWeight: '700',
      letterSpacing: -0.3,
    },

    // 文本区
    textCanvas: {
      flex: 1,
      zIndex: 10,
    },
    textCanvasContent: {
      paddingHorizontal: 28,
      paddingTop: 8,
    },
    tagRow: {
      marginBottom: 12,
    },
    tag: {
      alignSelf: 'flex-start',
      paddingHorizontal: 12,
      paddingVertical: 5,
      borderRadius: 999,
      borderWidth: 1,
    },
    tagText: {
      fontSize: 9,
      fontWeight: '800',
      letterSpacing: 1.5,
      textTransform: 'uppercase',
    },
    episodeTitle: {
      fontSize: 28,
      fontWeight: '800',
      letterSpacing: -0.5,
      lineHeight: 36,
      marginBottom: 28,
    },
    segmentsContainer: {
      gap: 28,
    },
    segmentText: {
      fontSize: 22,
      fontWeight: '500',
      lineHeight: 34,
    },

    // 底部播放器
    playerOverlay: {
      position: 'absolute',
      bottom: Platform.OS === 'ios' ? 100 : 76,
      left: 0,
      right: 0,
      zIndex: 40,
      paddingHorizontal: 16,
    },
    playerPanel: {
      borderRadius: 28,
      overflow: 'hidden',
      borderWidth: StyleSheet.hairlineWidth,
      // 在 iOS 上利用 blur
      ...Platform.select({
        ios: {
          shadowColor: isDark ? '#7C4DFF' : '#000',
          shadowOffset: { width: 0, height: 8 },
          shadowOpacity: isDark ? 0.15 : 0.08,
          shadowRadius: 24,
        },
        android: {
          elevation: 12,
        },
      }),
    },
    progressBarContainer: {
      paddingHorizontal: 0,
    },
    progressTrack: {
      height: 3,
      width: '100%',
      position: 'relative',
    },
    progressFill: {
      position: 'absolute',
      top: 0,
      left: 0,
      height: '100%',
    },
    progressThumb: {
      position: 'absolute',
      top: -4,
      width: 10,
      height: 10,
      borderRadius: 5,
      borderWidth: 2,
      marginLeft: -5,
    },
    timeRow: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      paddingHorizontal: 24,
      paddingTop: 16,
      marginBottom: 16,
    },
    timeText: {
      fontSize: 10,
      fontWeight: '700',
      letterSpacing: 1,
      fontVariant: ['tabular-nums'],
    },
    syncBadge: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 4,
      paddingHorizontal: 10,
      paddingVertical: 4,
      borderRadius: 999,
      borderWidth: StyleSheet.hairlineWidth,
    },
    syncText: {
      fontSize: 8,
      fontWeight: '900',
      letterSpacing: 1.5,
      textTransform: 'uppercase',
    },
    controlsRow: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      paddingHorizontal: 20,
      paddingBottom: 20,
      gap: 12,
    },
    sideButton: {
      width: 40,
      height: 40,
      borderRadius: 20,
      alignItems: 'center',
      justifyContent: 'center',
    },
    rateText: {
      fontSize: 10,
      fontWeight: '800',
    },
    coreControls: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 24,
    },
    seekButton: {
      padding: 4,
    },
    playButton: {
      width: 64,
      height: 64,
      borderRadius: 32,
      alignItems: 'center',
      justifyContent: 'center',
      ...Platform.select({
        ios: {
          shadowColor: '#7C4DFF',
          shadowOffset: { width: 0, height: 4 },
          shadowOpacity: 0.3,
          shadowRadius: 12,
        },
        android: {
          elevation: 8,
        },
      }),
    },
  });
}
