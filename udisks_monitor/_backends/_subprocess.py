"""Subprocess backend — spawns ``udisksctl monitor`` and parses stdout."""

from __future__ import annotations

import subprocess
import threading

from udisks_monitor._backends._base import _Backend
from udisks_monitor._parser import MonitorParser


class _SubprocessBackend(_Backend):
    """Spawns ``udisksctl monitor`` and feeds its output to :class:`MonitorParser`."""

    def __init__(self, publish):
        super().__init__(publish)
        self._parser = MonitorParser()
        self._proc = None
        self._stop_event = threading.Event()
        self._pub = publish
        self._all_types_interesting = True
        self._subscribed_types: frozenset = frozenset()

    def run(self):
        try:
            proc = subprocess.Popen(
                ['udisksctl', 'monitor'],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
            self._proc = proc
        except Exception:
            self.ready.set()
            return

        timer = threading.Timer(0.5, self.ready.set)
        timer.daemon = True
        timer.start()

        try:
            first = proc.stdout.readline()
        except Exception:
            proc.terminate()
            proc.wait()
            timer.cancel()
            self.ready.set()
            return

        self._feed(first)

        try:
            for line in proc.stdout:
                if self._stop_event.is_set():
                    break
                self._feed(line)
        finally:
            timer.cancel()
            proc.stdout.close()
            proc.terminate()
            proc.wait()

    def _refresh_filter(self):
        try:
            bus = self._pub.__self__.bus
        except (AttributeError, TypeError):
            self._all_types_interesting = True
            return
        types = bus.subscribed_types
        if types is None or len(types) == 0:
            self._all_types_interesting = True
            return
        self._subscribed_types = types
        self._all_types_interesting = False

    def _feed(self, line: str):
        event = self._parser.feed(line)
        if event is not None:
            self.ready.set()
            if self._all_types_interesting:
                self._refresh_filter()
            if self._all_types_interesting or type(event) in self._subscribed_types:
                self._publish(event)

    def stop(self):
        self._stop_event.set()
        if self._proc is not None:
            self._proc.terminate()
