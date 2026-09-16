"""Request-local visitor identity for shared presentation; never authorization.

The hosted gate and read-only router enforce authorization. This context only
keeps admin controls out of visitor pages without process-global state leakage.
"""

from contextvars import ContextVar
from golden_vector.access.store import Session

visitor_session: ContextVar[Session | None] = ContextVar("visitor_session", default=None)


def is_visitor() -> bool:
    return visitor_session.get() is not None
