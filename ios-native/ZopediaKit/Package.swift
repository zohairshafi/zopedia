// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "ZopediaKit",
    platforms: [.iOS(.v17), .macOS(.v14)],
    products: [
        .library(name: "ZopediaKit", targets: ["ZopediaKit"]),
    ],
    dependencies: [
        .package(url: "https://github.com/swiftlang/swift-markdown", from: "0.4.0"),
    ],
    targets: [
        .target(
            name: "ZopediaKit",
            dependencies: [
                .product(name: "Markdown", package: "swift-markdown"),
            ]
        ),
        .testTarget(
            name: "ZopediaKitTests",
            dependencies: ["ZopediaKit"],
            resources: [.copy("Fixtures")]
        ),
    ]
)
