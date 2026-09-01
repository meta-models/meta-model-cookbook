# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Small helpers shared by lazy native adapters."""

from __future__ import annotations

from importlib import import_module
from types import ModuleType


class NativeDependencyError(RuntimeError):
    """Raised when a concrete macOS adapter cannot load its native bridge."""


def load_framework(module_name: str) -> ModuleType:
    try:
        return import_module(module_name)
    except ImportError as error:
        raise NativeDependencyError(
            f"The {module_name} PyObjC framework is required for this macOS operation."
        ) from error
