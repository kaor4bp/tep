"""Server exception types."""


class TEPError(Exception):
    """Base class for server errors."""


class CanonicalJSONError(TEPError):
    """Raised when a value cannot be represented as canonical JSON."""
