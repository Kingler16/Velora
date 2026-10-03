// swift-tools-version: 6.2
import PackageDescription

let package = Package(
    name: "VeloraKit",
    defaultLocalization: "de",
    platforms: [.iOS(.v26), .macOS(.v26)],
    products: [
        .library(name: "VeloraKit", targets: ["VeloraKit"]),
    ],
    targets: [
        .target(name: "VeloraKit"),
        .testTarget(name: "VeloraKitTests", dependencies: ["VeloraKit"]),
    ]
)
