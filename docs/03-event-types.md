# 03 — Event Types

This is a complete catalogue of every event that `udisksctl monitor` can emit.

## 1. Preamble events

### Daemon connection

```
Monitoring the udisks daemon. Press Ctrl+C to exit.
```

Emitted exactly once at startup. No ANSI.

### Name owner

```
12:03:29.940: The udisks-daemon is running (name-owner :1.72).
```

Emitted when the D-Bus name owner is resolved (once at startup, and again if
the daemon restarts).  `:1.72` is the D-Bus unique connection name.

## 2. Job events

### Job added

```
12:03:37.002: Added /org/freedesktop/UDisks2/jobs/10842
```

Colour: green (`\x1b[32m`).
A new UDisks2 job was created. The following lines (indented) are the job's
properties.

### Job property block

After a job is added, the next lines describe the job:

```
  org.freedesktop.UDisks2.Job:
    Bytes:              0
    Cancelable:         true
    ExpectedEndTime:    0
    Objects:
    Operation:          filesystem-mount
    Progress:           0.0
    ProgressValid:      false
    Rate:               0
    StartTime:          1781604216975953
    StartedByUID:       0
```

Key properties for consumers:

| Property | Type | Meaning |
|----------|------|---------|
| `Operation` | string | What the job does (see [04](04-job-lifecycle.md)) |
| `Objects` | object path(s) | Target device(s) |
| `StartedByUID` | uint32 | UID that initiated the job |
| `Progress` | double | 0.0–1.0 if `ProgressValid` is true |

### Job completed

```
12:03:37.002: /org/freedesktop/UDisks2/jobs/10842: org.freedesktop.UDisks2.Job::Completed (true, '')
```

Colour: white (`\x1b[37m`).
Format: `<path>: <interface>::Completed (<success>, '<message>')`

- `success` — `true` or `false`
- `message` — empty string on success, error description on failure

### Job removed

```
12:03:37.002: Removed /org/freedesktop/UDisks2/jobs/10842
```

Colour: red (`\x1b[31m`).
The job object is being removed from the tree.  If a job is removed without
a preceding `::Completed` line, it means it was cancelled or timed out.

## 3. Properties Changed

```
12:03:36.774: /org/freedesktop/UDisks2/block_devices/loop3: org.freedesktop.UDisks2.Block: Properties Changed
  IdUUID:               F758-CF8B
  IdType:               vfat
  Size:                  1048576
```

Header format: `<object_path>: <interface>: Properties Changed`
Colour: yellow (`\x1b[33m`) for "Properties Changed".

Following indented lines (2 spaces) list changed properties:

```
  PropertyName:    value
```

Some properties span multiple lines (e.g. `Symlinks`):

```
  Symlinks:             /dev/disk/by-diskseq/7504
                        /dev/disk/by-uuid/F758-CF8B
```

Only properties that **changed** are listed — not all properties.

See [05-property-changes.md](05-property-changes.md) for a full property catalogue.

## 4. Interface Added

```
12:03:36.787: /org/freedesktop/UDisks2/block_devices/loop3: Added interface org.freedesktop.UDisks2.Filesystem
```

Colour: green (`\x1b[32m`).
A new D-Bus interface was added to an existing object. The next lines are the
initial property values for that interface.

## 5. Interface Removed

```
12:03:36.991: /org/freedesktop/UDisks2/block_devices/loop1: Removed interface org.freedesktop.UDisks2.Filesystem
```

Colour: red (`\x1b[31m`).
An interface was removed from an object. No property lines follow.

## Event ordering guarantees

Events for the same object are serialised in order. Events for different
objects may be interleaved.  Within a job:

1. `Added /org/.../jobs/N`
2. Job property block (Operation, Objects, etc.)
3. (optional) property changes during job execution
4. `...Job::Completed (…)`
5. `Removed /org/.../jobs/N`

Steps 1–5 always appear in that order but may be interleaved with events for
other objects.

## Non-events (ignored)

- **Empty lines**: occasionally appear; carry no information.
- **Stderr warnings**: go to stderr, not stdout; see
  [10-troubleshooting.md](10-troubleshooting.md).
- **Glib assertion messages**: rare, also on stderr.
