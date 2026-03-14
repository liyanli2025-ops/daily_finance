#!/usr/bin/env python
"""测试 ffmpeg 是否可用"""
import static_ffmpeg
import shutil
import os

print("测试 static_ffmpeg...")
static_ffmpeg.add_paths()

ffmpeg_path = shutil.which('ffmpeg')
ffprobe_path = shutil.which('ffprobe')

print(f"ffmpeg 路径: {ffmpeg_path}")
print(f"ffprobe 路径: {ffprobe_path}")

if ffmpeg_path:
    print("\n[OK] ffmpeg 已正确配置！")
else:
    print("\n[FAIL] ffmpeg 未找到，需要安装")
    print("请运行: winget install Gyan.FFmpeg")
