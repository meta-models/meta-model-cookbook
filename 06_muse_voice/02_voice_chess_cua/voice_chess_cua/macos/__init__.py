# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Import-safe macOS adapters.

PyObjC frameworks are loaded only when a concrete native backend is used. Importing
this package is therefore safe for test discovery before PyObjC is installed.
"""

from .appkit_host import AppKitHost
from .application import (
    CHESS_BUNDLE_IDENTIFIER,
    ChessApplicationAmbiguousError,
    ChessApplicationController,
    ChessApplicationError,
    ChessApplicationStatus,
)
from .audio import AudioCaptureService
from .capture import WindowScreenshot, WindowScreenshotProvider
from .overlay import BoardOverlay, OverlayStyle
from .permissions import PermissionController, PermissionGrant, PermissionSnapshot
from .windows import ChessWindowDescriptor, ChessWindowLocator

__all__ = [
    "CHESS_BUNDLE_IDENTIFIER",
    "AppKitHost",
    "AudioCaptureService",
    "BoardOverlay",
    "ChessApplicationAmbiguousError",
    "ChessApplicationController",
    "ChessApplicationError",
    "ChessApplicationStatus",
    "ChessWindowDescriptor",
    "ChessWindowLocator",
    "OverlayStyle",
    "PermissionController",
    "PermissionGrant",
    "PermissionSnapshot",
    "WindowScreenshot",
    "WindowScreenshotProvider",
]
