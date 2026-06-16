# 02 — Output Structure

Every line emitted by `udisksctl monitor` is **one line of text** (LF
terminated).  The output is line-buffered: each line is written as soon as it
is produced.

## Line anatomy

```
[timestamp] [colour] body content...
```

### Timestamp prefix

```
12:03:36.774:
```

- Format: `HH:MM:SS.mmm:`
- Local time, millisecond precision.
- Followed by a space.
- May be surrounded by ANSI colour escapes.

### ANSI colour codes

The output uses ANSI SGR (Select Graphic Rendition) sequences for readability:

| Code | Meaning | Used for |
|------|---------|----------|
| `\x1b[1m` | Bold | Interface names |
| `\x1b[31m` | Red | "Removed" prefix |
| `\x1b[32m` | Green | "Added" prefix |
| `\x1b[33m` | Yellow | Timestamps, "Properties Changed" |
| `\x1b[34m` | Blue | Object paths |
| `\x1b[35m` | Magenta | Interface names |
| `\x1b[37m` | White/grey | Property names, "Job::Completed" |
| `\x1b[0m` | Reset | End of coloured span |

ANSI sequences appear inline and must be stripped before parsing property
values. The pattern `\x1b\[[0-9;]*m` matches all SGR codes.

Example raw line (ANSI visible):

```
\x1b[1m\x1b[33m12:03:36.774:\x1b[0m \x1b[1m\x1b[34m/org/.../loop3:\x1b[0m ...
```

After stripping ANSI:

```
12:03:36.774: /org/freedesktop/UDisks2/block_devices/loop3: ...
```

### Indentation

- **0 indent** — top-level lines (object path header, job added/removed,
  job completed, daemon status).
- **2 spaces** — property lines belonging to the preceding header.
- **4 spaces** — sub-properties inside a job block.

Indentation is semantic: property lines are associated with the most recently
printed object path header.

### Warnings on stderr

The monitor sometimes prints warnings to stderr (not stdout). These do not
follow the structured format:

```
** (udisksctl monitor:2540566): WARNING **: 12:03:37.002: (udisksctl.c:2811):
monitor_on_interface_proxy_properties_changed: runtime check failed:
(g_strv_length ((gchar **) invalidated_properties) == 0)
```

This is a known benign warning (see [10-troubleshooting.md](10-troubleshooting.md)).

## Line types

Every line falls into one of these categories (see [03-event-types.md](03-event-types.md) for details):

1. **Preamble** — "Monitoring the udisks daemon…", name-owner status.
2. **Job added** — `Added /org/freedesktop/UDisks2/jobs/N`
3. **Job removed** — `Removed /org/freedesktop/UDisks2/jobs/N`
4. **Job completed** — `…/jobs/N: …Job::Completed (true, '')`
5. **Properties changed** — `…/block_devices/X: …Interface: Properties Changed`
6. **Interface added** — `…/block_devices/X: Added interface org.freedesktop.UDisks2.Filesystem`
7. **Interface removed** — `…/block_devices/X: Removed interface org.freedesktop.UDisks2.Filesystem`
8. **Property line** — `  PropertyName:  value` (indented, belongs to preceding header)

## Object paths

Object paths follow the D-Bus specification:

```
/org/freedesktop/UDisks2/<category>/<name>
```

Categories:

| Category | Path prefix | Example |
|----------|-------------|---------|
| Block devices | `/org/.../block_devices/` | `loop0`, `sda1`, `nvme0n1p2` |
| Drives | `/org/.../drives/` | `ST1000DM010-2EP102_XXXX` |
| Jobs | `/org/.../jobs/` | `10842` (monotonic integer) |

Block device names are the kernel device name (e.g. `loop3`, `sda`, `sda1`).
