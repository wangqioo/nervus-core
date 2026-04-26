import type { CapacitorConfig } from '@capacitor/cli';

const config: CapacitorConfig = {
  appId: 'ai.nervus.app',
  appName: 'Nervus',
  webDir: 'src',

  // 开发时指向局域网 Nervus 服务器（通过 Bonjour 自动发现后动态替换）
  // 生产时留空，使用本地 webDir
  server: {
    // url: 'https://nervus.local',   // 生产：局域网 HTTPS
    androidScheme: 'https',
    allowNavigation: ['nervus.local', '*.nervus.local'],
  },

  ios: {
    scheme: 'Nervus',
    // 后台模式：需要在 Xcode 的 Capabilities 里开启：
    //   - Background fetch
    //   - Background processing
    //   - Audio, AirPlay, and Picture in Picture（录音用）
    //   - Remote notifications
    contentInset: 'always',
  },

  plugins: {
    SplashScreen: {
      launchShowDuration: 1200,
      backgroundColor: '#0d0d0d',
      showSpinner: false,
    },
    StatusBar: {
      style: 'dark',
      backgroundColor: '#0d0d0d',
    },
    LocalNotifications: {
      smallIcon: 'ic_stat_icon',
      iconColor: '#00D4AA',
      sound: 'beep.wav',
    },
    PushNotifications: {
      presentationOptions: ['badge', 'sound', 'alert'],
    },
  },
};

export default config;
