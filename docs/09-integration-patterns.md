# 09 — Integration Patterns

How to integrate `udisksctl monitor` into a Python application.

## Pattern 1: Detach confirmation (unmount-image)

The primary integration pattern used by `unmount-image`:

```
┌─────────────────────────────────────────────┐
│  umount_image(device)                       │
│    │                                         │
│    ├─ 1. unmount (strategy)                 │
│    │                                         │
│    └─ 2. detach_loop(device)                │
│          │                                   │
│          └─ _DetachThread(device).start()   │
│               │                              │
│               ├─ start _UdisksMonitor       │
│               │                              │
│               └─ loop:                      │
│                    unmount                   │
│                    loop-delete               │
│                    wait for monitor feedback  │
│                      ├─ backing_cleared? → done │
│                      ├─ mount_detected? → retry │
│                      └─ timeout → fallback    │
└─────────────────────────────────────────────┘
```

### The _DetachThread state machine

```python
def _run_detach(self):
    monitor = _UdisksMonitor(device_name)
    monitor.start()
    monitor.ready.wait(timeout=10)

    while True:
        monitor.reset_events()
        _unmount_normal(device, None)
        time.sleep(0.15)
        loop_delete(device)

        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if monitor.mount_detected.is_set():
                break          # re-mounted, retry
            if monitor.backing_cleared.is_set():
                time.sleep(0.3)
                if monitor.mount_detected.is_set():
                    break      # re-mounted during grace period
                return         # confirmed detached
            time.sleep(0.1)
        else:
            _fallback_detach(name, device)
            return
```

### Key design decisions

1. **Daemon threads**: both `_UdisksMonitor` and `_DetachThread` are daemon
   threads. They won't block process exit.
2. **`threading.Event` signalling**: `backing_cleared` and `mount_detected`
   are cross-thread signals set by the monitor thread, waited on by the
   detach thread.
3. **Ready signal**: `monitor.ready.wait(timeout=10)` ensures the monitor
   has connected to D-Bus before any detach attempt.
4. **Grace period**: after `backing_cleared`, a 0.3 s sleep + re-check of
   `mount_detected` catches the last-moment re-mount.
5. **Fallback**: if the monitor doesn't confirm detach within 10 s, a
   polling-based fallback (`_fallback_detach`) uses
   `/sys/block/<name>/backing_file` existence to confirm deletion.

## Pattern 2: Device appearance watcher

Watching for new devices as they appear:

```python
def watch_for_device(expected_backing_file):
    import subprocess, re

    BACKING_RE = re.compile(r'BackingFile:\s+(.*)')
    current_device = ''

    proc = subprocess.Popen(
        ['udisksctl', 'monitor'],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)

    for line in proc.stdout:
        # Extract device name from path
        if '/block_devices/' in line:
            rest = line.split('/block_devices/')[1]
            colon = rest.find(':')
            if colon != -1:
                rest = rest[:colon]
            current_device = rest.strip()

        m = BACKING_RE.search(line)
        if m and current_device:
            backing = m.group(1).strip()
            if backing == expected_backing_file:
                return current_device
```

## Pattern 3: Mount point change watcher

Detecting when a filesystem is mounted or unmounted:

```python
def watch_mount_changes(device_name):
    """Yield mount state changes for a specific device."""
    import subprocess, re

    MOUNT_RE = re.compile(r'MountPoints:\s+(.*)')

    proc = subprocess.Popen(
        ['udisksctl', 'monitor'],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)

    current_device = ''

    for line in proc.stdout:
        if '/block_devices/' in line:
            rest = line.split('/block_devices/')[1]
            colon = rest.find(':')
            if colon != -1:
                rest = rest[:colon]
            current_device = rest.strip()

        if current_device == device_name:
            m = MOUNT_RE.search(line)
            if m:
                mount_points = [p for p in m.group(1).strip().split(',') if p]
                yield mount_points
```

## Pattern 4: Job result watcher

Waiting for a specific operation to complete:

```python
def wait_for_job_completion(device_name, expected_op):
    import subprocess, re, threading

    OP_RE = re.compile(r'Operation:\s+(\S+)')
    OBJ_RE = re.compile(r'Objects:\s+(\S+)')
    result = None
    event = threading.Event()

    proc = subprocess.Popen(
        ['udisksctl', 'monitor'],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)

    in_job = False
    for line in proc.stdout:
        if 'Added /org/freedesktop/UDisks2/jobs/' in line:
            in_job = True
            job_op = ''
            job_objects = ''
        elif 'Removed /org/freedesktop/UDisks2/jobs/' in line:
            in_job = False

        if in_job:
            m = OP_RE.search(line)
            if m:
                job_op = m.group(1)
            m = OBJ_RE.search(line)
            if m:
                job_objects = m.group(1)
            if job_op == expected_op and device_name in job_objects:
                if 'Job::Completed' in line:
                    result = 'true' in line
                    event.set()

        if event.wait(0):
            break

    proc.terminate()
    return result
```

## Threading considerations

### Monitor startup latency

`udisksctl monitor` needs to:
1. Fork a subprocess.
2. Connect to the D-Bus system bus.
3. Resolve the UDisks2 name owner.
4. Print the preamble.

On a typical system this takes **100–500 ms**. A `threading.Event` signal
after the first `readline()` succeeds is the recommended way to know the
monitor is ready.

### Graceful shutdown

```python
monitor._stop.set()       # signal the run loop
monitor.join(timeout=3)   # wait for thread exit
```

Inside the run loop, `subprocess.Popen` is terminated:

```python
proc.stdout.close()
proc.terminate()
proc.wait()
```

### Multiple monitors

Running multiple `udisksctl monitor` processes is safe — each gets an
independent D-Bus signal subscription. There is no practical limit beyond
system resources.

## Comparison with D-Bus directly

| Approach | Pros | Cons |
|----------|------|------|
| `udisksctl monitor` | No dependencies, simple text parsing, works from CLI | Subprocess overhead, text parsing is fragile |
| `pydbus` / `dasbus` | Native object model, type-safe | Requires Python D-Bus bindings and GLib event loop |
| `dbus-monitor --system` | Raw D-Bus, no UDisks2 dep | Very verbose, no semantic formatting |
| `gi.repository.UDisks` | Official GLib binding | Requires typelib, GLib main loop |

For `unmount-image`, the `udisksctl monitor` approach is the right trade-off:
zero dependencies, simple enough for a small library, and robust for the
specific signals it watches.
