from PIL import Image

img = Image.open('assets/apple-touch-icon.png').convert('RGBA')
w, h = img.size
print(f'图片尺寸: {w}x{h}')

pixels = img.load()
for pos, name in [((0,0),'左上'), ((w-1,0),'右上'), ((0,h-1),'左下'), ((w-1,h-1),'右下')]:
    print(f'{name}角像素 RGBA: {pixels[pos[0], pos[1]]}')

def is_border_pixel(rgba):
    r, g, b, a = rgba
    if a < 20:
        return True
    if r > 240 and g > 240 and b > 240:
        return True
    return False

# 找上边界
top = 0
for y in range(h):
    for x in range(0, w, 10):
        if not is_border_pixel(pixels[x, y]):
            top = y
            break
    else:
        continue
    break

# 找下边界
bottom = h - 1
for y in range(h-1, -1, -1):
    for x in range(0, w, 10):
        if not is_border_pixel(pixels[x, y]):
            bottom = y
            break
    else:
        continue
    break

# 找左边界
left = 0
for x in range(w):
    for y in range(0, h, 10):
        if not is_border_pixel(pixels[x, y]):
            left = x
            break
    else:
        continue
    break

# 找右边界
right = w - 1
for x in range(w-1, -1, -1):
    for y in range(0, h, 10):
        if not is_border_pixel(pixels[x, y]):
            right = x
            break
    else:
        continue
    break

print(f'内容区域: 左={left}, 上={top}, 右={right}, 下={bottom}')
print(f'边距: 上={top}, 下={h-1-bottom}, 左={left}, 右={w-1-right}')
print(f'内容尺寸: {right-left+1}x{bottom-top+1}')
