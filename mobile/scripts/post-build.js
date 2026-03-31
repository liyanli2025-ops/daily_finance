/**
 * Expo Web 构建后处理脚本
 * 为 iOS Safari "添加到主屏幕" 添加 apple-touch-icon
 * 
 * 使用方法: node scripts/post-build.js
 */

const fs = require('fs');
const path = require('path');

const distPath = path.join(__dirname, '..', 'dist');
const assetsPath = path.join(__dirname, '..', 'assets');
const indexHtmlPath = path.join(distPath, 'index.html');

// 检查 dist/index.html 是否存在
if (!fs.existsSync(indexHtmlPath)) {
  console.error('❌ 找不到 dist/index.html，请先运行 npx expo export --platform web');
  process.exit(1);
}

// 读取 index.html
let html = fs.readFileSync(indexHtmlPath, 'utf-8');

// 需要添加的 meta 和 link 标签
const headInserts = `
  <!-- iOS PWA 支持 -->
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
  <meta name="apple-mobile-web-app-title" content="财经FM">
  <link rel="apple-touch-icon" href="/apple-touch-icon.png">
  <link rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon.png">
  <link rel="apple-touch-icon" sizes="152x152" href="/apple-touch-icon.png">
  <link rel="apple-touch-icon" sizes="120x120" href="/apple-touch-icon.png">
  <link rel="manifest" href="/manifest.json">
`;

// 移除已存在的 apple-touch-icon 链接，然后重新添加完整配置
html = html.replace(/<link rel="apple-touch-icon"[^>]*>/g, '');
html = html.replace(/<meta name="apple-mobile-web-app[^>]*>/g, '');
html = html.replace(/<link rel="manifest"[^>]*>/g, '');

// 在 </head> 前插入
html = html.replace('</head>', headInserts + '</head>');

// 写回文件
fs.writeFileSync(indexHtmlPath, html, 'utf-8');
console.log('✅ 已添加 iOS PWA 配置到 index.html');

// 复制小熊图标为 apple-touch-icon.png
const appleTouchIconPath = path.join(distPath, 'apple-touch-icon.png');
const sourceIconPath = path.join(assetsPath, 'icon.png');

if (fs.existsSync(sourceIconPath)) {
  fs.copyFileSync(sourceIconPath, appleTouchIconPath);
  console.log('✅ 已复制小熊图标为 apple-touch-icon.png');
} else {
  console.warn('⚠️ 找不到 assets/icon.png，请手动添加 apple-touch-icon.png');
}

// 创建/更新 manifest.json
const manifestPath = path.join(distPath, 'manifest.json');
const manifest = {
  "name": "财经FM",
  "short_name": "财经FM",
  "description": "AI驱动的每日财经播报应用",
  "start_url": "/",
  "display": "standalone",
  "background_color": "#ffffff",
  "theme_color": "#7C4DFF",
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
};

fs.writeFileSync(manifestPath, JSON.stringify(manifest, null, 2), 'utf-8');
console.log('✅ 已更新 manifest.json');

console.log('\n🎉 构建后处理完成！');
console.log('💡 添加到主屏幕时将显示小熊图标');
