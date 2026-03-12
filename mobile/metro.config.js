const { getDefaultConfig } = require('expo/metro-config');

const config = getDefaultConfig(__dirname);

config.resolver.resolveRequest = (context, moduleName, platform) => {
  if (platform === 'web' && ['tty', 'os', 'fs', 'crypto', 'net', 'stream', 'zlib', 'http', 'https', 'child_process', 'path'].includes(moduleName)) {
    return { type: 'empty' };
  }
  return context.resolveRequest(context, moduleName, platform);
};

module.exports = config;
