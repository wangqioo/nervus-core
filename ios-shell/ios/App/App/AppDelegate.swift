import UIKit
import Capacitor
import WebKit

@main
class AppDelegate: UIResponder, UIApplicationDelegate {

    var window: UIWindow?

    func application(_ application: UIApplication, didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]?) -> Bool {
        return true
    }




    // CAPBridgeViewController 初始化后会调用这个方法，在 WebView 创建前注入脚本
    func application(_ application: UIApplication, didFinishLaunching notification: Notification) {}

    // 在 WebView 准备好之前注册 UserScript
    func applicationDidBecomeActive(_ application: UIApplication) {
        NSLog("[WebShell] applicationDidBecomeActive called")
        injectBridgeHandler()
        // 延迟 2 秒确保 Capacitor bridge 完全就绪后再触发相册同步
        DispatchQueue.main.asyncAfter(deadline: .now() + 2.0) {
            NSLog("[WebShell] setting up PhotoSync onStatusUpdate")
            // 把同步状态传给 WebView 显示
            PhotoSyncManager.shared.onStatusUpdate = { msg in
                DispatchQueue.main.async {
                    // 尝试多种方式获取 bridge webView
                    let rootVC = UIApplication.shared.connectedScenes
                        .compactMap { $0 as? UIWindowScene }
                        .flatMap { $0.windows }
                        .first(where: { $0.isKeyWindow })?.rootViewController
                    if let capVC = rootVC as? CAPBridgeViewController,
                       let webView = capVC.bridge?.webView {
                        let safe = msg.replacingOccurrences(of: "'", with: "\\'")
                        let js = "window.showSyncStatus && window.showSyncStatus('\(safe)')"
                        webView.evaluateJavaScript(js, completionHandler: nil)
                    } else {
                        NSLog("[WebShell] onStatusUpdate: no webView found, msg=\(msg)")
                    }
                }
            }
            NSLog("[WebShell] calling syncIfNeeded")
            // 申请后台任务令牌，即使用户切换到其他 app 也能继续运行
            var bgTask: UIBackgroundTaskIdentifier = .invalid
            bgTask = UIApplication.shared.beginBackgroundTask(withName: "PhotoSync") {
                // 超时回调：系统要强制结束，清理令牌
                UIApplication.shared.endBackgroundTask(bgTask)
                bgTask = .invalid
            }
            PhotoSyncManager.shared.syncIfNeeded()
            // 兜底：最多给 10 分钟，之后系统会强制结束
            DispatchQueue.global().asyncAfter(deadline: .now() + 600) {
                if bgTask != .invalid {
                    UIApplication.shared.endBackgroundTask(bgTask)
                    bgTask = .invalid
                }
            }
        }
    }

    private func injectBridgeHandler() {
        guard
            let rootVC = window?.rootViewController,
            let capVC = rootVC as? CAPBridgeViewController,
            let bridge = capVC.bridge,
            let webView = bridge.webView
        else { return }

        // 避免重复注册
        let controller = webView.configuration.userContentController
        let existing = controller.userScripts.map { $0.source }
        let jsFunc = "window.openExternalApp = function(title, url) { window.webkit.messageHandlers.openExternalApp.postMessage({title: title, url: url}); };"
        guard !existing.contains(jsFunc) else { return }

        // 注入为 UserScript，每次页面加载都会执行
        let script = WKUserScript(source: jsFunc, injectionTime: .atDocumentStart, forMainFrameOnly: true)
        controller.addUserScript(script)

        // 注册消息处理器（避免重复添加导致崩溃）
        controller.removeScriptMessageHandler(forName: "openExternalApp")
        controller.add(ExternalAppHandler(rootVC: rootVC), name: "openExternalApp")
    }

    func applicationWillResignActive(_ application: UIApplication) {}
    func applicationDidEnterBackground(_ application: UIApplication) {}
    func applicationWillEnterForeground(_ application: UIApplication) {}
    func applicationWillTerminate(_ application: UIApplication) {}

    func application(_ app: UIApplication, open url: URL, options: [UIApplication.OpenURLOptionsKey: Any] = [:]) -> Bool {
        return ApplicationDelegateProxy.shared.application(app, open: url, options: options)
    }

    func application(_ application: UIApplication, continue userActivity: NSUserActivity, restorationHandler: @escaping ([UIUserActivityRestoring]?) -> Void) -> Bool {
        return ApplicationDelegateProxy.shared.application(application, continue: userActivity, restorationHandler: restorationHandler)
    }
}

// MARK: - 处理 JS openExternalApp 消息

class ExternalAppHandler: NSObject, WKScriptMessageHandler {
    weak var rootVC: UIViewController?

    init(rootVC: UIViewController) {
        self.rootVC = rootVC
    }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        guard
            let body = message.body as? [String: String],
            let title = body["title"],
            let urlString = body["url"],
            let url = URL(string: urlString)
        else { return }

        DispatchQueue.main.async {
            let vc = WebAppViewController.cached(url: url, title: title)
            self.rootVC?.present(vc, animated: true)
        }
    }
}

// MARK: - 全屏外部 WebApp 控制器

class WebAppViewController: UIViewController, WKNavigationDelegate, WKUIDelegate {

    // 按 URL 缓存 ViewController，避免重复创建导致登录状态丢失
    private static var cache: [String: WebAppViewController] = [:]

    static func cached(url: URL, title: String) -> WebAppViewController {
        let key = url.absoluteString
        if let existing = cache[key] {
            return existing
        }
        let vc = WebAppViewController(url: url, title: title)
        cache[key] = vc
        return vc
    }

    private let url: URL
    private let appTitle: String
    private var webView: WKWebView!
    private var hasLoaded = false

    init(url: URL, title: String) {
        self.url = url
        self.appTitle = title
        super.init(nibName: nil, bundle: nil)
        self.modalPresentationStyle = .fullScreen
    }

    required init?(coder: NSCoder) { fatalError() }

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = .white

        let config = WKWebViewConfiguration()
        config.allowsInlineMediaPlayback = true
        config.mediaTypesRequiringUserActionForPlayback = []
        config.websiteDataStore = WKWebsiteDataStore.default()

        // 注入 sessionStorage 持久化脚本：把 sessionStorage 内容备份到 localStorage
        let persistScript = WKUserScript(source: """
            (function() {
                const KEY = '__ss_backup__';
                // 恢复上次备份的 sessionStorage
                try {
                    const backup = localStorage.getItem(KEY);
                    if (backup) {
                        const data = JSON.parse(backup);
                        Object.keys(data).forEach(k => {
                            if (!sessionStorage.getItem(k)) sessionStorage.setItem(k, data[k]);
                        });
                    }
                } catch(e) {}

                // 监听 sessionStorage 变化，实时备份到 localStorage
                const origSetItem = sessionStorage.setItem.bind(sessionStorage);
                const origRemoveItem = sessionStorage.removeItem.bind(sessionStorage);
                const origClear = sessionStorage.clear.bind(sessionStorage);

                function saveBackup() {
                    try {
                        const data = {};
                        for (let i = 0; i < sessionStorage.length; i++) {
                            const k = sessionStorage.key(i);
                            data[k] = sessionStorage.getItem(k);
                        }
                        localStorage.setItem(KEY, JSON.stringify(data));
                    } catch(e) {}
                }

                sessionStorage.setItem = function(k, v) {
                    origSetItem(k, v);
                    saveBackup();
                };
                sessionStorage.removeItem = function(k) {
                    origRemoveItem(k);
                    saveBackup();
                };
                sessionStorage.clear = function() {
                    origClear();
                    localStorage.removeItem(KEY);
                };
            })();
        """, injectionTime: .atDocumentStart, forMainFrameOnly: false)
        config.userContentController.addUserScript(persistScript)

        webView = WKWebView(frame: .zero, configuration: config)
        webView.navigationDelegate = self
        webView.uiDelegate = self
        webView.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(webView)

        let navBar = UIView()
        navBar.backgroundColor = .systemBackground
        navBar.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(navBar)

        let separator = UIView()
        separator.backgroundColor = UIColor(white: 0.9, alpha: 1)
        separator.translatesAutoresizingMaskIntoConstraints = false
        navBar.addSubview(separator)

        let backBtn = UIButton(type: .system)
        backBtn.setTitle("‹ 返回", for: .normal)
        backBtn.titleLabel?.font = UIFont.systemFont(ofSize: 16)
        backBtn.translatesAutoresizingMaskIntoConstraints = false
        backBtn.addTarget(self, action: #selector(goBack), for: .touchUpInside)
        navBar.addSubview(backBtn)

        let titleLabel = UILabel()
        titleLabel.text = appTitle
        titleLabel.font = UIFont.boldSystemFont(ofSize: 17)
        titleLabel.textAlignment = .center
        titleLabel.translatesAutoresizingMaskIntoConstraints = false
        navBar.addSubview(titleLabel)

        NSLayoutConstraint.activate([
            navBar.topAnchor.constraint(equalTo: view.topAnchor),
            navBar.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            navBar.trailingAnchor.constraint(equalTo: view.trailingAnchor),
            navBar.heightAnchor.constraint(equalToConstant: 100),

            separator.bottomAnchor.constraint(equalTo: navBar.bottomAnchor),
            separator.leadingAnchor.constraint(equalTo: navBar.leadingAnchor),
            separator.trailingAnchor.constraint(equalTo: navBar.trailingAnchor),
            separator.heightAnchor.constraint(equalToConstant: 0.5),

            backBtn.leadingAnchor.constraint(equalTo: navBar.leadingAnchor, constant: 16),
            backBtn.bottomAnchor.constraint(equalTo: navBar.bottomAnchor, constant: -10),

            titleLabel.centerXAnchor.constraint(equalTo: navBar.centerXAnchor),
            titleLabel.bottomAnchor.constraint(equalTo: navBar.bottomAnchor, constant: -10),

            webView.topAnchor.constraint(equalTo: navBar.bottomAnchor),
            webView.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            webView.trailingAnchor.constraint(equalTo: view.trailingAnchor),
            webView.bottomAnchor.constraint(equalTo: view.bottomAnchor),
        ])

        if !hasLoaded {
            hasLoaded = true
            webView.load(URLRequest(url: url))
        }
    }

    @objc func goBack() {
        dismiss(animated: true)
    }

    // 跳过 SSL 证书验证（开发/自签名证书场景）
    func webView(_ webView: WKWebView,
                 didReceive challenge: URLAuthenticationChallenge,
                 completionHandler: @escaping (URLSession.AuthChallengeDisposition, URLCredential?) -> Void) {
        if challenge.protectionSpace.authenticationMethod == NSURLAuthenticationMethodServerTrust,
           let trust = challenge.protectionSpace.serverTrust {
            completionHandler(.useCredential, URLCredential(trust: trust))
        } else {
            completionHandler(.performDefaultHandling, nil)
        }
    }
}
