"""The error types tool callers handle. Handlers turn them into ``{"error": {code, message}}``."""


class ToolError(Exception):
    """A tool rejected the request; ``code`` is a stable identifier for the caller."""

    code = "TOOL_ERROR"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code
        self.message = message


class ValidationError(ToolError):
    """An input is missing or invalid; the message names the field."""

    code = "INVALID_INPUT"


class TripNotFound(ToolError):
    """No trip record exists for the train and date."""

    code = "TRIP_NOT_FOUND"


class ClaimRejected(ToolError):
    """The claim cannot be submitted; ``code`` is the reason (e.g. CONFIRMATION_MISMATCH)."""
