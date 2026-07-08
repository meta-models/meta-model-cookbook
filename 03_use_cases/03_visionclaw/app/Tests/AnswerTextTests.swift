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

final class AnswerTextTests: XCTestCase {
  /// A realistic noisy gateway reply: tool narration, a bare URL, markdown, and an emoji.
  private let noisyReply = """
    Opened https://www.apple.com/airpods-pro/ in Chrome. 😎
    **Current model** is AirPods Pro 2 with USB-C — $249 at Apple.
    - Best Buy and Walmart often have deals.
    """

  func testSpokenHasNoURL() {
    let spoken = AnswerText.spoken(from: noisyReply)
    XCTAssertFalse(spoken.contains("http"), "spoken text must not contain a URL: \(spoken)")
    XCTAssertFalse(spoken.contains("apple.com"), "spoken text must not contain a domain: \(spoken)")
  }

  func testSpokenHasNoMarkdownOrEmoji() {
    let spoken = AnswerText.spoken(from: noisyReply)
    XCTAssertFalse(spoken.contains("**"), "spoken text must not contain markdown bold")
    XCTAssertFalse(spoken.contains("😎"), "spoken text must not contain emoji")
    XCTAssertFalse(spoken.hasPrefix("- "), "spoken text must not contain list markers")
  }

  func testSpokenStripsToolNarration() {
    let spoken = AnswerText.spoken(from: noisyReply).lowercased()
    XCTAssertFalse(spoken.contains("opened"), "spoken text must not narrate tool actions")
    XCTAssertFalse(spoken.contains("in chrome"), "spoken text must not mention the browser")
  }

  func testSpokenAppliesPronunciationReplacements() {
    let spoken = AnswerText.spoken(from: "It charges over USB-C.")
    XCTAssertTrue(spoken.contains("USB C"))
    XCTAssertFalse(spoken.contains("USB-C"))
  }

  func testDisplayStripsURLAndNarrationButKeepsAnswer() {
    let display = AnswerText.display(from: noisyReply)
    XCTAssertFalse(display.contains("http"), "display text must not contain a URL")
    XCTAssertFalse(display.lowercased().contains("opened"), "display must not narrate tool actions")
    XCTAssertTrue(display.contains("AirPods Pro 2"), "display must keep the actual answer: \(display)")
  }

  func testLinksAreExtracted() {
    let links = AnswerText.links(from: noisyReply)
    XCTAssertEqual(links.count, 1)
    XCTAssertEqual(links.first?.url.absoluteString, "https://www.apple.com/airpods-pro/")
  }

  func testMarkdownLinkKeepsLabelInTextAndExtractsURL() {
    let reply = "Try [the AirPods page](https://apple.com/airpods) for details."
    let spoken = AnswerText.spoken(from: reply)
    XCTAssertTrue(spoken.contains("the AirPods page"))
    XCTAssertFalse(spoken.contains("apple.com"))
    XCTAssertEqual(AnswerText.links(from: reply).first?.url.absoluteString, "https://apple.com/airpods")
  }

  func testPlainAnswerPassesThroughUnchanged() {
    let reply = "It is sunny and about 70 degrees."
    XCTAssertEqual(AnswerText.spoken(from: reply), reply)
    XCTAssertEqual(AnswerText.display(from: reply), reply)
    XCTAssertTrue(AnswerText.links(from: reply).isEmpty)
  }
}
