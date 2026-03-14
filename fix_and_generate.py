#!/usr/bin/env python
"""
修复并重新生成播客脚本
直接运行此脚本来生成缺失的播客文件
"""
import sys
import os

# 设置项目路径
project_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.join(project_dir, 'backend')
sys.path.insert(0, backend_dir)

# 首先配置 ffmpeg
print("[1/4] 配置 ffmpeg...")
try:
    import static_ffmpeg
    static_ffmpeg.add_paths()
    
    import shutil
    ffmpeg_path = shutil.which('ffmpeg')
    ffprobe_path = shutil.which('ffprobe')
    
    if ffmpeg_path and ffprobe_path:
        from pydub import AudioSegment
        AudioSegment.converter = ffmpeg_path
        AudioSegment.ffmpeg = ffmpeg_path
        AudioSegment.ffprobe = ffprobe_path
        print(f"   ffmpeg: {ffmpeg_path}")
        print(f"   ffprobe: {ffprobe_path}")
    else:
        print("   [ERROR] ffmpeg 路径未找到！")
        sys.exit(1)
except ImportError as e:
    print(f"   [ERROR] 导入失败: {e}")
    sys.exit(1)

print("[2/4] 检查背景音乐文件...")
bgm_path = os.path.join(backend_dir, 'data', 'bgm', 'background.mp3')
if os.path.exists(bgm_path):
    print(f"   BGM存在: {bgm_path}")
else:
    print(f"   [WARN] BGM不存在: {bgm_path}")

print("[3/4] 检查语音文件...")
podcasts_dir = os.path.join(backend_dir, 'data', 'podcasts')
report_id = 'ac49aad3-e268-4002-98cc-d1ae8dd99ece'
voice_path = os.path.join(podcasts_dir, f'{report_id}_voice.mp3')
output_path = os.path.join(podcasts_dir, f'{report_id}.mp3')

# 检查是否有已存在的语音文件可以混音
existing_podcasts = [f for f in os.listdir(podcasts_dir) if f.endswith('.mp3') and not f.endswith('_voice.mp3')]
print(f"   已有播客文件: {len(existing_podcasts)} 个")

# 检查是否有任何可用的语音文件
if os.path.exists(voice_path):
    print(f"   语音文件存在: {voice_path}")
    
    print("[4/4] 开始混音...")
    try:
        voice = AudioSegment.from_mp3(voice_path)
        print(f"   语音时长: {len(voice) // 1000} 秒")
        
        if os.path.exists(bgm_path):
            bgm = AudioSegment.from_mp3(bgm_path)
            print(f"   BGM时长: {len(bgm) // 1000} 秒")
            
            # 简单混音：降低BGM音量后叠加
            bgm_low = bgm - 15  # 降低15dB
            
            # 循环BGM以覆盖整个语音
            full_bgm = bgm_low
            while len(full_bgm) < len(voice):
                full_bgm = full_bgm + bgm_low
            full_bgm = full_bgm[:len(voice)]
            
            # 叠加
            final = full_bgm.overlay(voice)
            final.export(output_path, format='mp3', bitrate='192k')
            print(f"   [OK] 已生成: {output_path}")
        else:
            # 没有BGM，直接复制语音文件
            voice.export(output_path, format='mp3', bitrate='192k')
            print(f"   [OK] 已生成（无BGM）: {output_path}")
    except Exception as e:
        print(f"   [ERROR] 混音失败: {e}")
        import traceback
        traceback.print_exc()
else:
    print(f"   [INFO] 语音文件不存在: {voice_path}")
    print("   需要先通过TTS生成语音...")
    print("   ")
    print("   解决方案：请重启后端服务器以应用代码修复，然后重新生成报告。")
    print("   ")
    print("   步骤：")
    print("   1. 在后端终端按 Ctrl+C 停止服务")
    print("   2. 重新运行 python run.py")
    print("   3. 在网页上点击'生成报告'")

print("完成！")
