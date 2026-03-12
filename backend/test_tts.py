"""测试 Edge TTS 是否正常工作"""
import asyncio
import edge_tts
from pathlib import Path

async def test_tts():
    print("开始测试 Edge TTS...")
    
    # 测试文本
    text = "你好，这是一个测试。如果你能听到这段话，说明播客功能正常。"
    
    # 输出路径
    output_dir = Path("./data/podcasts")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "test_tts.mp3"
    
    try:
        # 生成音频
        communicate = edge_tts.Communicate(
            text=text,
            voice="zh-CN-YunxiNeural",  # 云希男声
            rate="+0%",
            volume="+0%"
        )
        
        await communicate.save(str(output_path))
        
        print(f"✅ 播客功能正常！")
        print(f"   测试文件已保存: {output_path}")
        print(f"   文件大小: {output_path.stat().st_size / 1024:.1f} KB")
        
    except Exception as e:
        print(f"❌ 播客功能测试失败: {e}")

if __name__ == "__main__":
    asyncio.run(test_tts())
