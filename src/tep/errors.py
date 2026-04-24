"""TEP core exceptions."""


class TEPError(Exception):
    """Base class for protocol errors."""


class CanonicalJSONError(TEPError):
    """Raised when a value cannot be represented as canonical JSON."""


class StorageError(TEPError):
    """Raised when filesystem storage cannot satisfy protocol expectations."""


class ValidationError(TEPError):
    """Raised when a mutation would violate protocol validation."""


class NotFoundError(ValidationError):
    """Raised when a referenced protocol record is missing."""


class OwnershipError(ValidationError):
    """Raised when a signing key does not own the selected agent ledger."""


class SealError(ValidationError):
    """Raised when a ledger seal cannot be created or verified."""


class PowError(ValidationError):
    """Raised when proof-of-work does not satisfy policy."""
