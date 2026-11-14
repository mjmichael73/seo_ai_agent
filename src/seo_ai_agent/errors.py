"""Application-level errors with safe, user-facing messages."""


class AuditError(RuntimeError):
    """Base class for errors that can be reported to an audit user."""


class UnsafeTargetError(AuditError):
    """Raised when a requested URL is not safe to fetch."""


class CrawlError(AuditError):
    """Raised when a public website cannot be fetched or parsed safely."""
