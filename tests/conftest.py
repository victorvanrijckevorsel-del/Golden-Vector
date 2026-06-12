"""Suite-wide guards.

The whole suite runs offline: external paid API calls (Yahoo market data)
require explicit user approval per the house rules, so a test that forgets a
monkeypatch must fail loudly here, never silently fetch live data.
"""

from __future__ import annotations

import socket

import pytest

_REAL_SOCKET = socket.socket


class _NetworkBlockedError(RuntimeError):
    pass


class _GuardedSocket(_REAL_SOCKET):
    def connect(self, address):  # type: ignore[override]
        host = address[0] if isinstance(address, tuple) else address
        if str(host) not in {"127.0.0.1", "localhost", "::1"}:
            raise _NetworkBlockedError(
                f"Tests must not hit the network (attempted connect to {host!r}). "
                "Monkeypatch the fetcher instead."
            )
        return super().connect(address)


@pytest.fixture(autouse=True)
def _block_external_network(monkeypatch):
    monkeypatch.setattr(socket, "socket", _GuardedSocket)
    yield
