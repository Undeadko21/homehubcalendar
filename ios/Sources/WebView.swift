import SwiftUI
import WebKit
import UIKit

/// Веб-интерфейс календаря (тот же, что в браузере и в приложении для Android).
struct WebView: UIViewRepresentable {
    let url: URL
    let reloadToken: Int

    func makeCoordinator() -> Coordinator { Coordinator() }

    func makeUIView(context: Context) -> WKWebView {
        let web = WKWebView(frame: .zero, configuration: WKWebViewConfiguration())
        web.navigationDelegate = context.coordinator
        web.allowsBackForwardNavigationGestures = true
        let refresh = UIRefreshControl()
        refresh.addTarget(context.coordinator, action: #selector(Coordinator.pulled(_:)), for: .valueChanged)
        web.scrollView.refreshControl = refresh
        context.coordinator.web = web
        context.coordinator.baseURL = url
        context.coordinator.lastToken = reloadToken
        web.load(URLRequest(url: url))
        return web
    }

    func updateUIView(_ web: WKWebView, context: Context) {
        let c = context.coordinator
        if c.baseURL != url {
            c.baseURL = url
            web.load(URLRequest(url: url))
        } else if c.lastToken != reloadToken {
            c.lastToken = reloadToken
            web.reload()
        }
    }

    final class Coordinator: NSObject, WKNavigationDelegate {
        var baseURL: URL?
        var lastToken = 0
        weak var web: WKWebView?

        @objc func pulled(_ sender: UIRefreshControl) {
            web?.reload()
            sender.endRefreshing()
        }

        func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction,
                     decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
            // Внешние ссылки открываем в браузере, а не внутри календаря.
            if navigationAction.navigationType == .linkActivated, let u = navigationAction.request.url,
               let host = u.host, host != baseURL?.host, ["http", "https"].contains(u.scheme ?? "") {
                UIApplication.shared.open(u)
                decisionHandler(.cancel)
                return
            }
            decisionHandler(.allow)
        }
    }
}
