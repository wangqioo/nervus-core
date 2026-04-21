/**
 * nervus-bridge.js
 * Nervus iOS Shell — 原生插件 JS 桥接层
 *
 * 提供以下能力：
 *  - NervusDiscovery  : Bonjour/mDNS 发现局域网 Nervus 服务器
 *  - PhotoLibrary     : 监听相册新照片，上传到 photo-scanner
 *  - AudioRecorder    : 录制会议音频，上传到 meeting-notes
 *  - BackgroundSync   : 后台拉取通知、推送本地提醒
 *
 * 使用前需通过 window.Nervus.init() 初始化，自动发现服务器地址。
 */

const { Capacitor } = window;

// ── 工具：注册原生插件 ──────────────────────────────────

function getPlugin(name) {
  if (Capacitor && Capacitor.Plugins && Capacitor.Plugins[name]) {
    return Capacitor.Plugins[name];
  }
  // Web/开发环境 mock
  console.warn(`[NervusBridge] 插件 ${name} 未注册，使用 mock`);
  return null;
}

// ── 状态 ──────────────────────────────────────────────

const _state = {
  serverBase: null,        // 如 "https://nervus.local"
  deviceId: null,
  initialized: false,
  photoWatchActive: false,
  recordingActive: false,
};

// ── 1. NervusDiscovery — 局域网服务发现 ──────────────────

const NervusDiscovery = {
  /**
   * 扫描局域网，发现 _nervus._tcp 服务
   * 返回 { host, port, addresses }
   */
  async scan(timeoutMs = 5000) {
    const plugin = getPlugin('NervusDiscoveryPlugin');
    if (!plugin) {
      // 开发环境：尝试 localhost
      return { host: 'localhost', port: 8090, addresses: ['127.0.0.1'] };
    }
    return plugin.scan({ timeoutMs });
  },

  /**
   * 停止扫描
   */
  async stop() {
    const plugin = getPlugin('NervusDiscoveryPlugin');
    if (plugin) await plugin.stop();
  },

  /**
   * 监听服务出现/消失事件
   * callback({ type: 'found'|'lost', host, port })
   */
  addListener(callback) {
    const plugin = getPlugin('NervusDiscoveryPlugin');
    if (plugin) {
      return plugin.addListener('serviceChange', callback);
    }
    return { remove: () => {} };
  },
};

// ── 2. PhotoLibrary — 相册监听 ────────────────────────

const PhotoLibrary = {
  /**
   * 请求相册访问权限
   * 返回 { granted: boolean, limited: boolean }
   */
  async requestPermission() {
    const plugin = getPlugin('PhotoLibraryPlugin');
    if (!plugin) return { granted: true, limited: false };
    return plugin.requestPermission();
  },

  /**
   * 启动相册新照片监听
   * 有新照片时自动上传到 Nervus photo-scanner
   * callback({ photoPath, localIdentifier, creationDate })
   */
  async startWatching(callback) {
    if (_state.photoWatchActive) return;
    const plugin = getPlugin('PhotoLibraryPlugin');
    if (!plugin) {
      console.warn('[NervusBridge] PhotoLibraryPlugin mock：无法监听相册');
      return;
    }
    await plugin.startWatching();
    plugin.addListener('newPhoto', async (data) => {
      // 上传到 photo-scanner
      try {
        await PhotoLibrary._uploadPhoto(data);
      } catch (e) {
        console.error('[NervusBridge] 照片上传失败', e);
      }
      if (callback) callback(data);
    });
    _state.photoWatchActive = true;
  },

  async stopWatching() {
    const plugin = getPlugin('PhotoLibraryPlugin');
    if (plugin) await plugin.stopWatching();
    _state.photoWatchActive = false;
  },

  /**
   * 从相册加载最近 N 张照片（供手动触发分析用）
   */
  async getRecentPhotos(limit = 20) {
    const plugin = getPlugin('PhotoLibraryPlugin');
    if (!plugin) return [];
    return plugin.getRecentPhotos({ limit });
  },

  /**
   * 将照片 base64 上传到 photo-scanner /upload
   * data: { base64, mimeType, filename, creationDate }
   */
  async _uploadPhoto(data) {
    if (!_state.serverBase) throw new Error('Nervus 服务器未发现');
    const resp = await fetch(`${_state.serverBase.replace(':8090', ':8006')}/upload`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        base64: data.base64,
        filename: data.filename || `photo_${Date.now()}.jpg`,
        source: 'ios_photo_library',
        creation_date: data.creationDate,
      }),
    });
    return resp.json();
  },
};

// ── 3. AudioRecorder — 会议录音 ───────────────────────

const AudioRecorder = {
  /**
   * 请求麦克风权限
   */
  async requestPermission() {
    const plugin = getPlugin('AudioRecorderPlugin');
    if (!plugin) return { granted: true };
    return plugin.requestPermission();
  },

  /**
   * 开始录音
   * options: { quality: 'high'|'medium', format: 'm4a'|'wav' }
   */
  async start(options = {}) {
    if (_state.recordingActive) return { error: '录音已在进行中' };
    const plugin = getPlugin('AudioRecorderPlugin');
    if (!plugin) return { error: '录音插件不可用' };
    const result = await plugin.start({
      quality: options.quality || 'high',
      format: options.format || 'm4a',
      sampleRate: 16000,   // Whisper 最佳采样率
      channels: 1,
    });
    _state.recordingActive = true;
    return result;
  },

  /**
   * 停止录音，返回音频文件路径
   * 自动上传到 meeting-notes /record
   */
  async stop() {
    if (!_state.recordingActive) return { error: '没有进行中的录音' };
    const plugin = getPlugin('AudioRecorderPlugin');
    if (!plugin) return { error: '录音插件不可用' };
    const result = await plugin.stop();
    _state.recordingActive = false;

    // 自动上传
    if (result.base64 && _state.serverBase) {
      try {
        await AudioRecorder._uploadRecording(result);
      } catch (e) {
        console.error('[NervusBridge] 录音上传失败', e);
      }
    }
    return result;
  },

  /**
   * 当前录音时长（秒）
   */
  async getDuration() {
    const plugin = getPlugin('AudioRecorderPlugin');
    if (!plugin) return 0;
    return (await plugin.getDuration()).seconds;
  },

  isRecording() {
    return _state.recordingActive;
  },

  /**
   * 上传录音到 meeting-notes /record
   */
  async _uploadRecording(data) {
    if (!_state.serverBase) return;
    const base = _state.serverBase.replace(':8090', ':8002');
    await fetch(`${base}/record`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        base64: data.base64,
        filename: `recording_${Date.now()}.m4a`,
        duration_sec: data.durationSec,
        recorded_at: new Date().toISOString(),
      }),
    });
  },
};

// ── 4. BackgroundSync — 后台同步 + 本地通知 ───────────

const BackgroundSync = {
  /**
   * 注册后台拉取任务（BGAppRefreshTask）
   * 系统允许时每 15 分钟唤醒一次
   */
  async register() {
    const plugin = getPlugin('BackgroundSyncPlugin');
    if (!plugin) return;
    await plugin.register({
      taskId: 'ai.nervus.background-sync',
      minimumInterval: 900, // 15 分钟
    });
  },

  /**
   * 请求通知权限
   */
  async requestNotificationPermission() {
    const plugin = getPlugin('BackgroundSyncPlugin');
    if (!plugin) return { granted: true };
    return plugin.requestNotificationPermission();
  },

  /**
   * 推送本地通知
   * options: { title, body, badge, sound, delay }
   */
  async scheduleNotification(options) {
    const plugin = getPlugin('BackgroundSyncPlugin');
    if (!plugin) {
      console.log('[NervusBridge] 通知 mock:', options.title, options.body);
      return;
    }
    await plugin.scheduleNotification({
      id: Date.now(),
      title: options.title,
      body: options.body || '',
      badge: options.badge ?? 1,
      sound: options.sound !== false,
      schedule: { at: new Date(Date.now() + (options.delayMs || 0)) },
    });
  },

  /**
   * 轮询 Arbor Core 通知中心，本地弹出未读消息
   * 在后台任务触发时调用
   */
  async pollAndNotify() {
    if (!_state.serverBase) return;
    try {
      const resp = await fetch(`${_state.serverBase}/notify/notifications?unread=true`, {
        signal: AbortSignal.timeout(10000),
      });
      const { notifications } = await resp.json();
      for (const n of notifications || []) {
        await BackgroundSync.scheduleNotification({
          title: n.title || 'Nervus',
          body: n.body || '',
          delayMs: 0,
        });
        // 标记已读
        await fetch(`${_state.serverBase}/notify/notifications/${n.id}/read`, {
          method: 'POST',
        });
      }
    } catch (e) {
      // 后台任务中失败静默处理
    }
  },

  /**
   * 监听后台任务触发（来自 Swift BGTaskScheduler）
   */
  addListener(callback) {
    const plugin = getPlugin('BackgroundSyncPlugin');
    if (plugin) {
      return plugin.addListener('backgroundFetch', callback);
    }
    return { remove: () => {} };
  },
};

// ── 5. Nervus 主入口 ─────────────────────────────────

const Nervus = {
  /**
   * 初始化 Nervus Shell
   * 1. 通过 Bonjour 发现服务器
   * 2. 注册后台任务
   * 3. 开始监听相册
   * 4. 设置通知权限
   */
  async init(options = {}) {
    if (_state.initialized) return _state;

    // 设备 ID
    try {
      const { Device } = Capacitor.Plugins;
      const info = await Device.getId();
      _state.deviceId = info.identifier;
    } catch (e) {}

    // 发现服务器
    console.log('[Nervus] 正在发现局域网服务器...');
    try {
      const discovered = await NervusDiscovery.scan(options.discoveryTimeout || 5000);
      const scheme = options.useHttp ? 'http' : 'https';
      _state.serverBase = `${scheme}://${discovered.host}:${discovered.port || 8090}`;
      console.log(`[Nervus] 服务器发现：${_state.serverBase}`);
    } catch (e) {
      // 回退：直接使用配置的地址
      _state.serverBase = options.fallbackServer || 'https://nervus.local';
      console.warn(`[Nervus] 发现失败，使用回退地址：${_state.serverBase}`);
    }

    // 通知权限
    await BackgroundSync.requestNotificationPermission();

    // 后台同步注册
    await BackgroundSync.register();

    // 相册权限（如果用户允许）
    if (options.watchPhotos !== false) {
      const perm = await PhotoLibrary.requestPermission();
      if (perm.granted) {
        await PhotoLibrary.startWatching(options.onNewPhoto);
      }
    }

    // 后台任务触发时轮询通知
    BackgroundSync.addListener(async () => {
      await BackgroundSync.pollAndNotify();
    });

    // 监听服务消失（Wi-Fi 切换等场景）
    NervusDiscovery.addListener(async ({ type, host, port }) => {
      if (type === 'found') {
        const scheme = options.useHttp ? 'http' : 'https';
        _state.serverBase = `${scheme}://${host}:${port || 8090}`;
        console.log(`[Nervus] 服务器重新发现：${_state.serverBase}`);
        window.dispatchEvent(new CustomEvent('nervus:connected', { detail: { serverBase: _state.serverBase } }));
      } else if (type === 'lost') {
        window.dispatchEvent(new CustomEvent('nervus:disconnected'));
      }
    });

    _state.initialized = true;
    window.dispatchEvent(new CustomEvent('nervus:ready', { detail: { serverBase: _state.serverBase } }));
    return _state;
  },

  getServerBase() { return _state.serverBase; },
  getDeviceId()   { return _state.deviceId; },
  isInitialized() { return _state.initialized; },

  // 子模块
  Discovery: NervusDiscovery,
  Photos: PhotoLibrary,
  Recorder: AudioRecorder,
  Background: BackgroundSync,

  /**
   * 通用 API 调用快捷方式
   * Nervus.api('/notify/notifications') → fetch serverBase + path
   */
  async api(path, options = {}) {
    if (!_state.serverBase) throw new Error('Nervus 未初始化');
    const url = `${_state.serverBase}${path}`;
    const resp = await fetch(url, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...(options.headers || {}),
      },
    });
    if (!resp.ok) throw new Error(`API 错误 ${resp.status}: ${path}`);
    return resp.json();
  },
};

// 挂载到 window
window.Nervus = Nervus;
window.NervusBridge = Nervus; // 别名

export default Nervus;
