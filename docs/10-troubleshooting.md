# 10 — Troubleshooting

Common issues, warnings, and edge cases when working with `udisksctl monitor`.

## Known stderr warnings

### `runtime check failed: (g_strv_length ((gchar **) invalidated_properties) == 0)`

```
** (udisksctl monitor:2540566): WARNING **: 12:03:37.002: (udisksctl.c:2811):
monitor_on_interface_proxy_properties_changed: runtime check failed:
(g_strv_length ((gchar **) invalidated_properties) == 0)
```

- **Cause**: UDisks2 sends D-Bus `PropertiesChanged` signals where the
  `invalidated_properties` array is non-empty. The monitor's handler expects
  it to always be empty (because UDisks2 always sends the full
  changed-properties dict).
- **Severity**: benign. The event is still printed correctly on stdout.
- **Fix**: none needed. If this bothers you, redirect stderr to `/dev/null`:
  ```python
  subprocess.Popen(['udisksctl', 'monitor'], stderr=subprocess.DEVNULL)
  ```

### GLib assertion warnings

Rare, typically on daemon restart or D-Bus disconnection. Same treatment:
redirect stderr.

## Monitor not starting

### "Error creating textual authentication agent"

```
Error creating textual authentication agent: Error opening current controlling
terminal for the process (`/dev/tty'): No such device or address
```

- **Cause**: Running in an environment without a TTY (cron, systemd service,
  SSH without `-t`).
- **Impact**: `udisksctl monitor` itself does **not** need authentication, but
  the polkit agent lookup can fail. The monitor should still start.
- **Workaround**: ensure D-Bus session bus is available, or use `dbus-run-session`.

### Monitor hangs on startup

If `udisksctl monitor` prints the preamble but never prints the name-owner
line:

- The UDisks2 daemon may not be running. Start it:
  ```bash
  systemctl start udisks2
  ```
  or
  ```bash
  udisksd &
  ```
- The system D-Bus may not be accessible. Check:
  ```bash
  dbus-send --system --dest=org.freedesktop.UDisks2 \
    /org/freedesktop/UDisks2 org.freedesktop.DBus.Peer.Ping
  ```

## Parsing pitfalls

### ANSI codes not stripped

If you forget to strip ANSI, `re.search('BackingFile:')` will fail to match
because the line might be:

```
  \x1b[37mBackingFile:\x1b[0m          /tmp/img
```

Always strip ANSI before pattern matching.

### Whitespace in empty property values

```
  BackingFile:
  BackingFile:          (has trailing spaces/tabs)
```

Both mean empty. Always `.strip()` the captured value and treat empty string as
the empty-value signal.

### Device name false matches

A naive `device_name in line` check can match:
- `loop0` inside `loop10`
- `sda` inside `sda1`

Always extract the device name from the canonical object path:

```python
'/block_devices/' + name  # exact match within object path
```

### Job property interleaving

Job properties (`Operation`, `Objects`, `Bytes`, etc.) are printed as a block
but the order is **not guaranteed**. Wait for both `Operation` and `Objects`
before emitting an event. Do not assume `Operation` comes before `Objects`.

## Edge cases

### Daemon restart while monitoring

If the UDisks2 daemon restarts:

```
12:03:29.940: The udisks-daemon is running (name-owner :1.72).
...events...
...daemon restart...
12:05:11.123: The udisks-daemon is running (name-owner :1.89).
```

- The monitor auto-reconnects and prints a new name-owner line.
- All previous state (device tracking, job context) must be reset.
- Job numbers restart from a low value.

### Device disappears during monitoring

If a device is physically removed while being monitored:
- Block properties zero out.
- `Removed interface` events fire.
- The object eventually stops emitting events.
- There is **no** "Removed object" event.

### Loop device number recycling

The kernel recycles loop device numbers. If `/dev/loop3` is detached and a new
image is set up, it may reuse loop3. Always check `BackingFile` against the
expected path, not just whether it became empty.

### Rapid mount/unmount cycles

Desktop auto-mounters can remount within milliseconds. The `unmount-image`
detach thread handles this with a retry loop, but a general monitor-based
script should be prepared for fast toggles:

```
MountPoints:          /run/media/user/IMG
MountPoints:
MountPoints:          /run/media/user/IMG
```

Within a second, the same device can mount, unmount, and mount again.

## Debugging tips

### Capture raw monitor output

```bash
udisksctl monitor 2>/tmp/monitor.err > /tmp/monitor.out
```

In another terminal, trigger operations and then examine the files.

### Check what UDisks2 sees

```bash
udisksctl dump              # all objects
udisksctl status            # high-level summary
udisksctl info -b /dev/loop3  # specific device
```

### Verify loop device state

```bash
cat /sys/block/loop3/loop/backing_file   # empty if detached
losetup -l /dev/loop3                    # shows backing file (detached if no output)
```

### Check for interfering processes

```bash
fuser -v /dev/loop3        # what processes have the device open?
lsof /dev/loop3             # detailed open-file list
```

Auto-mounters and file managers can hold references that prevent detach.

## FAQ

**Q: Can I run multiple monitors?**
A: Yes. Each is an independent D-Bus signal subscription.

**Q: Does monitor require root?**
A: No. Reading signals does not require elevated privileges.

**Q: Can I use `udisksctl monitor` inside a container?**
A: Yes, if the container has access to the host's D-Bus system bus
   (`-v /run/dbus/system_bus_socket:/run/dbus/system_bus_socket`).

**Q: Does the monitor show historical events?**
A: No. It only shows events that occur after the monitor starts.

**Q: Why does my parser miss events?**
A: Check that you're reading lines promptly. If your processing loop blocks,
   the pipe buffer may fill and the monitor subprocess may stall.
