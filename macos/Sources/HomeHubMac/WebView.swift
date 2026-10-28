import SwiftUI
import WebKit
import AppKit

/// Веб-интерфейс календаря (тот же, что в браузере и в приложении для Android).
struct WebView: NSViewRepresentable {
    let url: URL
    let reloadToken: Int

    func makeCoordinator() -> Coordinator { Coordinator() }

    func makeNSView(context: Context) -> WKWebView {
        let web = WKWebView(frame: .zero, configuration: WKWebViewConfiguration())
        web.navigationDelegate = context.coordinator
        web.allowsBackForwardNavigationGestures = true
        context.coordinator.baseURL = url
        context.coordinator.lastToken = reloadToken
        web.load(URLRequest(url: url))
        return web
    }

    func updateNSView(_ web: WKWebView, context: Context) {
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

        func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction,
                     decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
            // Внешние ссылки открываем в браузере, а не внутри окна календаря.
            if navigationAction.navigationType == .linkActivated, let u = navigationAction.request.url,
               let host = u.host, host != baseURL?.host, ["http", "https"].contains(u.scheme ?? "") {
                NSWorkspace.shared.open(u)
                decisionHandler(.cancel)
                return
            }
            decisionHandler(.allow)
        }
    }
}
