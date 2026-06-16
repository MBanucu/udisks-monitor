# 08 — Parsing Monitor Output

`unmount-image` parses `udisksctl monitor` output with a **stateful
line-by-line parser**. This document explains the parsing strategy and design
rationale.

## Design constraints

1. **Real-time**: events must be detected as lines arrive (no buffering).
2. **Minimal dependencies**: standard library only (`re`, `threading`).
3. **Fault-tolerant**: ANSI codes, warnings on stderr, and empty lines must
   not break parsing.
4. **Selective**: only two event types are needed — `filesystem-mount` jobs
   and `BackingFile` property changes.

## Architecture

```
udisksctl monitor --stdout--> _UdisksMonitor thread --line-by-line--> _MonitorParser --events--> _handle_event
```

### Step 1: ANSI stripping

```python
_ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')

clean = _ANSI_RE.sub('', line)
```

All SGR sequences are removed before pattern matching. This simplifies the
rest of the parser.

### Step 2: State tracking

`_MonitorParser` is a stateful object with four slots:

| Slot | Type | Purpose |
|------|------|---------|
| `_in_job` | bool | True while inside a job block |
| `_job_op` | str | Accumulated `Operation` value |
| `_job_objects` | str | Accumulated `Objects` value |
| `_emitted` | bool | Prevents re-emitting the same job |
| `_current_device` | str | Last-seen block device name |

### Step 3: Job entry/exit

```
Added /org/.../jobs/N    → _in_job = True, reset accumulators
Removed /org/.../jobs/N  → _in_job = False
```

### Step 4: Job property accumulation

While `_in_job` and not yet emitted:

```python
_OP_RE   = re.compile(r'Operation:\s+(\S+)')
_OBJ_RE  = re.compile(r'Objects:\s+(\S+)')
```

When **both** `Operation` and `Objects` have been captured, an event is emitted:

```python
return ('job', {'op': 'filesystem-mount',
                'objects': '/org/.../block_devices/loop0'})
```

Subsequent lines in the same job are ignored (`_emitted = True`).

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

This extracts `loop0` from paths like:
- `/org/freedesktop/UDisks2/block_devices/loop0:`
- `/org/freedesktop/UDisks2/block_devices/loop0` (no colon)

The extracted name sets `_current_device`.

### Step 6: Property line matching

While `_current_device` is set:

```python
_BACKING_RE = re.compile(r'BackingFile:\s+(.*)')
```

If a line matches, emit:

```python
('loop_prop', {
    'device': 'loop0',
    'prop': 'BackingFile',
    'value': '/tmp/img'  # or '' if empty
})
```

### Step 7: Event handling

`_UdisksMonitor._handle_event` filters events:

```python
if etype == 'job':
    if (data['op'] == 'filesystem-mount' and
            self._name in data['objects']):
        self.mount_detected.set()

elif etype == 'loop_prop':
    if (data['device'] == self._name and
            data['prop'] == 'BackingFile' and
            not data['value']):
        self.backing_cleared.set()
```

## Parsing edge cases

### Job objects matches device name substring

The `Objects` field contains a full object path like
`/org/.../block_devices/loop0`. Using `in` to match the device name could
falsely match `loop0` inside `loop10`:

```
Objects: .../block_devices/loop10  ← would match 'loop0' via 'in'
```

**Mitigation**: the object path uses the exact kernel name. A `loop10` is
`/block_devices/loop10`, not `loop1` followed by `0`. But to be safe, a
stricter match like `f'/block_devices/{name}' in objects` would be more
robust.

### Multi-line property values

`BackingFile` is always a single line. Other properties like `Symlinks` span
multiple lines. Since `_MonitorParser` only looks at `BackingFile`, multi-line
values are not a concern for this parser. A general-purpose parser would need
to handle continuation lines.

### Empty BackingFile vs whitespace

```
  BackingFile:
  BackingFile:          (trailing spaces)
  BackingFile:          
```

All should be treated as empty. The regex `BackingFile:\s+(.*)` with `.strip()`
on the captured group handles this correctly: all three produce `''`.

### Job Added/Removed without Complete

If a job is cancelled, `Removed` may appear without a prior `::Completed`. The
parser correctly exits the job context on `Removed`.

### Rapidly consecutive jobs

Jobs can be Added and Removed in quick succession. The parser tracks one job
at a time. If a second `Added` appears before the first `Removed`, the state
is reset — the first job's data is discarded. In practice, UDisks2 serializes
jobs per-object, so this is extremely rare.

### ANSI on stderr

The monitor sometimes prints ANSI-coloured warnings to stderr. Since
`_UdisksMonitor` redirects stderr to `subprocess.DEVNULL`, these are silently
discarded.

## Alternative approaches

1. **GDBus directly**: connect to the system bus and subscribe to
   `org.freedesktop.UDisks2` signals — more efficient, no text parsing
   needed, but requires `gi.repository.GLib` / `pydbus` dependency.
2. **`dbus-monitor`**: similar text-based approach but no UDisks2-specific
   formatting.
3. **Polling `/sys/block/loopN/loop/backing_file`**: simpler, no monitor
   needed, but event-driven is more responsive for the detach race.

The text-parsing approach was chosen for `unmount-image` because it has zero
dependencies beyond the Python standard library.
