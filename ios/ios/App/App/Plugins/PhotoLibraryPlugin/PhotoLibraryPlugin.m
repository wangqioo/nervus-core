#import <Foundation/Foundation.h>
#import <Capacitor/Capacitor.h>

// Capacitor 插件注册宏 — 将 Swift 类暴露给 JS 层
CAP_PLUGIN(PhotoLibraryPlugin, "PhotoLibraryPlugin",
    CAP_PLUGIN_METHOD(requestPermission, CAPPluginReturnPromise);
    CAP_PLUGIN_METHOD(startWatching,     CAPPluginReturnPromise);
    CAP_PLUGIN_METHOD(stopWatching,      CAPPluginReturnPromise);
    CAP_PLUGIN_METHOD(getRecentPhotos,   CAPPluginReturnPromise);
)
