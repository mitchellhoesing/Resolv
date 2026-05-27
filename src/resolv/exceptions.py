"""Centralized custom exceptions for Resolv."""


class ResolvError(Exception):
    """Base class for all Resolv errors."""


class IngestionError(ResolvError):
    """Raised when issue or repository ingestion fails."""


class SandboxError(ResolvError):
    """Raised when a Docker sandbox execution fails or times out."""


class QAGateError(ResolvError):
    """Raised when the CodeRabbit QA gate cannot be evaluated."""


class DeliveryError(ResolvError):
    """Raised when branch creation, commit, or PR opening fails."""


class LoopStallError(ResolvError):
    """Raised when the LangGraph loop exceeds max_iterations without converging."""
