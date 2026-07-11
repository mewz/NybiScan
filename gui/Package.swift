// swift-tools-version:6.0
import PackageDescription

let package = Package(
    name: "NybiScan",
    platforms: [.macOS(.v14)],
    targets: [
        // Testable client logic: no window, no business logic. Talks to the
        // control API and supervises the core process.
        .target(name: "NybiScanKit"),

        // SwiftUI window. Thin: renders NybiScanKit state and calls its client.
        .executableTarget(
            name: "NybiScanApp",
            dependencies: ["NybiScanKit"]
        ),

        .testTarget(
            name: "NybiScanKitTests",
            dependencies: ["NybiScanKit"]
        ),
    ]
)
