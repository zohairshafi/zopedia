// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "ZopediaKit",
    platforms: [.iOS(.v17), .macOS(.v14)],
    products: [
        .library(name: "ZopediaKit", targets: ["ZopediaKit"]),
    ],
    targets: [
        .target(name: "ZopediaKit"),
        .testTarget(
            name: "ZopediaKitTests",
            dependencies: ["ZopediaKit"],
            resources: [.copy("Fixtures")]
        ),
    ]
)
