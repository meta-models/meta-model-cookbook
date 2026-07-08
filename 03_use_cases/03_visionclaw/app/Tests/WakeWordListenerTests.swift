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

final class WakeWordListenerTests: XCTestCase {
  func testMatchesExactPhrase() {
    XCTAssertTrue(WakeWordListener.matches("hey muse"))
  }

  func testMatchesWithCasingAndPunctuation() {
    XCTAssertTrue(WakeWordListener.matches("Hey, Muse!"))
    XCTAssertTrue(WakeWordListener.matches("HEY MUSE"))
  }

  func testMatchesWithinLongerUtterance() {
    XCTAssertTrue(WakeWordListener.matches("ok so hey muse what is this"))
  }

  func testMatchesCommonMishearings() {
    XCTAssertTrue(WakeWordListener.matches("hey mews"))
    XCTAssertTrue(WakeWordListener.matches("hey moose"))
  }

  func testRejectsNearMisses() {
    XCTAssertFalse(WakeWordListener.matches("hey"))
    XCTAssertFalse(WakeWordListener.matches("muse"))
    XCTAssertFalse(WakeWordListener.matches("amusement park"))
    XCTAssertFalse(WakeWordListener.matches("they use it"))
    XCTAssertFalse(WakeWordListener.matches(""))
  }
}
