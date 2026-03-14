"""
音频混合服务
将背景音乐与播客语音混合
"""
import os
import subprocess
from pathlib import Path
from typing import Optional

# 配置 ffmpeg 路径
import shutil
from pydub import AudioSegment

# 常见的 ffmpeg/ffprobe 系统路径
SYSTEM_FFMPEG_PATHS = ['/usr/bin/ffmpeg', '/usr/local/bin/ffmpeg']
SYSTEM_FFPROBE_PATHS = ['/usr/bin/ffprobe', '/usr/local/bin/ffprobe']

def _find_ffmpeg():
    """查找 ffmpeg 可执行文件路径"""
    # 1. 先尝试 shutil.which
    path = shutil.which('ffmpeg')
    if path:
        return path
    # 2. 再尝试常见系统路径
    import os
    for p in SYSTEM_FFMPEG_PATHS:
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return None

def _find_ffprobe():
    """查找 ffprobe 可执行文件路径"""
    # 1. 先尝试 shutil.which
    path = shutil.which('ffprobe')
    if path:
        return path
    # 2. 再尝试常见系统路径
    import os
    for p in SYSTEM_FFPROBE_PATHS:
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return None

# 配置 pydub 使用的 ffmpeg/ffprobe 路径
ffmpeg_path = _find_ffmpeg()
ffprobe_path = _find_ffprobe()

if ffmpeg_path:
    AudioSegment.converter = ffmpeg_path
    AudioSegment.ffmpeg = ffmpeg_path
    print(f"[AudioMixer] 已配置 ffmpeg: {ffmpeg_path}")
else:
    print("[AudioMixer] 警告: 未找到 ffmpeg")

if ffprobe_path:
    AudioSegment.ffprobe = ffprobe_path
    print(f"[AudioMixer] 已配置 ffprobe: {ffprobe_path}")
else:
    print("[AudioMixer] 警告: 未找到 ffprobe")

from ..config import settings


class AudioMixerService:
    """音频混合服务"""
    
    def __init__(self):
        # 获取项目根目录（backend目录的父目录）
        backend_dir = Path(__file__).resolve().parent.parent.parent
        project_root = backend_dir.parent
        
        # 背景音乐配置 - 使用绝对路径
        self.bgm_dir = project_root / "backend" / "data" / "bgm"
        self.bgm_file = self.bgm_dir / "background.mp3"
        
        print(f"[AudioMixer] BGM目录: {self.bgm_dir}")
        print(f"[AudioMixer] BGM文件: {self.bgm_file}")
        print(f"[AudioMixer] BGM存在: {self.bgm_file.exists()}")
        
        # 混音参数
        self.intro_duration = 4000  # 开头纯音乐时长（毫秒）
        self.outro_duration = 4000  # 结尾纯音乐时长（毫秒）
        self.bgm_volume_reduction = -15  # 背景音乐降低的分贝数
        self.fade_duration = 1000  # 淡入淡出时长（毫秒）
        
        # 确保目录存在
        self.bgm_dir.mkdir(parents=True, exist_ok=True)
    
    def has_bgm(self) -> bool:
        """检查是否有背景音乐文件"""
        return self.bgm_file.exists()
    
    def mix_podcast_with_bgm(self, podcast_path: str, output_path: Optional[str] = None) -> str:
        """
        将播客与背景音乐混合
        
        流程：
        1. 开头4秒：背景音乐正常音量
        2. 4秒后：背景音乐淡入降低音量，播客开始
        3. 播客播放期间：背景音乐维持低音量循环
           - 检测静音段（停顿），在停顿处背景音乐渐强再渐弱
        4. 播客结束：背景音乐淡出回到正常音量
        5. 结尾4秒：背景音乐正常音量后淡出结束
        
        Args:
            podcast_path: 原始播客音频路径
            output_path: 输出路径（可选，默认覆盖原文件）
            
        Returns:
            输出文件路径
        """
        # 确保 ffmpeg 路径已设置（每次调用时检查）
        try:
            import static_ffmpeg
            static_ffmpeg.add_paths()
        except ImportError:
            pass
        
        if not self.has_bgm():
            print("[WARN] 未找到背景音乐文件，跳过混音")
            return podcast_path
        
        if output_path is None:
            output_path = podcast_path
        
        try:
            print(f"[BGM] 开始混音处理...")
            
            # 加载播客音频
            podcast = AudioSegment.from_mp3(podcast_path)
            podcast_duration = len(podcast)  # 毫秒
            print(f"   播客时长: {podcast_duration // 1000} 秒")
            
            # 加载背景音乐
            bgm_original = AudioSegment.from_mp3(str(self.bgm_file))
            print(f"   背景音乐时长: {len(bgm_original) // 1000} 秒")
            
            # 检测播客中的静音段（停顿位置）
            pause_positions = self._detect_pauses(podcast)
            print(f"   检测到 {len(pause_positions)} 个停顿位置")
            
            # 计算总时长（开头纯音乐 + 播客 + 结尾纯音乐）
            total_duration = self.intro_duration + podcast_duration + self.outro_duration
            
            # === 第一步：准备背景音乐轨道（带停顿处渐强效果）===
            bgm_track = self._prepare_bgm_track_with_pauses(bgm_original, total_duration, podcast_duration, pause_positions)
            
            # === 第二步：准备播客轨道（前面加静音以对齐）===
            # 播客前面加上 intro_duration 的静音
            silence_intro = AudioSegment.silent(duration=self.intro_duration)
            silence_outro = AudioSegment.silent(duration=self.outro_duration)
            podcast_track = silence_intro + podcast + silence_outro
            
            # === 第三步：混合两轨 ===
            # 确保两轨长度一致
            if len(bgm_track) != len(podcast_track):
                # 取较短的长度
                min_length = min(len(bgm_track), len(podcast_track))
                bgm_track = bgm_track[:min_length]
                podcast_track = podcast_track[:min_length]
            
            final_audio = bgm_track.overlay(podcast_track)
            
            # === 第四步：最后的淡出处理 ===
            final_audio = final_audio.fade_out(self.fade_duration)
            
            # === 第五步：导出 ===
            final_audio.export(output_path, format="mp3", bitrate="192k")
            
            print(f"[OK] 混音完成: {output_path}")
            print(f"   最终时长: {len(final_audio) // 1000} 秒")
            
            return output_path
            
        except Exception as e:
            print(f"[ERROR] 混音失败: {e}")
            import traceback
            traceback.print_exc()
            return podcast_path
    
    def _detect_pauses(self, audio: AudioSegment) -> list:
        """
        检测音频中的静音段（停顿位置）
        
        返回停顿位置列表，每个元素是 (开始时间ms, 结束时间ms)
        """
        pauses = []
        
        # 将音频分成小块来检测
        chunk_size = 100  # 100ms 的块
        silence_threshold = -32  # dBFS，低于此值认为是静音（放宽阈值以更好检测TTS静音）
        min_pause_duration = 600  # 至少 600ms 的静音才算停顿（降低以捕获更多停顿）
        
        current_pause_start = None
        
        for i in range(0, len(audio), chunk_size):
            chunk = audio[i:i + chunk_size]
            
            # 检查这个块是否是静音
            if chunk.dBFS < silence_threshold or chunk.dBFS == float('-inf'):
                if current_pause_start is None:
                    current_pause_start = i
            else:
                if current_pause_start is not None:
                    pause_duration = i - current_pause_start
                    if pause_duration >= min_pause_duration:
                        pauses.append((current_pause_start, i))
                    current_pause_start = None
        
        # 处理最后一个可能的停顿
        if current_pause_start is not None:
            pause_duration = len(audio) - current_pause_start
            if pause_duration >= min_pause_duration:
                pauses.append((current_pause_start, len(audio)))
        
        return pauses
    
    def _prepare_bgm_track_with_pauses(self, bgm_original: AudioSegment, total_duration: int, 
                                        podcast_duration: int, pause_positions: list) -> AudioSegment:
        """
        准备背景音乐轨道，在停顿处加入渐强效果
        
        结构：
        [正常音量 intro] -> [淡入降低] -> [低音量循环(停顿处渐强)] -> [淡出升高] -> [正常音量 outro]
        """
        # 创建降低音量的背景音乐版本
        bgm_low = bgm_original + self.bgm_volume_reduction  # 降低 15dB
        
        # === 开头部分：正常音量 ===
        intro_full = self.intro_duration - self.fade_duration
        bgm_intro = self._loop_audio(bgm_original, intro_full)
        
        # === 淡入降低部分 ===
        fade_down_segment = self._loop_audio(bgm_original, self.fade_duration)
        fade_down_segment = fade_down_segment.fade(
            from_gain=0,
            to_gain=self.bgm_volume_reduction,
            start=0,
            duration=self.fade_duration
        )
        
        # === 中间低音量部分（播客播放期间）===
        # 先生成基础的低音量背景音乐
        bgm_middle = self._loop_audio(bgm_low, podcast_duration)
        
        # 在停顿位置应用渐强效果
        if pause_positions:
            bgm_middle = self._apply_pause_effects(bgm_middle, bgm_original, pause_positions)
        
        # === 淡出升高部分 ===
        fade_up_segment = self._loop_audio(bgm_low, self.fade_duration)
        fade_up_segment = fade_up_segment.fade(
            from_gain=0,
            to_gain=-self.bgm_volume_reduction,  # 升回正常
            start=0,
            duration=self.fade_duration
        )
        
        # === 结尾部分：正常音量 ===
        outro_full = self.outro_duration - self.fade_duration
        bgm_outro = self._loop_audio(bgm_original, outro_full)
        
        # === 拼接所有部分 ===
        bgm_track = bgm_intro + fade_down_segment + bgm_middle + fade_up_segment + bgm_outro
        
        return bgm_track
    
    def _apply_pause_effects(self, bgm_middle: AudioSegment, bgm_original: AudioSegment, 
                             pause_positions: list) -> AudioSegment:
        """
        在停顿位置应用背景音乐渐强-渐弱效果
        
        效果：停顿时背景音乐音量从低 -> 正常 -> 低，形成"提示"效果
        """
        # 渐强/渐弱的过渡时间
        transition_time = 250  # 250ms（缩短过渡时间，效果更明显）
        # 停顿中间保持正常音量的时间
        hold_time = 400  # 400ms
        
        # 计算每个停顿需要多少额外增益（增强效果）
        gain_boost = -self.bgm_volume_reduction * 1.2  # 提升到略高于正常音量，效果更明显
        
        result = bgm_middle
        
        for pause_start, pause_end in pause_positions:
            pause_duration = pause_end - pause_start
            
            # 如果停顿太短，跳过
            if pause_duration < transition_time * 2 + hold_time:
                continue
            
            try:
                # 计算渐强效果的时间点
                # 渐强开始 -> 渐强结束 -> 保持 -> 渐弱开始 -> 渐弱结束
                fade_in_start = pause_start
                fade_in_end = pause_start + transition_time
                hold_start = fade_in_end
                hold_end = pause_end - transition_time
                fade_out_start = hold_end
                fade_out_end = pause_end
                
                # 对停顿区域应用增益变化
                # 方法：提取停顿区域，应用效果，再覆盖回去
                
                # 渐强部分
                if fade_in_end <= len(result):
                    fade_in_segment = result[fade_in_start:fade_in_end]
                    # 使用 crossfade 思路：混合低音量和正常音量
                    fade_in_segment = fade_in_segment.fade(
                        from_gain=0,
                        to_gain=gain_boost * 0.8,  # 提升到80%，效果更明显
                        start=0,
                        duration=len(fade_in_segment)
                    )
                    result = result[:fade_in_start] + fade_in_segment + result[fade_in_end:]
                
                # 保持部分（增益）
                if hold_end <= len(result) and hold_end > hold_start:
                    hold_segment = result[hold_start:hold_end]
                    hold_segment = hold_segment + (gain_boost * 0.8)  # 提升音量到80%
                    result = result[:hold_start] + hold_segment + result[hold_end:]
                
                # 渐弱部分
                if fade_out_end <= len(result):
                    fade_out_segment = result[fade_out_start:fade_out_end]
                    fade_out_segment = fade_out_segment.fade(
                        from_gain=gain_boost * 0.8,
                        to_gain=0,
                        start=0,
                        duration=len(fade_out_segment)
                    )
                    result = result[:fade_out_start] + fade_out_segment + result[fade_out_end:]
                    
            except Exception as e:
                print(f"[WARN] 处理停顿效果时出错: {e}")
                continue
        
        return result
    
    def _loop_audio(self, audio: AudioSegment, target_duration: int) -> AudioSegment:
        """
        循环音频直到达到目标时长
        
        Args:
            audio: 原始音频
            target_duration: 目标时长（毫秒）
            
        Returns:
            循环后的音频
        """
        if target_duration <= 0:
            return AudioSegment.silent(duration=0)
        
        audio_duration = len(audio)
        
        if audio_duration >= target_duration:
            # 音频够长，直接裁剪
            return audio[:target_duration]
        
        # 需要循环
        result = audio
        while len(result) < target_duration:
            result = result + audio
        
        # 裁剪到精确长度
        return result[:target_duration]


# 单例实例
_audio_mixer: Optional[AudioMixerService] = None


def get_audio_mixer() -> AudioMixerService:
    """获取音频混合服务实例"""
    global _audio_mixer
    if _audio_mixer is None:
        _audio_mixer = AudioMixerService()
    return _audio_mixer
