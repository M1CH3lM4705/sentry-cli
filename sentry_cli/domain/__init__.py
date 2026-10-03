"""
Domínio do subsistema Sentry CLI.
"""

from sentry_cli.domain.value_objects import (
    CommandStatement,
    ExecutionContext,
    CommandExecutionResult,
    SecurityViolationError,
)
from sentry_cli.domain.entities import SentryExecutionResult
from sentry_cli.domain.interfaces import (
    ILLMProvider,
    ICommandExecutor,
    IAuditLogger,
)

__all__ = [
    "CommandStatement",
    "ExecutionContext",
    "CommandExecutionResult",
    "SecurityViolationError",
    "SentryExecutionResult",
    "ILLMProvider",
    "ICommandExecutor",
    "IAuditLogger",
]
