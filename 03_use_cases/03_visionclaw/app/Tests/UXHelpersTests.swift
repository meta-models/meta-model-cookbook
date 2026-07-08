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

final class UXHelpersTests: XCTestCase {
  // MARK: Mic level normalization

  func testNormalizeSilenceIsZero() {
    XCTAssertEqual(SpeechRecognizer.normalize(rms: 0), 0)
  }

  func testNormalizeFullScaleIsOne() {
    XCTAssertEqual(SpeechRecognizer.normalize(rms: 1.0), 1, accuracy: 0.0001)
  }

  func testNormalizeBelowFloorIsZero() {
    // -60 dBFS is below the -50 dB floor.
    let rms = pow(10, -60.0 / 20.0)
    XCTAssertEqual(SpeechRecognizer.normalize(rms: Float(rms)), 0)
  }

  func testNormalizeMidRangeIsBetweenZeroAndOne() {
    // -25 dBFS should land around the middle of the 0...1 window.
    let rms = Float(pow(10, -25.0 / 20.0))
    let level = SpeechRecognizer.normalize(rms: rms)
    XCTAssertGreaterThan(level, 0.3)
    XCTAssertLessThan(level, 0.7)
  }

  // MARK: Highlighted attributed string

  func testHighlightWithNilRangeReturnsPlainText() {
    let text = "Hello world"
    let attributed = highlightedAttributedString(text, spokenRange: nil)
    XCTAssertEqual(String(attributed.characters), text)
  }

  func testHighlightWithValidRangePreservesText() {
    let text = "Hello world"
    let range = NSRange(location: 0, length: 5) // "Hello"
    let attributed = highlightedAttributedString(text, spokenRange: range)
    // The full text is preserved; styling is applied to the range.
    XCTAssertEqual(String(attributed.characters), text)
  }

  func testHighlightWithOutOfBoundsRangeIsSafe() {
    let text = "Hi"
    let range = NSRange(location: 5, length: 10)
    let attributed = highlightedAttributedString(text, spokenRange: range)
    XCTAssertEqual(String(attributed.characters), text)
  }

  // MARK: Turn

  func testTurnHoldsSpokenAndDisplaySeparately() {
    let turn = Turn(
      prompt: "what is this",
      frame: nil,
      status: .answered,
      displayAnswer: "It is an apple.",
      spokenAnswer: "It is an apple.",
      links: []
    )
    XCTAssertEqual(turn.prompt, "what is this")
    XCTAssertEqual(turn.displayAnswer, "It is an apple.")
    XCTAssertEqual(turn.status, .answered)
    XCTAssertTrue(turn.links.isEmpty)
    XCTAssertNil(turn.frame)
  }

  func testPendingTurnDefaults() {
    let turn = Turn(prompt: "what is this", frame: nil)
    XCTAssertEqual(turn.status, .pending)
    XCTAssertTrue(turn.displayAnswer.isEmpty)
    XCTAssertTrue(turn.spokenAnswer.isEmpty)
  }

  // MARK: Conversation persistence

  func testConversationStoreRoundTrip() {
    let store = ConversationStore(directoryName: "TestConversation-\(UUID().uuidString)")
    defer { store.clear() }

    let answered = Turn(
      prompt: "what is this",
      frame: nil,
      status: .answered,
      displayAnswer: "An apple.",
      spokenAnswer: "An apple.",
      links: [AnswerLink(label: "apple.com", url: URL(string: "https://apple.com")!)]
    )
    let pending = Turn(prompt: "in flight", frame: nil, status: .pending)
    store.save([answered, pending])

    let loaded = store.load()
    // Only the answered turn is persisted.
    XCTAssertEqual(loaded.count, 1)
    XCTAssertEqual(loaded.first?.prompt, "what is this")
    XCTAssertEqual(loaded.first?.displayAnswer, "An apple.")
    XCTAssertEqual(loaded.first?.status, .answered)
    XCTAssertEqual(loaded.first?.links.first?.url.absoluteString, "https://apple.com")
  }

  func testConversationStoreClear() {
    let store = ConversationStore(directoryName: "TestConversation-\(UUID().uuidString)")
    store.save([Turn(prompt: "q", frame: nil, status: .answered, displayAnswer: "a", spokenAnswer: "a")])
    XCTAssertEqual(store.load().count, 1)
    store.clear()
    XCTAssertTrue(store.load().isEmpty)
  }
}
