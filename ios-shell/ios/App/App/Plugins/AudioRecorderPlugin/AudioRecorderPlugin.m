#import <Foundation/Foundation.h>
#import <Capacitor/Capacitor.h>

CAP_PLUGIN(AudioRecorderPlugin, "AudioRecorderPlugin",
    CAP_PLUGIN_METHOD(requestPermission, CAPPluginReturnPromise);
    CAP_PLUGIN_METHOD(start,             CAPPluginReturnPromise);
    CAP_PLUGIN_METHOD(stop,              CAPPluginReturnPromise);
    CAP_PLUGIN_METHOD(getDuration,       CAPPluginReturnPromise);
    CAP_PLUGIN_METHOD(getMetering,       CAPPluginReturnPromise);
)
