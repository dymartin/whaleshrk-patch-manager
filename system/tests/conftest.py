"""Shared test fixtures.

Every fixture that later phases test against is frozen (see fixtures/README.md
and docs/decisions.md #42): CI replays committed data and must never reach the
network. This blocks socket creation for the whole test session so a test
that accidentally tries to fetch live data fails loudly instead of silently
depending on network availability.
"""

import socket

import pytest


class _NetworkBlocked(RuntimeError):
    pass


def _blocked_socket(*args, **kwargs):
    raise _NetworkBlocked("tests must not open network sockets; fixtures are frozen")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(socket, "socket", _blocked_socket)
    monkeypatch.setattr(socket, "create_connection", _blocked_socket)
