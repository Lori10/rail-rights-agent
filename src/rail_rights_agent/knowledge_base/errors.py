"""The one error type callers of the knowledge base handle (design D9)."""

from botocore.exceptions import ClientError


class KnowledgeBaseError(Exception):
    """A knowledge-base operation failed; ``code`` is the service error code or our own."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message

    @classmethod
    def from_client_error(cls, err: ClientError) -> "KnowledgeBaseError":
        error = err.response.get("Error", {})
        return cls(error.get("Code", "Unknown"), error.get("Message", str(err)))
