/**
 * Expo Web 构建后处理脚本
 * 为 iOS Safari "添加到主屏幕" 添加 apple-touch-icon
 * 
 * 使用方法: node scripts/post-build.js
 */

const fs = require('fs');
const path = require('path');

const distPath = path.join(__dirname, '..', 'dist');
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
    <link rel="manifest" href="/manifest.json">
`;

// 检查是否已经添加过
if (html.includes('apple-touch-icon')) {
  console.log('✅ apple-touch-icon 已存在，跳过');
} else {
  // 在 </head> 前插入
  html = html.replace('</head>', headInserts + '</head>');
  
  // 写回文件
  fs.writeFileSync(indexHtmlPath, html, 'utf-8');
  console.log('✅ 已添加 apple-touch-icon 到 index.html');
}

// 复制 favicon.png 为 apple-touch-icon.png（如果不存在）
const appleTouchIconPath = path.join(distPath, 'apple-touch-icon.png');
const app512IconPath = path.join(distPath, 'app-icon-512.png');

if (!fs.existsSync(appleTouchIconPath)) {
  // 如果有 app-icon-512.png，复制它
  if (fs.existsSync(app512IconPath)) {
    fs.copyFileSync(app512IconPath, appleTouchIconPath);
    console.log('✅ 已复制 app-icon-512.png 为 apple-touch-icon.png');
  } else {
    console.warn('⚠️ 请手动添加 apple-touch-icon.png (180x180 或 512x512)');
  }
}

// 更新 manifest.json
const manifestPath = path.join(distPath, 'manifest.json');
if (fs.existsSync(manifestPath)) {
  let manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf-8'));
  
  // 确保有正确的图标配置
  if (!manifest.icons.some(icon => icon.sizes === '180x180')) {
    manifest.icons.push({
      "src": "/apple-touch-icon.png",
      "sizes": "180x180",
      "type": "image/png",
      "purpose": "any maskable"
    });
    
    fs.writeFileSync(manifestPath, JSON.stringify(manifest, null, 2), 'utf-8');
    console.log('✅ 已更新 manifest.json');
  }
}

console.log('\n🎉 构建后处理完成！');
console.log('💡 提示: 确保 apple-touch-icon.png 是一个正方形图片 (推荐 180x180 或 512x512)');
