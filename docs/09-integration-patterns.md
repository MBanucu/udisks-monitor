# 09 — Integration Patterns

How to integrate `udisks-monitor` and `udisksctl monitor` into a Python application.

## Pattern 1: Event-driven loop device lifecycle (udisks-monitor)

The primary integration pattern provided by `udisks-monitor`:

```python
from udisks_monitor import UdisksMonitor, DevicePropertyChanged, JobCompleted

mon = UdisksMonitor()

@mon.on(DevicePropertyChanged, device='loop0', property_='BackingFile')
def on_backing(evt):
    if not evt.value:
        print(f"{evt.device_name} backing file cleared at {evt.timestamp}")

@mon.on(JobCompleted, operation='loop-delete')
def on_deleted(evt):
    print(f"loop-delete complete: success={evt.success}")

mon.start()
mon.join()
```

### Key design decisions

1. **Daemon thread**: `UdisksMonitor` is a daemon thread — won't block process exit.
2. **Pre-start subscriptions**: callbacks registered before `start()` are active
   immediately when the monitor connects to D-Bus.
3. **`ready` signal**: `mon.ready.wait(timeout=10)` ensures the monitor
   has connected to D-Bus before triggering any UDisks2 operations.
4. **Event-driven stop**: use `threading.Event` or `EventBus` subscription
   filters to wait for specific events rather than polling.

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
mon.stop()                # signal the run loop + terminate subprocess
mon.join(timeout=3)       # wait for thread exit
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

For `udisks-monitor`, the `udisksctl monitor` approach is the right trade-off:
a single lightweight dependency (`strip-ansi`), simple enough for a small library,
and robust for all UDisks2 signal types.
