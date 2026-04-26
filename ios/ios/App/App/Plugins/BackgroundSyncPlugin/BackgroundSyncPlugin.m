#import <Foundation/Foundation.h>
#import <Capacitor/Capacitor.h>

CAP_PLUGIN(BackgroundSyncPlugin, "BackgroundSyncPlugin",
    CAP_PLUGIN_METHOD(register,                      CAPPluginReturnPromise);
    CAP_PLUGIN_METHOD(requestNotificationPermission, CAPPluginReturnPromise);
    CAP_PLUGIN_METHOD(scheduleNotification,          CAPPluginReturnPromise);
    CAP_PLUGIN_METHOD(cancelNotification,            CAPPluginReturnPromise);
    CAP_PLUGIN_METHOD(getPendingNotifications,       CAPPluginReturnPromise);
    CAP_PLUGIN_METHOD(clearBadge,                    CAPPluginReturnPromise);
)
