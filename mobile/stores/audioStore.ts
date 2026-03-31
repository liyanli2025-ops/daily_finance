import { create } from 'zustand';
import { Audio } from 'expo-av';
import { Platform, Alert } from 'react-native';

interface AudioStore {
  isPlaying: boolean;
  currentPosition: number;
  duration: number;
  playbackRate: number;
  currentReportId: string | null;
  sound: Audio.Sound | null;
  isLoading: boolean;
  error: string | null;

  play: (reportId: string, audioUrl: string) => Promise<void>;
  pause: () => Promise<void>;
  resume: () => Promise<void>;
  stop: () => Promise<void>;
  seekTo: (position: number) => Promise<void>;
  setPlaybackRate: (rate: number) => Promise<void>;
}

export const useAudioStore = create<AudioStore>((set, get) => ({
  isPlaying: false,
  currentPosition: 0,
  duration: 0,
  playbackRate: 1,
  currentReportId: null,
  sound: null,
  isLoading: false,
  error: null,

  play: async (reportId: string, audioUrl: string) => {
    const { sound: currentSound, currentReportId } = get();

    // 检查 URL 是否有效
    if (!audioUrl || audioUrl.trim() === '') {
      set({ error: '播客音频尚未生成' });
      if (Platform.OS === 'web') {
        alert('播客音频尚未生成，请稍后再试');
      } else {
        Alert.alert('提示', '播客音频尚未生成，请稍后再试');
      }
      return;
    }

    // 如果是同一个音频且已暂停，则继续播放
    if (currentReportId === reportId && currentSound) {
      await currentSound.playAsync();
      set({ isPlaying: true });
      return;
    }

    // 停止当前音频
    if (currentSound) {
      await currentSound.unloadAsync();
    }

    set({ isLoading: true, error: null });

    try {
      // 配置音频模式
      await Audio.setAudioModeAsync({
        allowsRecordingIOS: false,
        staysActiveInBackground: true,
        playsInSilentModeIOS: true,
      });

      // 加载新音频
      const { sound } = await Audio.Sound.createAsync(
        { uri: audioUrl },
        { shouldPlay: true, rate: get().playbackRate },
        (status) => {
          if (status.isLoaded) {
            set({
              currentPosition: status.positionMillis / 1000,
              duration: (status.durationMillis ?? 0) / 1000,
              isPlaying: status.isPlaying,
            });

            // 播放完成
            if (status.didJustFinish) {
              set({ isPlaying: false, currentPosition: 0 });
            }
          }
        }
      );

      set({
        sound,
        currentReportId: reportId,
        isPlaying: true,
        isLoading: false,
      });
    } catch (error) {
      console.error('播放音频失败:', error);
      set({ 
        isLoading: false, 
        isPlaying: false,
        error: '播放失败，音频可能不存在或网络问题'
      });
      
      if (Platform.OS === 'web') {
        alert('播放失败：音频文件可能不存在或网络问题');
      } else {
        Alert.alert('播放失败', '音频文件可能不存在或网络问题');
      }
    }
  },

  pause: async () => {
    const { sound } = get();
    if (sound) {
      await sound.pauseAsync();
    }
    set({ isPlaying: false });
  },

  resume: async () => {
    const { sound } = get();
    if (sound) {
      await sound.playAsync();
    }
    set({ isPlaying: true });
  },

  stop: async () => {
    const { sound } = get();
    if (sound) {
      await sound.stopAsync();
      await sound.unloadAsync();
    }
    set({
      sound: null,
      isPlaying: false,
      currentPosition: 0,
      currentReportId: null,
    });
  },

  seekTo: async (position: number) => {
    const { sound } = get();
    if (sound) {
      await sound.setPositionAsync(position * 1000);
    }
    set({ currentPosition: position });
  },

  setPlaybackRate: async (rate: number) => {
    const { sound } = get();
    if (sound) {
      await sound.setRateAsync(rate, true);
    }
    set({ playbackRate: rate });
  },
}));
