# 01 — Command Overview

`udisksctl monitor` connects to the UDisks2 D-Bus service and prints
human-readable notifications for every state change in the daemon's object
tree.

## Invocation

```bash
udisksctl monitor
```

- **No arguments, no flags.**
- Prints to **stdout**.
- Warnings go to **stderr**.
- Runs **indefinitely** until interrupted (Ctrl+C / SIGTERM).
- Output is **line-buffered** — each line is flushed immediately.

## What it monitors

The UDisks2 daemon exposes an object tree rooted at
`/org/freedesktop/UDisks2`. Objects represent:

- **Block devices** (`/org/freedesktop/UDisks2/block_devices/<name>`)
- **Drives** (`/org/freedesktop/UDisks2/drives/<name>`)
- **Jobs** (`/org/freedesktop/UDisks2/jobs/<n>`)

Each object can carry multiple D-Bus interfaces, e.g.:

- `org.freedesktop.UDisks2.Block`
- `org.freedesktop.UDisks2.Filesystem`
- `org.freedesktop.UDisks2.Loop`
- `org.freedesktop.UDisks2.Job`

`udisksctl monitor` reports the following categories of change:

1. **Jobs added / removed** — an operation started or finished (mount, unmount,
   check, loop-setup, loop-delete, power-off, cleanup).
2. **Job completed** — a job finished with a success/failure result.
3. **Interface added / removed** — e.g. `Filesystem` interface appears when a
   device gains a filesystem.
4. **Properties changed** — any property on any interface changed its value.

## D-Bus connection lifecycle

On startup, the monitor prints:

```
Monitoring the udisks daemon. Press Ctrl+C to exit.
```

Once the D-Bus name owner is resolved:

```
12:03:29.940: The udisks-daemon is running (name-owner :1.72).
```

If the daemon restarts, a new name-owner message appears.

## Permissions

`udisksctl monitor` only subscribes to D-Bus signals — it performs **no
modifications**.  On most desktop distributions, polkit grants this to any
active local session without a password prompt.

On headless or SSH sessions without a polkit agent, the monitor still works
because it only receives signals.

## Use cases

- **Debugging**: observe what UDisks2 does when you plug/unplug a USB drive.
- **Scripting**: watch for device appearance/disappearance.
- **Automation**: detect when a filesystem is mounted so you can act on it.
- **Detach confirmation**: confirm that a loop device's backing file has been
  cleared (used by `unmount-image`).

## Example session

```bash
$ udisksctl monitor
Monitoring the udisks daemon. Press Ctrl+C to exit.
12:03:29.940: The udisks-daemon is running (name-owner :1.72).
12:03:36.774: /org/freedesktop/UDisks2/block_devices/loop3: org.freedesktop.UDisks2.Block: Properties Changed
  IdUUID:               F758-CF8B
  IdType:               vfat
  Size:                  1048576
...
12:03:37.002: Added /org/freedesktop/UDisks2/jobs/10842
  org.freedesktop.UDisks2.Job:
    Operation:          filesystem-mount
    Objects:            /org/freedesktop/UDisks2/block_devices/loop3
...
12:03:37.002: /org/freedesktop/UDisks2/jobs/10842: org.freedesktop.UDisks2.Job::Completed (true, '')
12:03:37.002: Removed /org/freedesktop/UDisks2/jobs/10842
```
