import Foundation
import CryptoKit

/// Код подключения «hhc1.…»: публичная ссылка на снимок, ключ шифрования и (необязательно) токен записи.
public struct ConnectionCode: Equatable {
    public let url: String
    public let key: String
    public let token: String?
}

public enum CloudError: LocalizedError {
    case badCode, badResponse(Int), badKey

    public var errorDescription: String? {
        switch self {
        case .badCode: return "Код подключения не распознан"
        case .badResponse(let c): return "Облако ответило \(c)"
        case .badKey: return "Снимок не расшифровался: проверьте код подключения"
        }
    }
}

/// Снимок на Яндекс.Диске: nonce(12) + AES-256-GCM, AAD «homehub-v1» — как на сервере (backend/app/cloud.py).
public enum Cloud {
    static let aad = Data("homehub-v1".utf8)

    public static func base64url(_ s: String) -> Data? {
        var t = s.replacingOccurrences(of: "-", with: "+").replacingOccurrences(of: "_", with: "/")
        while t.count % 4 != 0 { t += "=" }
        return Data(base64Encoded: t)
    }

    public static func parse(_ code: String) -> ConnectionCode? {
        var s = code.trimmingCharacters(in: .whitespacesAndNewlines)
        if s.hasPrefix("hhc1.") { s.removeFirst(5) }
        guard let data = base64url(s),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let u = obj["u"] as? String, let k = obj["k"] as? String,
              u.hasPrefix("https://"), !k.isEmpty else { return nil }
        let t = obj["t"] as? String
        return ConnectionCode(url: u, key: k, token: (t?.isEmpty ?? true) ? nil : t)
    }

    public static func decrypt(key: Data, blob: Data) throws -> Data {
        do {
            let box = try AES.GCM.SealedBox(combined: blob)
            return try AES.GCM.open(box, using: SymmetricKey(data: key), authenticating: aad)
        } catch {
            throw CloudError.badKey
        }
    }

    public static func encrypt(key: Data, plain: Data) throws -> Data {
        let box = try AES.GCM.seal(plain, using: SymmetricKey(data: key), authenticating: aad)
        return box.combined ?? Data()
    }

    /// Скачивает и расшифровывает снимок по публичной ссылке (без аккаунта и кук).
    public static func fetch(_ code: ConnectionCode, session: URLSession = .shared) async throws -> Data {
        guard let key = base64url(code.key) else { throw CloudError.badCode }
        var comps = URLComponents(string: "https://cloud-api.yandex.net/v1/disk/public/resources/download")!
        comps.queryItems = [URLQueryItem(name: "public_key", value: code.url)]
        let meta = try await get(comps.url!, session)
        guard let obj = try JSONSerialization.jsonObject(with: meta) as? [String: Any],
              let href = obj["href"] as? String, let url = URL(string: href) else { throw CloudError.badCode }
        let blob = try await get(url, session)
        return try decrypt(key: key, blob: blob)
    }

    static func get(_ url: URL, _ session: URLSession) async throws -> Data {
        var req = URLRequest(url: url)
        req.timeoutInterval = 12
        let (data, resp) = try await session.data(for: req)
        if let http = resp as? HTTPURLResponse, !(200..<300).contains(http.statusCode) {
            throw CloudError.badResponse(http.statusCode)
        }
        return data
    }
}
