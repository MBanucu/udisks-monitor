"""Stateful line parser for udisksctl monitor output."""

import re

from udisks_monitor._events import (
    DevicePropertyChanged,
    InterfaceAdded,
    InterfaceRemoved,
    JobAdded,
    JobCompleted,
    JobProperties,
    JobRemoved,
)

_ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')
_BACKING_RE = re.compile(r'BackingFile:\s+(.*)')
_OP_RE = re.compile(r'Operation:\s+(\S+)')
_OBJ_RE = re.compile(r'Objects:\s+(\S+)')

_BLOCK_DEVICES = '/block_devices/'
_JOBS_PREFIX = '/org/freedesktop/UDisks2/jobs/'
_INTERFACE_PREFIX = 'org.freedesktop.UDisks2.'
_ADDED_IFACE = 'Added interface '
_REMOVED_IFACE = 'Removed interface '
_PROPS_CHANGED = 'Properties Changed'
_JOB_COMPLETED = '::Completed'


def _device_name_from_path(line: str) -> str | None:
    idx = line.find(_BLOCK_DEVICES)
    if idx == -1:
        return None
    rest = line[idx + len(_BLOCK_DEVICES):]
    colon = rest.find(':')
    if colon != -1:
        rest = rest[:colon]
    return rest.strip()


def _interface_from_line(line: str) -> str | None:
    if _INTERFACE_PREFIX not in line:
        return None
    idx = line.find(_INTERFACE_PREFIX)
    rest = line[idx:]
    colon = rest.find(':')
    if colon != -1:
        rest = rest[:colon]
    return rest.strip()


def _object_path_from_line(line: str) -> str:
    idx = line.find('/org/')
    if idx == -1:
        return ''
    rest = line[idx:]
    colon = rest.find(':')
    if colon != -1:
        rest = rest[:colon]
    return rest


class _BlockBuffer:
    """Accumulates indented property lines for InterfaceAdded blocks."""

    def __init__(self):
        self.path = ''
        self.device = ''
        self.interface = ''
        self.properties: dict[str, str] = {}

    def reset(self):
        self.path = ''
        self.device = ''
        self.interface = ''
        self.properties = {}

    def is_active(self) -> bool:
        return bool(self.path)


class MonitorParser:
    """Stateful line parser for ``udisksctl monitor`` output.

    Feed one stripped line at a time via :meth:`feed`.  Returns an
    event object or ``None``.  Internally tracks device, interface
    and job context so that indented property lines are attributed
    correctly.
    """

    __slots__ = ('_cur_device', '_cur_interface', '_cur_object_path',
                 '_in_job', '_job_id', '_job_path', '_job_op',
                 '_job_objects', '_job_emitted', '_iface_buf')

    def __init__(self):
        self._cur_device = ''
        self._cur_interface = ''
        self._cur_object_path = ''
        self._in_job = False
        self._job_id = 0
        self._job_path = ''
        self._job_op = ''
        self._job_objects = ''
        self._job_emitted = False
        self._iface_buf = _BlockBuffer()

    def feed(self, line: str):
        clean = _ANSI_RE.sub('', line)
        event = None

        # ── indented / property line ──────────────────────────
        if clean.startswith('  '):
            return self._feed_indented(clean)

        # ── flush any pending buffered block ──────────────────
        event = self._flush_buffer()

        # ── top-level lines ───────────────────────────────────

        # Job Added
        if clean.startswith('Added ' + _JOBS_PREFIX):
            self._in_job = True
            self._job_path = clean[len('Added '):]
            self._job_id = int(self._job_path.rsplit('/', 1)[1])
            self._job_op = ''
            self._job_objects = ''
            self._job_emitted = False
            return event if event else JobAdded(
                job_path=self._job_path, job_id=self._job_id)

        # Job Removed
        if clean.startswith('Removed ' + _JOBS_PREFIX):
            jp = clean[len('Removed '):]
            jid = int(jp.rsplit('/', 1)[1])
            if jid == self._job_id:
                self._in_job = False
            ev = JobRemoved(job_path=jp, job_id=jid)
            return _merge(event, ev)

        # Job::Completed
        if _JOB_COMPLETED in clean:
            obj_path = _object_path_from_line(clean)
            jid = int(obj_path.rsplit('/', 1)[1])
            rest = clean.split('::Completed', 1)[1]
            rest = rest.strip().lstrip('(').rstrip(')')
            parts = rest.split(',', 1)
            success = parts[0].strip() == 'true'
            msg = ''
            if len(parts) > 1:
                msg = parts[1].strip().strip("'")
            ev = JobCompleted(job_path=obj_path, job_id=jid,
                              success=success, message=msg)
            return _merge(event, ev)

        # Added interface
        if _ADDED_IFACE in clean:
            obj_path = _object_path_from_line(clean)
            device = _device_name_from_path(clean) or self._cur_device
            iface = _interface_from_line(clean) or ''
            self._iface_buf.path = obj_path
            self._iface_buf.device = device
            self._iface_buf.interface = iface
            self._iface_buf.properties = {}
            self._update_context(clean, device, iface)
            return event

        # Removed interface
        if _REMOVED_IFACE in clean:
            device = _device_name_from_path(clean) or self._cur_device
            iface = _interface_from_line(clean) or ''
            self._update_context(clean, device, iface)
            ev = InterfaceRemoved(object_path=_object_path_from_line(clean),
                                  device_name=device, interface=iface)
            return _merge(event, ev)

        # Properties Changed
        if _PROPS_CHANGED in clean:
            device = _device_name_from_path(clean) or self._cur_device
            iface = _interface_from_line(clean) or ''
            self._update_context(clean, device, iface)
            return event

        # Other top-level line (preamble, empty, drive path, etc.)
        device = _device_name_from_path(clean)
        if device:
            self._cur_device = device
        return event

    def _feed_indented(self, clean):
        # Job property lines (4-space indent) — capture above device parsing
        if self._in_job:
            if clean.startswith('    '):
                if not self._job_emitted:
                    m = _OP_RE.search(clean)
                    if m:
                        self._job_op = m.group(1)
                    m = _OBJ_RE.search(clean)
                    if m:
                        self._job_objects = m.group(1)
                    if self._job_op and self._job_objects:
                        self._job_emitted = True
                        return JobProperties(job_path=self._job_path,
                                             job_id=self._job_id,
                                             operation=self._job_op,
                                             objects=self._job_objects)
                return None
            # ``  org.freedesktop.UDisks2.Job:`` header — ignore
            if 'UDisks2.Job' in clean:
                return None

        # Inside an interface-added block — accumulate properties
        if self._iface_buf.is_active():
            colon = clean.find(':')
            if colon != -1:
                prop = clean[2:colon].strip()
                value = clean[colon + 1:].strip()
                self._iface_buf.properties[prop] = value
            return None

        # Indented line under current device — emit as DevicePropertyChanged
        if self._cur_device:
            colon = clean.find(':')
            if colon != -1:
                prop = clean[2:colon].strip()
                value = clean[colon + 1:].strip()
                return DevicePropertyChanged(
                    object_path=self._cur_object_path,
                    device_name=self._cur_device,
                    interface=self._cur_interface,
                    property=prop,
                    value=value,
                )

        return None

    def _flush_buffer(self):
        if not self._iface_buf.is_active():
            return None
        ev = InterfaceAdded(
            object_path=self._iface_buf.path,
            device_name=self._iface_buf.device,
            interface=self._iface_buf.interface,
            properties=dict(self._iface_buf.properties),
        )
        self._iface_buf.reset()
        return ev

    def _update_context(self, clean, device, iface):
        if device:
            self._cur_device = device
        if iface:
            self._cur_interface = iface
        if '/' in clean and ':' in clean:
            self._cur_object_path = clean.split(':')[0]


def _merge(first, second):
    if first is None:
        return second
    if second is None:
        return first
    raise NotImplementedError(
        "parser produced two top-level events for a single line")
