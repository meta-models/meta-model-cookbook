/*
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 */

@testable import VisionClaw
// ast-grep-ignore: swift-testing/swift/no-new-xctest
import XCTest

final class ChatDTOsTests: XCTestCase {
  func testJpegDataURIHasExpectedShape() {
    let data = Data([0xFF, 0xD8, 0xFF, 0xE0])
    let uri = ImageEncoding.jpegDataURI(data)
    XCTAssertTrue(uri.hasPrefix("data:image/jpeg;base64,"))
    XCTAssertTrue(uri.hasSuffix(data.base64EncodedString()))
  }

  func testRequestEncodesTextAndImageParts() throws {
    let request = ChatRequest(
      model: "openclaw/default",
      messages: [
        .init(
          role: "user",
          content: [
            .text("What am I looking at?"),
            .imageURL("data:image/jpeg;base64,AAAA"),
          ])
      ],
      user: "visionclaw-test",
      stream: false
    )
    let data = try JSONEncoder().encode(request)
    let root = try XCTUnwrap(try JSONSerialization.jsonObject(with: data) as? [String: Any])

    XCTAssertEqual(root["model"] as? String, "openclaw/default")
    // The app must never hand tool execution back to itself.
    XCTAssertNil(root["tools"])

    let messages = try XCTUnwrap(root["messages"] as? [[String: Any]])
    let content = try XCTUnwrap(messages.first?["content"] as? [[String: Any]])
    XCTAssertEqual(content.count, 2)
    XCTAssertEqual(content[0]["type"] as? String, "text")
    XCTAssertEqual(content[1]["type"] as? String, "image_url")
    let imageURL = try XCTUnwrap(content[1]["image_url"] as? [String: Any])
    XCTAssertEqual(imageURL["url"] as? String, "data:image/jpeg;base64,AAAA")
  }

  func testResponseDecodesFinalText() throws {
    let json = Data(
      """
      {"id":"chatcmpl_1","object":"chat.completion","choices":[{"index":0,"message":{"role":"assistant","content":"A red mug."},"finish_reason":"stop"}]}
      """.utf8)
    let response = try JSONDecoder().decode(ChatResponse.self, from: json)
    XCTAssertEqual(response.text, "A red mug.")
  }

  func testResponseTextEmptyWhenNoChoices() throws {
    let json = Data(#"{"id":"x","object":"chat.completion","choices":[]}"#.utf8)
    let response = try JSONDecoder().decode(ChatResponse.self, from: json)
    XCTAssertEqual(response.text, "")
  }
}
