"""Centralized custom exceptions for Resolv."""


class ResolvError(Exception):
    """Base class for all Resolv errors."""


class IngestionError(ResolvError):
    """Raised when issue or repository ingestion fails."""


class SandboxError(ResolvError):
    """Raised when isolated test execution cannot be launched."""


class InstallError(ResolvError):
    """Raised when installing the target repo's dependencies fails."""


class DeliveryError(ResolvError):
    """Raised when branch creation, commit, or PR opening fails."""


class CoderError(ResolvError):
    """Raised when a Coder backend cannot produce or apply a valid patch."""


class ConfigError(ResolvError):
    """Configuration missing, invalid, or referencing an unknown option.

    Currently unraised: pydantic-settings validates Settings on construction.
    """


class LoopStallError(ResolvError):
    """The LangGraph loop exceeded max_iterations without converging.

    Currently unraised: the gate routes a stalled loop to END, and `resolv run`
    reports non-convergence with a message and a non-zero exit code instead.
    """
