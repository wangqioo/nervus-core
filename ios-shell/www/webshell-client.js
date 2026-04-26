/**
 * WebShell Client
 * 在你的远程 Web 应用里引入这个文件，即可调用原生能力
 * 用法：const loc = await WebShell.getLocation()
 */

const WebShell = (() => {
  let _callId = 0;
  const _pending = {};

  // 接收 Shell 回传的结果
  window.addEventListener('message', (event) => {
    const { id, result, error } = event.data ?? {};
    if (!id || !_pending[id]) return;
    const { resolve, reject } = _pending[id];
    delete _pending[id];
    error ? reject(new Error(error)) : resolve(result);
  });

  function call(method, ...args) {
    return new Promise((resolve, reject) => {
      const id = `ws_${++_callId}`;
      _pending[id] = { resolve, reject };
      window.parent.postMessage({ id, method, args }, '*');
    });
  }

  return {
    // 相册 / 相机
    pickPhoto:   ()         => call('pickPhoto'),
    takePhoto:   ()         => call('takePhoto'),
    // 定位
    getLocation: ()         => call('getLocation'),
    // 文件
    saveFile:    (name, data) => call('saveFile', name, data),
    readFile:    (name)     => call('readFile', name),
    // 触感
    vibrate:     ()         => call('vibrate'),
    // 通知权限
    requestNotificationPermission: () => call('requestNotificationPermission'),
    // 检测是否在 WebShell 容器里
    isAvailable: () => window.self !== window.top,
  };
})();

window.WebShell = WebShell;
