// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "HomeHubMac",
    platforms: [.macOS(.v13)],
    targets: [
        // Логика без интерфейса: коды подключения, расшифровка снимка, «что дальше». Её проверяют тесты.
        .target(name: "HomeHubCore"),
        .executableTarget(name: "HomeHubMac", dependencies: ["HomeHubCore"]),
        .testTarget(name: "HomeHubCoreTests", dependencies: ["HomeHubCore"]),
    ]
)
