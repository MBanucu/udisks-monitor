"""Subprocess backend — spawns ``udisksctl monitor`` and parses stdout."""

from __future__ import annotations

import os
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

        os.set_blocking(proc.stdout.fileno(), False)

        timer = threading.Timer(0.5, self.ready.set)
        timer.daemon = True
        timer.start()

        try:
            self._read_loop(proc)
        finally:
            timer.cancel()
            proc.stdout.close()
            proc.terminate()
            proc.wait()

    def _read_loop(self, proc):
        fd = proc.stdout.fileno()
        buf = ''
        while not self._stop_event.is_set():
            try:
                data = os.read(fd, 4096)
            except BlockingIOError:
                self._stop_event.wait(0.05)
                continue
            except OSError:
                break
            if not data:
                break
            buf += data.decode('utf-8', errors='replace')
            while '\n' in buf:
                line, buf = buf.split('\n', 1)
                self._feed(line + '\n')

    def _feed(self, line: str):
        event = self._parser.feed(line)
        if event is not None:
            self.ready.set()
            self._publish(event)

    def stop(self):
        self._stop_event.set()
        if self._proc is not None:
            self._proc.terminate()
