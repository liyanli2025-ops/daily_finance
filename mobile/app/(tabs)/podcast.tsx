import React, { useEffect } from 'react';
import { View, ScrollView, StyleSheet, Image } from 'react-native';
import { Text, Card, Button, useTheme, IconButton, ProgressBar } from 'react-native-paper';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import { useAudioStore } from '@/stores/audioStore';
import { useReportStore } from '@/stores/reportStore';

export default function PodcastScreen() {
  const theme = useTheme();
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

  useEffect(() => {
    fetchTodayReport();
  }, []);

  const formatTime = (seconds: number) => {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
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
    const newPosition = forward ? currentPosition + 15 : currentPosition - 15;
    seekTo(Math.max(0, Math.min(newPosition, duration)));
  };

  const cyclePlaybackRate = () => {
    const currentIndex = playbackRates.indexOf(playbackRate);
    const nextIndex = (currentIndex + 1) % playbackRates.length;
    setPlaybackRate(playbackRates[nextIndex]);
  };

  const currentReport = todayReport;
  const isPodcastReady = currentReport?.podcast_status === 'ready';

  return (
    <ScrollView style={[styles.container, { backgroundColor: theme.colors.background }]}>
      {/* 播放器主区域 */}
      <View style={[styles.playerSection, { backgroundColor: theme.colors.surfaceVariant }]}>
        {/* 封面 */}
        <View style={[styles.coverContainer, { backgroundColor: theme.colors.primaryContainer }]}>
          <MaterialCommunityIcons
            name="podcast"
            size={80}
            color={theme.colors.primary}
          />
        </View>

        {/* 报告信息 */}
        <Text variant="titleLarge" style={styles.reportTitle} numberOfLines={2}>
          {currentReport?.title || '暂无播客'}
        </Text>
        <Text variant="bodyMedium" style={{ color: theme.colors.outline, marginTop: 4 }}>
          {currentReport
            ? new Date(currentReport.report_date).toLocaleDateString('zh-CN')
            : '等待生成'}
        </Text>

        {/* 进度条 */}
        {isPodcastReady && (
          <View style={styles.progressContainer}>
            <ProgressBar
              progress={duration > 0 ? currentPosition / duration : 0}
              color={theme.colors.primary}
              style={styles.progressBar}
            />
            <View style={styles.timeContainer}>
              <Text variant="bodySmall" style={{ color: theme.colors.outline }}>
                {formatTime(currentPosition)}
              </Text>
              <Text variant="bodySmall" style={{ color: theme.colors.outline }}>
                {formatTime(duration)}
              </Text>
            </View>
          </View>
        )}

        {/* 控制按钮 */}
        <View style={styles.controlsContainer}>
          {/* 后退15秒 */}
          <IconButton
            icon="rewind-15"
            size={32}
            iconColor={theme.colors.onSurface}
            onPress={() => handleSeek(false)}
            disabled={!isPodcastReady}
          />

          {/* 播放/暂停 */}
          <IconButton
            icon={isPlaying ? 'pause-circle' : 'play-circle'}
            size={72}
            iconColor={isPodcastReady ? theme.colors.primary : theme.colors.outline}
            onPress={handlePlayPause}
            disabled={!isPodcastReady}
          />

          {/* 前进15秒 */}
          <IconButton
            icon="fast-forward-15"
            size={32}
            iconColor={theme.colors.onSurface}
            onPress={() => handleSeek(true)}
            disabled={!isPodcastReady}
          />
        </View>

        {/* 倍速按钮 */}
        <Button
          mode="outlined"
          compact
          style={styles.rateButton}
          labelStyle={{ fontSize: 12 }}
          onPress={cyclePlaybackRate}
          disabled={!isPodcastReady}
        >
          {playbackRate}x 倍速
        </Button>

        {/* 播客状态提示 */}
        {!isPodcastReady && currentReport && (
          <View style={styles.statusContainer}>
            <MaterialCommunityIcons
              name={currentReport.podcast_status === 'generating' ? 'loading' : 'alert-circle-outline'}
              size={20}
              color={theme.colors.outline}
            />
            <Text variant="bodySmall" style={{ color: theme.colors.outline, marginLeft: 8 }}>
              {currentReport.podcast_status === 'generating'
                ? '播客正在生成中...'
                : currentReport.podcast_status === 'failed'
                ? '播客生成失败'
                : '播客尚未生成'}
            </Text>
          </View>
        )}
      </View>

      {/* 章节列表（如果有） */}
      {currentReport?.highlights && currentReport.highlights.length > 0 && (
        <View style={styles.chapterSection}>
          <Text variant="titleMedium" style={styles.sectionTitle}>
            📑 内容章节
          </Text>
          {currentReport.highlights.map((highlight, index) => (
            <Card
              key={index}
              style={[styles.chapterCard, { backgroundColor: theme.colors.surface }]}
            >
              <Card.Content style={styles.chapterContent}>
                <View style={styles.chapterNumber}>
                  <Text variant="bodySmall" style={{ color: theme.colors.primary }}>
                    {index + 1}
                  </Text>
                </View>
                <View style={styles.chapterInfo}>
                  <Text variant="bodyMedium" numberOfLines={2}>
                    {highlight.title}
                  </Text>
                  <Text variant="bodySmall" style={{ color: theme.colors.outline, marginTop: 2 }}>
                    {highlight.source}
                  </Text>
                </View>
              </Card.Content>
            </Card>
          ))}
        </View>
      )}

      {/* 历史播客 */}
      <View style={styles.historySection}>
        <Text variant="titleMedium" style={styles.sectionTitle}>
          📻 往期播客
        </Text>
        {recentReports
          .filter((r) => r.podcast_status === 'ready')
          .slice(0, 10)
          .map((report) => (
            <Card
              key={report.id}
              style={[styles.historyCard, { backgroundColor: theme.colors.surface }]}
              onPress={() => play(report.id, report.podcast_url || '')}
            >
              <Card.Content style={styles.historyContent}>
                <View style={styles.historyIcon}>
                  <MaterialCommunityIcons
                    name={currentReportId === report.id && isPlaying ? 'pause' : 'play'}
                    size={24}
                    color={theme.colors.primary}
                  />
                </View>
                <View style={styles.historyInfo}>
                  <Text variant="bodyMedium" numberOfLines={1}>
                    {report.title}
                  </Text>
                  <Text variant="bodySmall" style={{ color: theme.colors.outline }}>
                    {new Date(report.report_date).toLocaleDateString('zh-CN')} ·{' '}
                    {report.podcast_duration
                      ? `${Math.floor(report.podcast_duration / 60)} 分钟`
                      : ''}
                  </Text>
                </View>
              </Card.Content>
            </Card>
          ))}

        {recentReports.filter((r) => r.podcast_status === 'ready').length === 0 && (
          <View style={styles.emptyHistory}>
            <MaterialCommunityIcons name="podcast" size={48} color={theme.colors.outline} />
            <Text variant="bodyMedium" style={{ color: theme.colors.outline, marginTop: 12 }}>
              暂无历史播客
            </Text>
          </View>
        )}
      </View>

      <View style={{ height: 32 }} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  playerSection: {
    margin: 16,
    padding: 24,
    borderRadius: 20,
    alignItems: 'center',
  },
  coverContainer: {
    width: 160,
    height: 160,
    borderRadius: 16,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 20,
  },
  reportTitle: {
    fontWeight: '700',
    textAlign: 'center',
    paddingHorizontal: 16,
  },
  progressContainer: {
    width: '100%',
    marginTop: 24,
  },
  progressBar: {
    height: 4,
    borderRadius: 2,
  },
  timeContainer: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginTop: 8,
  },
  controlsContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    marginTop: 16,
    gap: 8,
  },
  rateButton: {
    marginTop: 16,
    borderRadius: 20,
  },
  statusContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    marginTop: 16,
  },
  chapterSection: {
    paddingHorizontal: 16,
    marginTop: 8,
  },
  sectionTitle: {
    fontWeight: '600',
    marginBottom: 12,
  },
  chapterCard: {
    marginBottom: 8,
    borderRadius: 12,
  },
  chapterContent: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  chapterNumber: {
    width: 28,
    height: 28,
    borderRadius: 14,
    backgroundColor: 'rgba(108, 99, 255, 0.2)',
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 12,
  },
  chapterInfo: {
    flex: 1,
  },
  historySection: {
    paddingHorizontal: 16,
    marginTop: 24,
  },
  historyCard: {
    marginBottom: 8,
    borderRadius: 12,
  },
  historyContent: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  historyIcon: {
    width: 44,
    height: 44,
    borderRadius: 22,
    backgroundColor: 'rgba(108, 99, 255, 0.15)',
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 12,
  },
  historyInfo: {
    flex: 1,
  },
  emptyHistory: {
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 40,
  },
});
