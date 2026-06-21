"""Subprocess backend — spawns ``udisksctl monitor`` and parses stdout."""

from __future__ import annotations

import subprocess
import threading
import time

from udisks_monitor._backends._base import _Backend
from udisks_monitor._parser import MonitorParser


class _SubprocessBackend(_Backend):
    """Spawns ``udisksctl monitor`` and feeds its output to :class:`MonitorParser`."""

    def __init__(self, publish):
        super().__init__(publish)
        self._parser = MonitorParser()
        self._proc = None
        self._stop_event = threading.Event()

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

        try:
            first = proc.stdout.readline()
        except Exception:
            proc.terminate()
            proc.wait()
            self.ready.set()
            return

        self._feed(first)
        time.sleep(0.5)
        self.ready.set()

        try:
            for line in proc.stdout:
                if self._stop_event.is_set():
                    break
                self._feed(line)
        finally:
            proc.stdout.close()
            proc.terminate()
            proc.wait()

    def _feed(self, line: str):
        event = self._parser.feed(line)
        if event is not None:
            self.ready.set()
            self._publish(event)

    def stop(self):
        self._stop_event.set()
        if self._proc is not None:
            self._proc.terminate()
