"""Typed CLI error carrying an exit code."""


class CLIError(Exception):
    """An error with an associated process exit code.

    Exit codes are: 1 runtime, 2 usage/validation, 3 missing
    permission.
    """

    def __init__(self, message: str, code: int = 1):
        super().__init__(message)
        self.message = message
        self.code = code
