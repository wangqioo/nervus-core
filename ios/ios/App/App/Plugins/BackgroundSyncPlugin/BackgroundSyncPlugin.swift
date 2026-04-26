import Foundation
import Capacitor
import BackgroundTasks
import UserNotifications

/**
 BackgroundSyncPlugin
 - 注册 BGAppRefreshTask，定期唤醒 App 拉取 Nervus 通知
 - 封装 UNUserNotificationCenter，推送本地通知
 权限需求（Info.plist）：
   BGTaskSchedulerPermittedIdentifiers: ["ai.nervus.background-sync"]
 Capabilities (Xcode):
   Background Modes → Background fetch + Background processing
 */
@objc(BackgroundSyncPlugin)
public class BackgroundSyncPlugin: CAPPlugin {

    private static let bgTaskId = "ai.nervus.background-sync"

    // MARK: - 注册后台任务

    @objc func register(_ call: CAPPluginCall) {
        let taskId   = call.getString("taskId") ?? Self.bgTaskId
        let interval = call.getDouble("minimumInterval") ?? 900

        // 注册 BGAppRefreshTask 处理器（必须在 App 启动早期调用，此处补充注册）
        BGTaskScheduler.shared.register(forTaskWithIdentifier: taskId, using: nil) { [weak self] task in
            guard let refreshTask = task as? BGAppRefreshTask else { return }
            self?.handleBackgroundFetch(task: refreshTask)
        }

        scheduleBackgroundFetch(taskId: taskId, interval: interval)
        call.resolve(["status": "registered", "taskId": taskId])
    }

    private func scheduleBackgroundFetch(taskId: String, interval: TimeInterval) {
        let request = BGAppRefreshTaskRequest(identifier: taskId)
        request.earliestBeginDate = Date(timeIntervalSinceNow: interval)
        try? BGTaskScheduler.shared.submit(request)
    }

    private func handleBackgroundFetch(task: BGAppRefreshTask) {
        // 通知 JS 层执行 pollAndNotify
        notifyListeners("backgroundFetch", data: [
            "taskId": Self.bgTaskId,
            "timestamp": ISO8601DateFormatter().string(from: Date()),
        ])

        // 完成任务并重新调度
        task.setTaskCompleted(success: true)
        scheduleBackgroundFetch(taskId: Self.bgTaskId, interval: 900)
    }

    // MARK: - 通知权限

    @objc func requestNotificationPermission(_ call: CAPPluginCall) {
        UNUserNotificationCenter.current().requestAuthorization(
            options: [.alert, .badge, .sound]
        ) { granted, error in
            call.resolve(["granted": granted])
        }
    }

    // MARK: - 推送本地通知

    @objc func scheduleNotification(_ call: CAPPluginCall) {
        guard let title = call.getString("title") else {
            call.reject("title 不能为空")
            return
        }

        let body      = call.getString("body") ?? ""
        let badge     = call.getInt("badge") ?? 1
        let withSound = call.getBool("sound") ?? true
        let notifId   = "\(call.getInt("id") ?? Int.random(in: 0..<999999))"

        // 触发时间
        let delayMs = call.getDouble("delayMs") ?? 0
        let fireDate = Date(timeIntervalSinceNow: delayMs / 1000)

        let content = UNMutableNotificationContent()
        content.title = title
        content.body  = body
        content.badge = NSNumber(value: badge)
        if withSound { content.sound = .default }

        let comps = Calendar.current.dateComponents([.year,.month,.day,.hour,.minute,.second], from: fireDate)
        let trigger = UNCalendarNotificationTrigger(dateMatching: comps, repeats: false)
        let request = UNNotificationRequest(identifier: notifId, content: content, trigger: trigger)

        UNUserNotificationCenter.current().add(request) { error in
            if let e = error {
                call.reject("通知调度失败: \(e.localizedDescription)")
            } else {
                call.resolve(["id": notifId])
            }
        }
    }

    // MARK: - 取消通知

    @objc func cancelNotification(_ call: CAPPluginCall) {
        guard let notifId = call.getString("id") else {
            call.reject("id 不能为空")
            return
        }
        UNUserNotificationCenter.current().removePendingNotificationRequests(withIdentifiers: [notifId])
        call.resolve()
    }

    // MARK: - 获取待推送通知列表

    @objc func getPendingNotifications(_ call: CAPPluginCall) {
        UNUserNotificationCenter.current().getPendingNotificationRequests { requests in
            let data = requests.map { req -> [String: Any] in
                return [
                    "id":    req.identifier,
                    "title": req.content.title,
                    "body":  req.content.body,
                ]
            }
            call.resolve(["notifications": data])
        }
    }

    // MARK: - 清除角标

    @objc func clearBadge(_ call: CAPPluginCall) {
        DispatchQueue.main.async {
            UIApplication.shared.applicationIconBadgeNumber = 0
        }
        call.resolve()
    }
}
