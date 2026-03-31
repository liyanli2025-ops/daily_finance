#!/bin/bash
# 构建后处理脚本：修复 PWA 适配问题
# 使用方法：npx expo export --platform web && bash scripts/post-build.sh

DIST_DIR="$(dirname "$0")/../dist"

echo "🔧 正在应用 PWA 适配修改..."

# 1. 修复 viewport
sed -i '' 's|content="width=device-width, initial-scale=1, shrink-to-fit=no"|content="width=device-width, initial-scale=1, minimum-scale=1, maximum-scale=1, user-scalable=no, shrink-to-fit=no, viewport-fit=cover"|' "$DIST_DIR/index.html"

# 2. 替换 CSS reset 样式
python3 -c "
import re
with open('$DIST_DIR/index.html', 'r') as f:
    content = f.read()

old_css = '''    <style id=\"expo-reset\">
      /* These styles make the body full-height */
      html,
      body {
        height: 100%;
      }
      /* These styles disable body scrolling if you are using <ScrollView> */
      body {
        overflow: hidden;
      }
      /* These styles make the root element full-height */
      #root {
        display: flex;
        height: 100%;
        flex: 1;
      }
    </style>'''

new_css = '''    <style id=\"expo-reset\">
      html,
      body {
        height: 100%;
        margin: 0;
        padding: 0;
        width: 100%;
        overflow: hidden;
        -webkit-overflow-scrolling: touch;
        overscroll-behavior: none;
        background-color: #F5F3FF;
      }
      #root {
        display: flex;
        height: 100%;
        width: 100%;
        flex: 1;
      }
    </style>'''

content = content.replace(old_css, new_css)
with open('$DIST_DIR/index.html', 'w') as f:
    f.write(content)
print('  ✅ CSS 样式已更新')
"

# 3. 添加 PWA meta 标签（如果不存在）
if ! grep -q 'apple-mobile-web-app-capable' "$DIST_DIR/index.html"; then
    sed -i '' 's|</head>|  <!-- iOS PWA 支持 -->\n  <meta name="apple-mobile-web-app-capable" content="yes">\n  <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">\n  <meta name="apple-mobile-web-app-title" content="财经FM">\n  <link rel="apple-touch-icon" href="/apple-touch-icon.png">\n  <link rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon.png">\n  <link rel="manifest" href="/manifest.json"></head>|' "$DIST_DIR/index.html"
    echo "  ✅ PWA meta 标签已添加"
fi

# 4. 复制 PWA 资源
cp "$(dirname "$0")/../assets/apple-touch-icon.png" "$DIST_DIR/apple-touch-icon.png" 2>/dev/null && echo "  ✅ apple-touch-icon 已复制"

# 5. 创建 manifest.json
cat > "$DIST_DIR/manifest.json" << 'EOF'
{
  "name": "财经FM",
  "short_name": "财经FM",
  "description": "AI驱动的每日财经播报应用",
  "start_url": "/",
  "display": "standalone",
  "background_color": "#F5F3FF",
  "theme_color": "#7C4DFF",
  "orientation": "portrait",
  "icons": [
    {
      "src": "/apple-touch-icon.png",
      "sizes": "180x180",
      "type": "image/png",
      "purpose": "any maskable"
    },
    {
      "src": "/apple-touch-icon.png",
      "sizes": "192x192",
      "type": "image/png"
    },
    {
      "src": "/apple-touch-icon.png",
      "sizes": "512x512",
      "type": "image/png"
    }
  ]
}
EOF
echo "  ✅ manifest.json 已创建"

echo "🎉 PWA 适配修改完成！"
