import React, { useEffect, useRef, useMemo, useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  Dimensions,
  TouchableOpacity,
  ScrollView,
  Animated,
  Platform,
  Modal,
  FlatList,
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
  const { todayReport, currentReport, recentReports, fetchTodayReport, fetchRecentReports, fetchReport } = useReportStore();
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
  const scrollViewRef = useRef<ScrollView>(null);
  const segmentYPositions = useRef<number[]>([]);
  const segmentsContainerY = useRef<number>(0);
  const [showPlaylist, setShowPlaylist] = useState(false);

  useEffect(() => {
    fetchTodayReport();
    fetchRecentReports();
  }, []);

  // 当播放的报告ID变化时，获取对应的报告详情
  useEffect(() => {
    if (currentReportId && currentReportId !== todayReport?.id) {
      fetchReport(currentReportId);
    }
  }, [currentReportId, todayReport?.id]);

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

  // 获取当前应显示的报告：优先显示正在播放的报告，否则显示今日报告
  const displayReport = useMemo(() => {
    // 如果有正在播放的报告，且 currentReport 已加载
    if (currentReportId && currentReport && currentReport.id === currentReportId) {
      return currentReport;
    }
    // 如果正在播放的是今日报告
    if (currentReportId && todayReport && todayReport.id === currentReportId) {
      return todayReport;
    }
    // 默认显示今日报告
    return todayReport;
  }, [currentReportId, currentReport, todayReport]);

  const handlePlayPause = () => {
    if (isPlaying) {
      pause();
    } else if (displayReport?.podcast_url) {
      play(displayReport.id, displayReport.podcast_url);
    } else if (todayReport?.podcast_url) {
      // 如果当前报告没有音频但今日报告有，播放今日报告
      play(todayReport.id, todayReport.podcast_url);
    } else {
      // 没有音频 URL，audioStore 会显示提示
      play(displayReport?.id || todayReport?.id || '', '');
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

  const isPodcastReady = displayReport?.podcast_status === 'ready';
  const progress = duration > 0 ? currentPosition / duration : 0;

  // 播客章节结构（基于实际播客生成逻辑）
  // 结构：开场白 -> 核心观点 -> 报告正文 -> 跨界热点（可选）-> 结束语
  const podcastChapters = useMemo(() => {
    if (!displayReport || !duration) return [];
    
    const chapters: { name: string; startTime: number; content: string }[] = [];
    const totalDuration = duration;
    
    // 根据报告内容估算各章节时长比例
    const hasCoreCopinions = displayReport.core_opinions && displayReport.core_opinions.length > 0;
    const hasCrossBorder = displayReport.cross_border_events && displayReport.cross_border_events.length > 0;
    
    // 时长分配（基于播客生成逻辑）
    // 开场白约 10%，核心观点约 15%，正文约 50-60%，跨界约 10%（如有），结尾约 10-15%
    let currentTime = 0;
    
    // 1. 开场白（天气 + 日期）
    const openingDuration = totalDuration * 0.10;
    chapters.push({
      name: '开场',
      startTime: currentTime,
      content: '大家好，欢迎收听今日财经播报...',
    });
    currentTime += openingDuration;
    
    // 2. 核心观点
    if (hasCoreCopinions) {
      const opinionsDuration = totalDuration * 0.18;
      chapters.push({
        name: '核心观点',
        startTime: currentTime,
        content: displayReport.core_opinions?.join('\n\n') || '',
      });
      currentTime += opinionsDuration;
    }
    
    // 3. 报告正文/市场分析
    const mainContentDuration = totalDuration * (hasCrossBorder ? 0.45 : 0.55);
    chapters.push({
      name: '深度分析',
      startTime: currentTime,
      content: displayReport.summary || '市场分析...',
    });
    currentTime += mainContentDuration;
    
    // 4. 跨界热点（如果有）
    if (hasCrossBorder) {
      const crossBorderDuration = totalDuration * 0.12;
      chapters.push({
        name: '跨界热点',
        startTime: currentTime,
        content: displayReport.cross_border_events?.map((e: any) => e.title).join('\n') || '',
      });
      currentTime += crossBorderDuration;
    }
    
    // 5. 结束语
    chapters.push({
      name: '总结',
      startTime: currentTime,
      content: '今天的播报就到这里...',
    });
    
    return chapters;
  }, [displayReport, duration]);

  // 文本段落（用于歌词显示）
  const textSegments = useMemo(() => {
    if (!displayReport) return [];
    const segments: { text: string; chapterIndex: number }[] = [];
    
    // 开场
    segments.push({ text: '欢迎收听今日财经播报', chapterIndex: 0 });
    
    // 核心观点
    if (displayReport.core_opinions && displayReport.core_opinions.length > 0) {
      displayReport.core_opinions.forEach((opinion: string, idx: number) => {
        segments.push({ text: `${idx + 1}. ${opinion}`, chapterIndex: 1 });
      });
    }
    
    // 摘要作为主要内容
    if (displayReport.summary) {
      // 将摘要按句子分割
      const sentences = displayReport.summary.split(/[。！？]/).filter((s: string) => s.trim());
      sentences.forEach((sentence: string) => {
        if (sentence.trim()) {
          segments.push({ 
            text: sentence.trim() + '。', 
            chapterIndex: displayReport.core_opinions?.length > 0 ? 2 : 1 
          });
        }
      });
    }
    
    // 重点新闻标题
    if (displayReport.highlights) {
      displayReport.highlights.slice(0, 3).forEach((h: any) => {
        if (h.title) {
          segments.push({ 
            text: h.title, 
            chapterIndex: displayReport.core_opinions?.length > 0 ? 2 : 1 
          });
        }
      });
    }
    
    // 跨界热点
    if (displayReport.cross_border_events && displayReport.cross_border_events.length > 0) {
      displayReport.cross_border_events.forEach((event: any) => {
        segments.push({ 
          text: event.title, 
          chapterIndex: podcastChapters.length - 2 
        });
      });
    }
    
    // 结束语
    segments.push({ text: '今天的播报就到这里，我们明天见！', chapterIndex: podcastChapters.length - 1 });
    
    if (segments.length === 0) {
      return [
        { text: '等待播客内容生成...', chapterIndex: 0 },
        { text: '每天早上 7:00 自动生成财经播客', chapterIndex: 0 },
        { text: '包含市场分析、操作建议、自选股解读等内容', chapterIndex: 0 },
      ];
    }
    
    return segments;
  }, [displayReport, podcastChapters.length]);

  // 当前所在章节
  const currentChapterIndex = useMemo(() => {
    if (podcastChapters.length === 0) return 0;
    for (let i = podcastChapters.length - 1; i >= 0; i--) {
      if (currentPosition >= podcastChapters[i].startTime) {
        return i;
      }
    }
    return 0;
  }, [currentPosition, podcastChapters]);

  // 基于播放进度和章节确定当前高亮段落
  const activeSegmentIndex = useMemo(() => {
    if (textSegments.length === 0) return 0;
    
    // 找到当前章节对应的文本段落
    const segmentsInCurrentChapter = textSegments.filter(
      (s) => s.chapterIndex === currentChapterIndex
    );
    
    if (segmentsInCurrentChapter.length === 0) {
      return Math.min(
        Math.floor(progress * textSegments.length),
        textSegments.length - 1
      );
    }
    
    // 在当前章节内按进度计算
    const chapterStart = podcastChapters[currentChapterIndex]?.startTime || 0;
    const chapterEnd = podcastChapters[currentChapterIndex + 1]?.startTime || duration;
    const chapterProgress = chapterEnd > chapterStart 
      ? (currentPosition - chapterStart) / (chapterEnd - chapterStart) 
      : 0;
    
    const firstSegmentInChapter = textSegments.findIndex(s => s.chapterIndex === currentChapterIndex);
    const segmentOffset = Math.floor(chapterProgress * segmentsInCurrentChapter.length);
    
    return Math.min(
      firstSegmentInChapter + segmentOffset,
      textSegments.length - 1
    );
  }, [progress, textSegments, currentChapterIndex, currentPosition, podcastChapters, duration]);

  // 歌词自动滚动到当前段落
  useEffect(() => {
    if (isPlaying && scrollViewRef.current && segmentYPositions.current[activeSegmentIndex] !== undefined) {
      const targetY = segmentsContainerY.current + segmentYPositions.current[activeSegmentIndex];
      // 滚动到当前段落，让它显示在屏幕上方约 1/3 处
      scrollViewRef.current.scrollTo({
        y: Math.max(0, targetY - SCREEN_HEIGHT * 0.3),
        animated: true,
      });
    }
  }, [activeSegmentIndex, isPlaying]);

  // 获取显示的日期（基于当前播放的报告）
  const dateStr = useMemo(() => {
    if (displayReport?.report_date) {
      const date = new Date(displayReport.report_date);
      return `${date.getMonth() + 1}月${date.getDate()}日`;
    }
    const today = new Date();
    return `${today.getMonth() + 1}月${today.getDate()}日`;
  }, [displayReport?.report_date]);

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
        ref={scrollViewRef}
        style={styles.textCanvas}
        contentContainerStyle={styles.textCanvasContent}
        showsVerticalScrollIndicator={false}
      >
        {isPodcastReady && displayReport && (
          <View style={styles.tagRow}>
            <View style={[styles.tag, { backgroundColor: isDark ? 'rgba(182,160,255,0.1)' : 'rgba(124,77,255,0.08)', borderColor: isDark ? 'rgba(182,160,255,0.2)' : 'rgba(124,77,255,0.15)' }]}>
              <Text style={[styles.tagText, { color: colors.primary }]}>
                AI 财经播报 · {dateStr}
              </Text>
            </View>
          </View>
        )}

        {displayReport && (
          <Text style={[styles.episodeTitle, { color: colors.onSurface }]}>
            {displayReport.title || '每日财经早报'}
          </Text>
        )}

        {/* 文本段落（歌词式显示） */}
        <View
          style={styles.segmentsContainer}
          onLayout={(e) => {
            segmentsContainerY.current = e.nativeEvent.layout.y;
          }}
        >
          {textSegments.map((segment, index) => {
            const isActive = index === activeSegmentIndex;
            const isPast = index < activeSegmentIndex;
            const isFuture = index > activeSegmentIndex;

            return (
              <View
                key={index}
                onLayout={(e) => {
                  segmentYPositions.current[index] = e.nativeEvent.layout.y;
                }}
              >
                <Text
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
                  {segment.text}
                </Text>
              </View>
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
          {/* 章节快捷跳转 */}
          {podcastChapters.length > 0 && isPodcastReady && (
            <View style={styles.chapterNav}>
              <ScrollView 
                horizontal 
                showsHorizontalScrollIndicator={false}
                contentContainerStyle={styles.chapterNavContent}
              >
                {podcastChapters.map((chapter, index) => {
                  const isCurrentChapter = index === currentChapterIndex;
                  return (
                    <TouchableOpacity
                      key={index}
                      style={[
                        styles.chapterButton,
                        {
                          backgroundColor: isCurrentChapter
                            ? (isDark ? 'rgba(182,160,255,0.2)' : 'rgba(124,77,255,0.12)')
                            : (isDark ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.04)'),
                          borderColor: isCurrentChapter
                            ? colors.primary
                            : 'transparent',
                        },
                      ]}
                      onPress={() => seekTo(chapter.startTime)}
                    >
                      <Text
                        style={[
                          styles.chapterButtonText,
                          {
                            color: isCurrentChapter ? colors.primary : colors.onSurfaceVariant,
                            fontWeight: isCurrentChapter ? '700' : '500',
                          },
                        ]}
                      >
                        {chapter.name}
                      </Text>
                      <Text style={[styles.chapterTime, { color: colors.onSurfaceVariant }]}>
                        {formatTime(chapter.startTime)}
                      </Text>
                    </TouchableOpacity>
                  );
                })}
              </ScrollView>
            </View>
          )}

          {/* 进度条（带章节标记） */}
          <View style={styles.progressBarContainer}>
            <View style={[styles.progressTrack, { backgroundColor: isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.08)' }]}>
              {/* 章节标记点 */}
              {podcastChapters.map((chapter, index) => {
                if (index === 0 || !duration) return null;
                const markerPosition = (chapter.startTime / duration) * 100;
                return (
                  <TouchableOpacity
                    key={`marker-${index}`}
                    style={[
                      styles.chapterMarker,
                      {
                        left: `${markerPosition}%`,
                        backgroundColor: index <= currentChapterIndex ? colors.primary : colors.onSurfaceVariant,
                      },
                    ]}
                    onPress={() => seekTo(chapter.startTime)}
                  />
                );
              })}
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

          {/* 时间与当前章节标签 */}
          <View style={styles.timeRow}>
            <Text style={[styles.timeText, { color: colors.onSurfaceVariant }]}>
              {formatTime(currentPosition)}
            </Text>
            <View style={[styles.syncBadge, {
              backgroundColor: isDark ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.04)',
              borderColor: isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.06)',
            }]}>
              <MaterialCommunityIcons name="broadcast" size={10} color={colors.tertiary} />
              <Text style={[styles.syncText, { color: colors.onSurface }]}>
                {podcastChapters[currentChapterIndex]?.name || 'AI 播报'}
              </Text>
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
              onPress={() => setShowPlaylist(true)}
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

      {/* 播客历史浮层 */}
      <Modal
        visible={showPlaylist}
        transparent
        animationType="slide"
        onRequestClose={() => setShowPlaylist(false)}
      >
        <TouchableOpacity
          style={styles.playlistOverlay}
          activeOpacity={1}
          onPress={() => setShowPlaylist(false)}
        >
          <TouchableOpacity activeOpacity={1} style={[styles.playlistSheet, {
            backgroundColor: isDark ? colors.surfaceContainer : colors.surface,
          }]}>
            {/* 拖拽指示条 */}
            <View style={styles.playlistHandle}>
              <View style={[styles.handleBar, {
                backgroundColor: isDark ? 'rgba(255,255,255,0.2)' : 'rgba(0,0,0,0.15)',
              }]} />
            </View>

            {/* 标题栏 */}
            <View style={styles.playlistHeader}>
              <Text style={[styles.playlistTitle, { color: colors.onSurface }]}>
                📻 历史播客
              </Text>
              <TouchableOpacity onPress={() => setShowPlaylist(false)}>
                <MaterialCommunityIcons name="close" size={22} color={colors.onSurfaceVariant} />
              </TouchableOpacity>
            </View>

            {/* 播客列表 */}
            <FlatList
              data={recentReports?.filter((r: any) => r.podcast_status === 'ready') || []}
              keyExtractor={(item: any) => item.id}
              showsVerticalScrollIndicator={false}
              style={styles.playlistList}
              ListEmptyComponent={
                <View style={styles.playlistEmpty}>
                  <MaterialCommunityIcons name="podcast" size={40} color={colors.outline} />
                  <Text style={[styles.playlistEmptyText, { color: colors.outline }]}>
                    暂无历史播客
                  </Text>
                </View>
              }
              renderItem={({ item }: { item: any }) => {
                const isCurrentlyPlaying = currentReportId === item.id;
                const reportDate = item.report_date || item.created_at?.split('T')[0] || '';
                return (
                  <TouchableOpacity
                    style={[styles.playlistItem, {
                      backgroundColor: isCurrentlyPlaying
                        ? (isDark ? 'rgba(182,160,255,0.12)' : 'rgba(124,77,255,0.08)')
                        : 'transparent',
                    }]}
                    onPress={() => {
                      play(item.id, item.podcast_url);
                      setShowPlaylist(false);
                    }}
                  >
                    <View style={[styles.playlistItemIcon, {
                      backgroundColor: isCurrentlyPlaying
                        ? colors.primary
                        : (isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.04)'),
                    }]}>
                      <MaterialCommunityIcons
                        name={isCurrentlyPlaying && isPlaying ? 'equalizer' : 'play'}
                        size={16}
                        color={isCurrentlyPlaying ? '#fff' : colors.onSurfaceVariant}
                      />
                    </View>
                    <View style={styles.playlistItemInfo}>
                      <Text
                        style={[styles.playlistItemTitle, {
                          color: isCurrentlyPlaying ? colors.primary : colors.onSurface,
                        }]}
                        numberOfLines={1}
                      >
                        {item.title || '财经日报'}
                      </Text>
                      <Text style={[styles.playlistItemDate, { color: colors.onSurfaceVariant }]}>
                        {reportDate}
                      </Text>
                    </View>
                    {isCurrentlyPlaying && (
                      <View style={[styles.nowPlayingDot, { backgroundColor: colors.primary }]} />
                    )}
                  </TouchableOpacity>
                );
              }}
            />
          </TouchableOpacity>
        </TouchableOpacity>
      </Modal>
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
    // 章节导航
    chapterNav: {
      paddingVertical: 10,
      borderBottomWidth: StyleSheet.hairlineWidth,
      borderBottomColor: isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.05)',
    },
    chapterNavContent: {
      paddingHorizontal: 16,
      gap: 8,
    },
    chapterButton: {
      paddingHorizontal: 12,
      paddingVertical: 6,
      borderRadius: 12,
      borderWidth: 1,
      alignItems: 'center',
      minWidth: 60,
    },
    chapterButtonText: {
      fontSize: 11,
      letterSpacing: 0.3,
    },
    chapterTime: {
      fontSize: 9,
      opacity: 0.7,
      marginTop: 2,
    },
    // 章节标记点
    chapterMarker: {
      position: 'absolute',
      top: -2,
      width: 7,
      height: 7,
      borderRadius: 4,
      marginLeft: -3,
      zIndex: 5,
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

    // 播客历史浮层
    playlistOverlay: {
      flex: 1,
      justifyContent: 'flex-end',
      paddingBottom: Platform.OS === 'ios' ? 88 : 64, // 给 Tab Bar 留空间
    },
    playlistSheet: {
      maxHeight: SCREEN_HEIGHT * 0.55,
      borderTopLeftRadius: 24,
      borderTopRightRadius: 24,
      paddingBottom: Platform.OS === 'ios' ? 20 : 12,
      borderWidth: StyleSheet.hairlineWidth,
      borderBottomWidth: 0,
      borderColor: isDark ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.08)',
      ...Platform.select({
        ios: {
          shadowColor: '#000',
          shadowOffset: { width: 0, height: -8 },
          shadowOpacity: 0.25,
          shadowRadius: 24,
        },
        android: {
          elevation: 24,
        },
      }),
    },
    playlistHandle: {
      alignItems: 'center',
      paddingVertical: 12,
    },
    handleBar: {
      width: 36,
      height: 4,
      borderRadius: 2,
    },
    playlistHeader: {
      flexDirection: 'row',
      justifyContent: 'space-between',
      alignItems: 'center',
      paddingHorizontal: 24,
      paddingBottom: 16,
    },
    playlistTitle: {
      fontSize: 18,
      fontWeight: '700',
    },
    playlistList: {
      paddingHorizontal: 16,
    },
    playlistEmpty: {
      alignItems: 'center',
      paddingVertical: 40,
      gap: 12,
    },
    playlistEmptyText: {
      fontSize: 14,
    },
    playlistItem: {
      flexDirection: 'row',
      alignItems: 'center',
      paddingVertical: 12,
      paddingHorizontal: 12,
      borderRadius: 12,
      marginBottom: 4,
      gap: 12,
    },
    playlistItemIcon: {
      width: 36,
      height: 36,
      borderRadius: 18,
      alignItems: 'center',
      justifyContent: 'center',
    },
    playlistItemInfo: {
      flex: 1,
      gap: 2,
    },
    playlistItemTitle: {
      fontSize: 15,
      fontWeight: '600',
    },
    playlistItemDate: {
      fontSize: 12,
    },
    nowPlayingDot: {
      width: 6,
      height: 6,
      borderRadius: 3,
    },
  });
}
