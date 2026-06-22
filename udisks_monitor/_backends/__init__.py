"""Backend selection for UdisksMonitor."""

from __future__ import annotations

from collections.abc import Callable

from udisks_monitor._backends._base import _Backend
from udisks_monitor._events import Event


def _get_backend(name: str, publish: Callable[[Event], None]) -> _Backend:
    """Return a backend instance for the given *name*.

    Parameters
    ----------
    name:
        ``'auto'`` — use the D-Bus backend (default).
        ``'subprocess'`` — use ``udisksctl monitor`` text parsing.
        ``'dbus'`` — same as ``'auto'`` (direct D-Bus).
    """
    from udisks_monitor._backends._dbus import _DBusBackend
    from udisks_monitor._backends._subprocess import _SubprocessBackend

    if name == 'subprocess':
        return _SubprocessBackend(publish)

    if name in ('auto', 'dbus'):
        return _DBusBackend(publish)

    raise ValueError(
        f"Unknown backend: {name!r}; expected 'auto', 'subprocess', or 'dbus'")
