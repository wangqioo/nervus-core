import Foundation
import Capacitor
import Network

/**
 NervusDiscoveryPlugin
 使用 Bonjour/mDNS (Network.framework) 在局域网内自动发现 Nervus 服务器。
 服务类型: _nervus._tcp（或 _http._tcp 配合 TXT 记录过滤）
 发现后返回 { host, port, addresses }
 */
@objc(NervusDiscoveryPlugin)
public class NervusDiscoveryPlugin: CAPPlugin {

    private let serviceType = "_nervus._tcp"
    private let localDomain = "local."

    private var browser: NWBrowser?
    private var activeScanCall: CAPPluginCall?
    private var scanTimer: Timer?

    // MARK: - 扫描

    @objc func scan(_ call: CAPPluginCall) {
        let timeoutMs = call.getDouble("timeoutMs") ?? 5000

        // 优先尝试 nervus.local 直接解析（Caddy 已配置）
        Task {
            if let direct = await self.tryDirect(hosts: ["nervus.local"]) {
                call.resolve(direct)
                return
            }
            // 回退：mDNS 浏览
            self.activeScanCall = call
            self.startBrowsing()
            self.scanTimer = Timer.scheduledTimer(withTimeInterval: timeoutMs / 1000,
                                                   repeats: false) { [weak self] _ in
                self?.browser?.cancel()
                self?.activeScanCall?.reject("扫描超时：局域网内未发现 Nervus 服务器")
                self?.activeScanCall = nil
            }
        }
    }

    @objc func stop(_ call: CAPPluginCall) {
        scanTimer?.invalidate()
        browser?.cancel()
        call.resolve()
    }

    // MARK: - 直接解析已知主机

    private func tryDirect(hosts: [String]) async -> [String: Any]? {
        for host in hosts {
            for port in [8090, 80, 443] {
                let url = URL(string: "http://\(host):\(port)/health")!
                if let _ = try? await URLSession.shared.data(from: url) {
                    return ["host": host, "port": port, "addresses": [host]]
                }
            }
        }
        return nil
    }

    // MARK: - NWBrowser mDNS 浏览

    private func startBrowsing() {
        let params = NWParameters()
        params.includePeerToPeer = false

        browser = NWBrowser(for: .bonjourWithTXTRecord(type: serviceType, domain: localDomain),
                            using: params)

        browser?.stateUpdateHandler = { [weak self] state in
            switch state {
            case .failed(let error):
                self?.activeScanCall?.reject("mDNS 浏览失败: \(error)")
                self?.activeScanCall = nil
            default:
                break
            }
        }

        browser?.browseResultsChangedHandler = { [weak self] results, changes in
            for change in changes {
                switch change {
                case .added(let result):
                    self?.resolveService(result: result)
                case .removed(let result):
                    if case .service(let name, _, _, _) = result.endpoint {
                        self?.notifyListeners("serviceChange", data: [
                            "type": "lost",
                            "name": name,
                        ])
                    }
                default:
                    break
                }
            }
        }

        browser?.start(queue: .global(qos: .userInitiated))
    }

    // MARK: - 解析服务端点

    private func resolveService(result: NWBrowser.Result) {
        let connection = NWConnection(to: result.endpoint, using: .tcp)

        connection.stateUpdateHandler = { [weak self] state in
            switch state {
            case .ready:
                guard let path = connection.currentPath,
                      let remote = path.remoteEndpoint else {
                    connection.cancel()
                    return
                }

                var host = ""
                var port = 8090

                if case .hostPort(let h, let p) = remote {
                    host = "\(h)"
                    port = Int(p.rawValue)
                }

                let resultData: [String: Any] = [
                    "host": host.isEmpty ? "nervus.local" : host,
                    "port": port,
                    "addresses": [host],
                ]

                // 完成扫描
                self?.scanTimer?.invalidate()
                self?.activeScanCall?.resolve(resultData)
                self?.activeScanCall = nil

                // 持续通知监听者
                self?.notifyListeners("serviceChange", data: ["type": "found"] + resultData)
                connection.cancel()

            case .failed:
                connection.cancel()
            default:
                break
            }
        }
        connection.start(queue: .global(qos: .userInitiated))
    }
}

// 合并字典
private func + (lhs: [String: Any], rhs: [String: Any]) -> [String: Any] {
    var result = lhs
    rhs.forEach { result[$0] = $1 }
    return result
}
