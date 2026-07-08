// swift-tools-version:5.9
import PackageDescription

let package = Package(
  name: "metacua",
  platforms: [.macOS(.v13)],
  targets: [
    .executableTarget(
      name: "metacua",
      path: "src/metacua",
      linkerSettings: [
        .linkedFramework("AppKit"),
        .linkedFramework("CoreGraphics"),
        .linkedFramework("ApplicationServices"),
      ]
    )
  ]
)
