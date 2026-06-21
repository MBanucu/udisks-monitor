"""Protocol class for UDisks2 event-source backends."""

from __future__ import annotations

import threading
from collections.abc import Callable

from udisks_monitor._events import Event


class _Backend:
    """Abstract backend for monitoring UDisks2 events.

    Parameters
    ----------
    publish:
        Callback invoked with each :class:`Event` as it occurs.
    """

    def __init__(self, publish: Callable[[Event], None]):
        self._publish = publish
        self.ready = threading.Event()

    def run(self) -> None:
        """Block until :meth:`stop` is called from another thread.

        Subclasses must call ``self.ready.set()`` once connected.
        """
        raise NotImplementedError

    def stop(self) -> None:
        """Signal :meth:`run` to exit from another thread."""
        raise NotImplementedError
