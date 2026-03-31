import React from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  Image,
  Platform,
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
    currentReportDate,
    currentReportType,
    pause,
    resume,
  } = useAudioStore();

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
    return '财经播客';
  };

  const handlePlayPause = (e: any) => {
    e.stopPropagation();
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

  return (
    <View style={styles.wrapper}>
      <TouchableOpacity
        style={[
          styles.container,
          {
            backgroundColor: isDark ? 'rgba(40, 40, 45, 0.95)' : 'rgba(255, 255, 255, 0.95)',
          }
        ]}
        onPress={handleNavigateToPodcast}
        activeOpacity={0.9}
      >
        {/* 左侧：小熊图标 - 使用小尺寸图标加快加载 */}
        <View style={styles.iconContainer}>
          <Image
            source={require('@/assets/icon-small.png')}
            style={styles.bearIcon}
            resizeMode="cover"
          />
        </View>

        {/* 中间：标题 */}
        <View style={styles.titleContainer}>
          <Text 
            style={[styles.title, { color: isDark ? '#FFFFFF' : '#1a1a1a' }]} 
            numberOfLines={1}
          >
            {getDisplayTitle()}
          </Text>
        </View>

        {/* 右侧：播放/暂停按钮 */}
        <TouchableOpacity
          style={[styles.playButton, { borderColor: colors.primary }]}
          onPress={handlePlayPause}
          hitSlop={{ top: 12, bottom: 12, left: 12, right: 12 }}
        >
          <MaterialCommunityIcons
            name={isPlaying ? 'pause' : 'play'}
            size={24}
            color={colors.primary}
            style={!isPlaying ? { marginLeft: 2 } : undefined}
          />
        </TouchableOpacity>

        {/* 底部进度条 - 紧贴底部 */}
        <View style={styles.progressContainer}>
          <View 
            style={[
              styles.progressFill, 
              { 
                width: `${progress * 100}%`,
                backgroundColor: colors.primary,
              }
            ]} 
          />
        </View>
      </TouchableOpacity>
    </View>
  );
}

const styles = StyleSheet.create({
  wrapper: {
    paddingHorizontal: 12,
    paddingBottom: 8,
  },
  container: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 12,
    paddingTop: 10,
    paddingBottom: 14, // 为底部进度条留出空间
    borderRadius: 16,
    position: 'relative',
    overflow: 'hidden',
    ...Platform.select({
      ios: {
        shadowColor: '#000',
        shadowOffset: { width: 0, height: 4 },
        shadowOpacity: 0.15,
        shadowRadius: 12,
      },
      android: {
        elevation: 8,
      },
      web: {
        boxShadow: '0 4px 20px rgba(0, 0, 0, 0.12)',
      },
    }),
  },
  iconContainer: {
    width: 44,
    height: 44,
    borderRadius: 10,
    overflow: 'hidden',
  },
  bearIcon: {
    width: 44,
    height: 44,
  },
  titleContainer: {
    flex: 1,
    marginLeft: 12,
    justifyContent: 'center',
  },
  title: {
    fontSize: 15,
    fontWeight: '600',
    letterSpacing: -0.3,
  },
  playButton: {
    width: 40,
    height: 40,
    borderRadius: 20,
    borderWidth: 2,
    alignItems: 'center',
    justifyContent: 'center',
    marginLeft: 12,
  },
  progressContainer: {
    position: 'absolute',
    bottom: 0,
    left: 0,
    right: 0,
    height: 3,
    backgroundColor: 'rgba(0, 0, 0, 0.08)',
    borderBottomLeftRadius: 16,
    borderBottomRightRadius: 16,
    overflow: 'hidden',
  },
  progressFill: {
    height: '100%',
  },
});
