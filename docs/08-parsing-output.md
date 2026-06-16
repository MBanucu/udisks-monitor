# 08 — Parsing Monitor Output

`udisks-monitor` parses `udisksctl monitor` output with a **stateful
line-by-line parser**. This document explains the parsing strategy and design
rationale.

## Design constraints

1. **Real-time**: events must be detected as lines arrive (no buffering).
2. **Lightweight**: minimal non-stdlib dependencies (`strip-ansi` only).
3. **Fault-tolerant**: ANSI codes, warnings on stderr, and empty lines must
   not break parsing.
4. **Complete**: all 7 UDisks2 event types are captured.

## Architecture

```
udisksctl monitor --stdout--> UdisksMonitor thread --line-by-line--> MonitorParser --events--> EventBus.publish()
```

### Step 1: Timestamp and ANSI stripping

Lines arrive with a `HH:MM:SS.mmm: ` timestamp prefix and optional ANSI
colour codes:

```
\x1b[1m\x1b[33m12:03:36.774:\x1b[0m \x1b[1m\x1b[34m/org/.../loop3:\x1b[0m ...
```

The parser strips both:

```python
from strip_ansi import strip_ansi

def feed(self, line: str):
    clean = strip_ansi(line)            # remove ANSI SGR sequences
    m = _TIMESTAMP_RE.match(clean)
    if m:
        self._ts = m.group(0)[:-2]      # capture HH:MM:SS.mmm
    clean = _TIMESTAMP_RE.sub('', clean) # remove timestamp prefix
```

The timestamp is captured **before** stripping and attached to every event
as `event.timestamp`.  It persists across indented lines that belong to the
same top-level event (indented property lines carry no timestamp of their own).

### Step 2: State tracking

`MonitorParser` is a stateful object with the following slots:

| Slot | Type | Purpose |
|------|------|---------|
| `_ts` | str | Current timestamp (persists across indented lines) |
| `_cur_device` | str | Last-seen block device name |
| `_cur_interface` | str | Last-seen D-Bus interface |
| `_cur_object_path` | str | Last-seen object path |
| `_in_job` | bool | True while inside a job block |
| `_job_id` | int | Current job's numeric identifier |
| `_job_path` | str | Current job's object path |
| `_job_op` | str | Accumulated `Operation` value |
| `_job_objects` | str | Accumulated `Objects` value |
| `_job_emitted` | bool | Prevents re-emitting the same job |
| `_iface_buf` | _BlockBuffer | Buffers `InterfaceAdded` properties |

### Step 3: Top-level line dispatch

Top-level lines (0 indent) are dispatched by pattern matching:

| Pattern | Match | Event emitted |
|---------|-------|---------------|
| `Added /org/.../jobs/N` | `startswith` | `JobAdded` |
| `Removed /org/.../jobs/N` | `startswith` | `JobRemoved` |
| `...Job::Completed (true, '')` | `in` substring | `JobCompleted` |
| `Added interface org.freedesktop.UDisks2.X` | `in` substring | (buffered, emitted on next top-level line as `InterfaceAdded`) |
| `Removed interface org.freedesktop.UDisks2.X` | `in` substring | `InterfaceRemoved` |
| `Properties Changed` | `in` substring | (sets device/interface context, actual property events come from indented lines) |

### Step 4: Indented line handling

**2-space indented** lines under a device context emit `DevicePropertyChanged`:

```python
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
            timestamp=self._ts,
        )
```

**4-space indented** lines inside a job block are scanned for `Operation`
and `Objects` fields.  When both are captured, `JobProperties` is emitted.

**Indented lines inside an `InterfaceAdded` block** (between the `Added
interface` header and the next top-level line) accumulate property key/value
pairs.  These are flushed as an `InterfaceAdded` event when the next
top-level line arrives.

### Step 5: Device name extraction

```python
def _device_name_from_path(line):
    idx = line.find('/block_devices/')
    if idx == -1:
        return None
    rest = line[idx + len('/block_devices/'):]
    colon = rest.find(':')
    if colon != -1:
        rest = rest[:colon]
    return rest.strip()
```

Extracts `loop0` from paths like:
- `/org/freedesktop/UDisks2/block_devices/loop0:`
- `/org/freedesktop/UDisks2/block_devices/loop0`

The extracted name sets `_cur_device`.

## Parsing edge cases

### Timestamp on indented lines

Only top-level lines carry timestamps.  The parser persists `_ts` from the
last timestamped line, so indented property events get the timestamp of their
parent header.

### Job Added/Removed without Complete

If a job is cancelled, `Removed` may appear without a prior `::Completed`.
The parser correctly exits the job context on `Removed`.

### Rapidly consecutive jobs

Jobs can be Added and Removed in quick succession.  The parser tracks one job
at a time.  If a second `Added` appears before the first `Removed`, the state
is reset.  In practice, UDisks2 serializes jobs per-object.

### Multi-line property values

Properties like `Symlinks` span multiple continuation lines.  Each
continuation line is captured as a separate `DevicePropertyChanged` event with
the same property name — consumers should coalesce them.

### ANSI on stderr

The monitor sometimes prints ANSI-coloured warnings to stderr.  Since
`UdisksMonitor` redirects stderr to `subprocess.DEVNULL`, these are silently
discarded.

## Alternative approaches

1. **GDBus directly**: connect to the system bus and subscribe to
   `org.freedesktop.UDisks2` signals — more efficient, no text parsing
   needed, but requires `gi.repository.GLib` / `pydbus` dependency.
2. **`dbus-monitor`**: similar text-based approach but no UDisks2-specific
   formatting.
3. **Polling `/sys/block/loopN/loop/backing_file`**: simpler, no monitor
   needed, but event-driven is more responsive.

The text-parsing approach was chosen because it has a single lightweight
dependency (`strip-ansi`) and works with `udisksctl monitor` as-is, without
requiring D-Bus bindings.
