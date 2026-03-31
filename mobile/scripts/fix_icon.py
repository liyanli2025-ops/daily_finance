from PIL import Image

# 读取原始图标
img = Image.open('assets/apple-touch-icon.png').convert('RGBA')
w, h = img.size
print(f'原始尺寸: {w}x{h}')

# 裁剪掉白边（内容区域: 左=28, 上=2, 右=1413, 下=1439）
# 为了让图标更大（减少 iOS 自动加的圆角内白边），多裁一点
crop_margin = 15  # 比实际白边再多裁一点，让内容填更满
cropped = img.crop((crop_margin, 0, w - crop_margin, h))
print(f'裁剪后尺寸: {cropped.size}')

# 创建新的正方形画布，用图标的主色调（深蓝）填充背景，避免透明区域显示白色
size = max(cropped.size)
new_img = Image.new('RGBA', (size, size), (15, 32, 65, 255))  # 深蓝色背景

# 居中粘贴
x_offset = (size - cropped.size[0]) // 2
y_offset = (size - cropped.size[1]) // 2
new_img.paste(cropped, (x_offset, y_offset), cropped)

# 导出不同尺寸
# 1024x1024 - 大图标（用于其他用途）
big = new_img.resize((1024, 1024), Image.LANCZOS)
big.save('assets/apple-touch-icon.png')
print('已保存 apple-touch-icon.png (1024x1024)')

# 180x180 - iOS 标准 touch icon
small = new_img.resize((180, 180), Image.LANCZOS)
small.save('assets/apple-touch-icon-180.png')
print('已保存 apple-touch-icon-180.png (180x180)')

# 同步更新 icon.png
icon = new_img.resize((1024, 1024), Image.LANCZOS)
icon.save('assets/icon.png')
print('已保存 icon.png (1024x1024)')

# 复制到 dist
big.save('dist/apple-touch-icon.png')
print('已复制到 dist/apple-touch-icon.png')

print('完成！')
