# 07 — Interface Changes

UDisks2 objects can gain or lose D-Bus interfaces at runtime. `udisksctl
monitor` reports these with "Added interface" and "Removed interface" events.

## Added interface

```
12:03:36.787: /org/freedesktop/UDisks2/block_devices/loop3: Added interface org.freedesktop.UDisks2.Filesystem
  MountPoints:
  Size:                 0
```

Format: `<object_path>: Added interface <interface>`

Colour: green (`\x1b[32m`).

The indented lines after the header are the **initial property values** for
that interface. Not all properties are listed — only those with non-default
values.

## Removed interface

```
12:03:36.991: /org/freedesktop/UDisks2/block_devices/loop1: Removed interface org.freedesktop.UDisks2.Filesystem
```

Format: `<object_path>: Removed interface <interface>`

Colour: red (`\x1b[31m`).

No property lines follow — the interface is gone.

## Which interfaces are added/removed?

| Interface | Added when | Removed when |
|-----------|-----------|-------------|
| `org.freedesktop.UDisks2.Filesystem` | Device with filesystem appears | Device detached or filesystem type cleared |
| `org.freedesktop.UDisks2.Loop` | Loop device set up | Loop device deleted |
| `org.freedesktop.UDisks2.Partition` | Partition table detected | Device detached |
| `org.freedesktop.UDisks2.Swapspace` | Swap signature detected | Device reformatted or detached |
| `org.freedesktop.UDisks2.Encrypted` | LUKS header detected | Device reformatted or detached |

## Relationship to Properties Changed

`Added interface` is distinct from `Properties Changed`:

- **Added interface**: the interface **appears** on the object for the first
  time. The event includes initial property values.
- **Properties Changed**: an existing interface's properties were mutated.

A `Removed interface` followed by a new `Added interface` for the same
interface on the same object means the interface was torn down and
re-created. This can happen during certain device re-probing sequences.

## Interface removal during detach

When a loop device is fully detached, the interface removal sequence is:

```
12:03:42.641: /org/.../block_devices/loop3: org.freedesktop.UDisks2.Block: Properties Changed
  IdUUID:
  IdType:
  Size:                 0
  ...

12:03:42.641: /org/.../block_devices/loop3: Removed interface org.freedesktop.UDisks2.Filesystem
```

The `Filesystem` interface is removed **after** the block identity properties
are cleared, **before** the object itself disappears.

## Object lifetime

Objects in the UDisks2 tree are **never explicitly removed** in the monitor
output. There is no "Removed object" event. Instead, when a device is gone:

1. All added interfaces are removed.
2. Block properties are zeroed/emptied.
3. The object may be garbage-collected by UDisks2 internally.

The monitor will not print anything to indicate the object no longer exists in
the tree — it simply stops emitting events for it.

## Practical implications

To detect device disappearance in a monitor-based application:

- **Loop devices**: watch for `BackingFile` becoming empty.
- **Physical devices**: watch for `Removed interface org.freedesktop.UDisks2.Block` (rare) or `MediaAvailable` becoming false on the parent drive.
- **Filesystem lifecycle**: watch for `Removed interface org.freedesktop.UDisks2.Filesystem` plus zeroed `Size` and empty `IdType`.
