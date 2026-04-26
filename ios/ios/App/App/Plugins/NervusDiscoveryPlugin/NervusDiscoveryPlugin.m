#import <Foundation/Foundation.h>
#import <Capacitor/Capacitor.h>

CAP_PLUGIN(NervusDiscoveryPlugin, "NervusDiscoveryPlugin",
    CAP_PLUGIN_METHOD(scan, CAPPluginReturnPromise);
    CAP_PLUGIN_METHOD(stop, CAPPluginReturnPromise);
)
