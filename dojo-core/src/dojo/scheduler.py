"""Coordination boundary for short, database-only scheduling turns."""

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from typing import Protocol

# Stable signed bigint: ASCII "DOJOEMIT". All scheduler processes in a database
# must use this same key; never derive it from Python's randomized hash().
SCHEDULER_EMISSION_LOCK_KEY = 0x444F4A4F454D4954


class EmissionCoordinator(Protocol):
    def emission_transaction(self) -> AbstractContextManager[None]: ...

    def try_advisory_xact_lock(self, key: int) -> bool: ...


@contextmanager
def try_emission_leadership(store: EmissionCoordinator) -> Iterator[bool]:
    """Yield whether this turn may emit; caller must skip work when False.

    Keep every emission write inside this scope using the same store instance.
    Nested scopes are rejected. Exceptions propagate after rollback; the next
    turn gets a fresh transaction. Rendering and HTTP belong outside this scope.
    """
    with store.emission_transaction():
        yield store.try_advisory_xact_lock(SCHEDULER_EMISSION_LOCK_KEY)
