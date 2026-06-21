"""Subprocess backend — spawns ``udisksctl monitor`` and parses stdout."""

from __future__ import annotations

import subprocess
import threading

from udisks_monitor._backends._base import _Backend
from udisks_monitor._events import (
    DevicePropertyChanged,
    InterfaceAdded,
    InterfaceRemoved,
    JobAdded,
    JobCompleted,
    JobProperties,
    JobRemoved,
)
from udisks_monitor._parser import MonitorParser


class _SubprocessBackend(_Backend):
    """Spawns ``udisksctl monitor`` and feeds its output to :class:`MonitorParser`."""

    def __init__(self, publish):
        super().__init__(publish)
        self._parser = MonitorParser()
        self._proc = None
        self._stop_event = threading.Event()
        self._keywords: frozenset[str] = frozenset()
        self._all_types_interesting = True
        self._tracking_iface_block = False
        self._need_indented = False
        self._bus = None
        self._subscribed_types: frozenset = frozenset()

    def run(self):
        self._init_prefilter()
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

    def _init_prefilter(self):
        try:
            bus = self._publish.__self__.bus
        except (AttributeError, TypeError):
            self._all_types_interesting = True
            return

        if not hasattr(bus, 'subscribed_types'):
            self._all_types_interesting = True
            return

        types = bus.subscribed_types
        if types is None:
            self._all_types_interesting = True
            return

        self._bus = bus
        self._subscribed_types = types
        self._all_types_interesting = False
        keywords: set[str] = set()

        for et, kw in [
            (InterfaceAdded, 'Added interface '),
            (InterfaceRemoved, 'Removed interface '),
            (JobAdded, 'Added /org/freedesktop/UDisks2/jobs/'),
            (JobRemoved, 'Removed /org/freedesktop/UDisks2/jobs/'),
            (JobCompleted, '::Completed'),
        ]:
            if et in types:
                keywords.add(kw)

        if DevicePropertyChanged in types:
            keywords.add('/block_devices/')
            keywords.add('Properties Changed')

        if JobProperties in types:
            keywords.add('Operation:')
            keywords.add('Objects:')
            keywords.add('/org/freedesktop/UDisks2/jobs/')

        if DevicePropertyChanged in types or JobProperties in types:
            self._need_indented = True

        self._keywords = frozenset(keywords)

    def _line_matters(self, line: str) -> bool:
        if not line:
            return True

        if line[0].isdigit():
            return True

        if self._tracking_iface_block:
            return True

        if self._need_indented and line.startswith('  '):
            return True

        for kw in self._keywords:
            if kw in line:
                return True

        return False

    def _feed(self, line: str):
        if not self._all_types_interesting and not self._line_matters(line):
            return
        event = self._parser.feed(line)
        if event is not None:
            self.ready.set()
            if isinstance(event, InterfaceAdded):
                self._tracking_iface_block = False
            if self._all_types_interesting or type(event) in self._subscribed_types:
                self._publish(event)
        # After parser processing: check if current line starts a new
        # buffering block (the parser only returns flushed events).
        if (not self._all_types_interesting
                and InterfaceAdded in self._subscribed_types
                and 'Added interface ' in line):
            self._tracking_iface_block = True

    def stop(self):
        self._stop_event.set()
        if self._proc is not None:
            self._proc.terminate()
