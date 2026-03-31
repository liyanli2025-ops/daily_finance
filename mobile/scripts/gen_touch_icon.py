from PIL import Image

# 读取 1024x1024 的大图标
img = Image.open('assets/apple-touch-icon.png').convert('RGBA')
print(f'源图标: {img.size}, 大小未知（需看文件）')

# 创建不带 alpha 的版本（iOS apple-touch-icon 不应该有透明通道）
# 用深蓝色填充背景
bg = Image.new('RGB', img.size, (15, 32, 65))
bg.paste(img, (0, 0), img)  # 用 alpha 通道作为 mask

# 生成 180x180（iOS apple-touch-icon 标准尺寸）
icon_180 = bg.resize((180, 180), Image.LANCZOS)
icon_180.save('dist/apple-touch-icon.png', optimize=True, quality=95)
print(f'已生成 dist/apple-touch-icon.png: 180x180')

# 查看文件大小
import os
size = os.path.getsize('dist/apple-touch-icon.png')
print(f'文件大小: {size / 1024:.1f} KB')

# 同时更新 assets 目录的 180 版本
icon_180.save('assets/apple-touch-icon-180.png', optimize=True, quality=95)
print(f'已更新 assets/apple-touch-icon-180.png')
