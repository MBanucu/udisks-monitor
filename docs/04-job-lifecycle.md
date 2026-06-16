# 04 — Job Lifecycle

Jobs are the primary mechanism UDisks2 uses to perform **long-running
operations** on block devices. Every mount, unmount, filesystem check, loop
setup, and loop delete is a job.

## Lifecycle stages

```
                   +-----------+
  request arrives  |  Created  |  Added /org/.../jobs/N
                   +-----+-----+
                         |
                         v
                   +-----------+   Operation:   filesystem-mount
                   |  Running  |   Objects:     /org/.../block_devices/loop3
                   +-----+-----+
                         |
              +----------+----------+
              |                     |
              v                     v
        +-----------+        +-----------+
        | Completed |        |  Failed   |
        +-----+-----+        +-----+-----+
              |                     |
              v                     v
        Job::Completed         Job::Completed
        (true, '')             (false, 'msg')
              |                     |
              +----------+----------+
                         |
                         v
                   +-----------+
                   |  Removed  |  Removed /org/.../jobs/N
                   +-----------+
```

### 1. Added

```
Added /org/freedesktop/UDisks2/jobs/10842
```

A new job enters the UDisks2 job queue. The job number is a monotonic counter
local to the daemon session (resets on daemon restart).

### 2. Property block

Immediately after the Added line, the job's initial properties are printed:

```
  org.freedesktop.UDisks2.Job:
    Bytes:              0
    Cancelable:         true
    ExpectedEndTime:    0
    Objects:            /org/freedesktop/UDisks2/block_devices/loop3
    Operation:          filesystem-mount
    Progress:           0.0
    ProgressValid:      false
    Rate:               0
    StartTime:          1781604216975953
    StartedByUID:       0
```

### 3. Progress updates (optional)

Some jobs emit `Properties Changed` events with progress updates:

```
/org/.../jobs/10842: org.freedesktop.UDisks2.Job: Properties Changed
  Progress:           0.5
  ProgressValid:      true
```

Most short-lived jobs complete without any progress events.

### 4. Completed

```
/org/.../jobs/10842: org.freedesktop.UDisks2.Job::Completed (true, '')
```

- `true` — operation succeeded.
- `false` — operation failed; the second element contains the error message.

### 5. Removed

```
Removed /org/freedesktop/UDisks2/jobs/10842
```

The job object is torn down. Always follows `::Completed` (or immediately if
the job is cancelled).

## Job operations

The `Operation` property identifies what the job does:

| Operation | Triggered by | Description |
|-----------|-------------|-------------|
| `filesystem-mount` | `udisksctl mount` | Mount a filesystem |
| `filesystem-unmount` | `udisksctl unmount` | Unmount a filesystem |
| `filesystem-check` | `udisksctl info` / auto | Check filesystem integrity |
| `loop-setup` | `udisksctl loop-setup` | Set up a loop device |
| `loop-delete` | `udisksctl loop-delete` | Delete a loop device |
| `cleanup` | Internal / auto | Housekeeping after device removal |
| `power-off` | `udisksctl power-off` | Safely power off a drive |
| `ata-smart-selftest` | SMART self-test | Run SMART self-test |
| `ata-smart-simulate` | `udisksctl smart-simulate` | Simulate SMART data |
| `luks-close` | `udisksctl lock` | Close LUKS device |
| `luks-open` | `udisksctl unlock` | Open LUKS device |

## Special behaviour

### Cleanup jobs

`cleanup` jobs appear frequently during device teardown. They are internal
housekeeping and have no `Objects`. Multiple `cleanup` jobs may fire in quick
succession during a single device detach.

### Completed before Added

In some race conditions (e.g. when the monitor starts mid-operation), a
`::Completed` and `Removed` may appear for a job whose `Added` was missed.
This is rare and happens because UDisks2 signals are delivered to the monitor
only from the time it connects.

### Concurrency

Multiple jobs can run concurrently for different devices. Job numbers are
independent — there is no parent/child relationship between jobs.

## Example: full mount cycle

```
12:03:36.774: /org/.../block_devices/loop3: ...Block: Properties Changed
  IdUUID:               F758-CF8B
  IdType:               vfat
...
12:03:36.787: /org/.../block_devices/loop3: Added interface ...Filesystem
  MountPoints:
  Size:                 0
12:03:37.002: Added /org/freedesktop/UDisks2/jobs/10842
  ...
    Operation:          filesystem-mount
    Objects:            /org/.../block_devices/loop3
12:03:37.002: /org/.../jobs/10842: ...Job::Completed (true, '')
12:03:37.002: Removed /org/.../jobs/10842
12:03:37.002: /org/.../block_devices/loop3: ...Filesystem: Properties Changed
  MountPoints:          /run/media/user/F758-CF8B
```

Key observation: `Properties Changed` for `MountPoints` fires **after** the
job completes, not before.
