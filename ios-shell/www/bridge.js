/**
 * WebShell Bridge
 * 封装所有 Capacitor 原生能力，供各 Web App 调用
 */

const Plugins = window.Capacitor?.Plugins ?? {};
const Camera = Plugins.Camera;
const Geolocation = Plugins.Geolocation;
const PushNotifications = Plugins.PushNotifications;
const Filesystem = Plugins.Filesystem;
const Haptics = Plugins.Haptics;

const Bridge = {

  // ── 相机 / 相册 ──────────────────────────────────────────
  async pickPhoto() {
    const image = await Camera.getPhoto({
      quality: 90,
      allowEditing: false,
      resultType: 'uri',
      source: 'photos',
    });
    return image.webPath;
  },

  async takePhoto() {
    const image = await Camera.getPhoto({
      quality: 90,
      allowEditing: false,
      resultType: 'uri',
      source: 'camera',
    });
    return image.webPath;
  },

  // ── 定位 ─────────────────────────────────────────────────
  async getLocation() {
    const pos = await Geolocation.getCurrentPosition({
      enableHighAccuracy: true,
    });
    return {
      lat: pos.coords.latitude,
      lng: pos.coords.longitude,
      accuracy: pos.coords.accuracy,
    };
  },

  watchLocation(callback) {
    return Geolocation.watchPosition({ enableHighAccuracy: true }, callback);
  },

  // ── 推送通知 ──────────────────────────────────────────────
  async requestNotificationPermission() {
    const result = await PushNotifications.requestPermissions();
    if (result.receive === 'granted') {
      await PushNotifications.register();
      return true;
    }
    return false;
  },

  // ── 文件系统 ──────────────────────────────────────────────
  async saveFile(filename, data) {
    await Filesystem.writeFile({
      path: filename,
      data,
      directory: 'DOCUMENTS',
    });
  },

  async readFile(filename) {
    const result = await Filesystem.readFile({
      path: filename,
      directory: 'DOCUMENTS',
    });
    return result.data;
  },

  // ── 触感反馈 ──────────────────────────────────────────────
  vibrate() {
    Haptics.impact({ style: 'MEDIUM' });
  },

  // ── 麦克风（通过 Web API 直接访问）────────────────────────
  async getMicStream() {
    return navigator.mediaDevices.getUserMedia({ audio: true });
  },

  // ── 判断是否运行在原生容器中 ──────────────────────────────
  isNative() {
    return !!(window.Capacitor?.isNativePlatform?.());
  },
};

window.Bridge = Bridge;
