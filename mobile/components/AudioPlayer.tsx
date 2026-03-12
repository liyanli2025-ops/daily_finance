import React from 'react';
import { View, StyleSheet, Pressable } from 'react-native';
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
    currentReportId,
    play,
    pause,
  } = useAudioStore();

  const isCurrentTrack = currentReportId === reportId;
  const isTrackPlaying = isCurrentTrack && isPlaying;

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
            {formatTime(duration)}
          </Text>
        </View>
        {isCurrentTrack && (
          <View style={styles.compactProgress}>
            <ProgressBar
              progress={duration > 0 ? currentPosition / duration : 0}
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
          <ProgressBar
            progress={duration > 0 ? currentPosition / duration : 0}
            color={theme.colors.primary}
            style={styles.progressBar}
          />
          <View style={styles.timeRow}>
            <Text variant="bodySmall" style={{ color: theme.colors.outline }}>
              {isCurrentTrack ? formatTime(currentPosition) : '0:00'}
            </Text>
            <Text variant="bodySmall" style={{ color: theme.colors.outline }}>
              {formatTime(duration)}
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
    marginTop: 4,
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
});
