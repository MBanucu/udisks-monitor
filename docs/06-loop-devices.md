# 06 — Loop Devices

Loop devices are virtual block devices that map a regular file to a block
device node (`/dev/loopN`). UDisks2 monitors them just like physical devices.

## Loop device lifecycle

### 1. Loop setup (`udisksctl loop-setup -f disk.img`)

```
12:03:36.774: /org/.../block_devices/loop3: org.freedesktop.UDisks2.Block: Properties Changed
  IdUUID:               F758-CF8B
  IdType:               vfat
  IdUsage:              filesystem
  Size:                  1048576
  Symlinks:             /dev/disk/by-diskseq/7504
                        /dev/disk/by-uuid/F758-CF8B

12:03:36.787: /org/.../block_devices/loop3: Added interface org.freedesktop.UDisks2.Filesystem
  MountPoints:
  Size:                 0

12:03:36.794: /org/.../block_devices/loop3: org.freedesktop.UDisks2.Loop: Properties Changed
  SetupByUID:           1000
  BackingFile:          /tmp/test.img
  Autoclear:            true
```

1. **Block properties appear first** (UUID, type, size).
2. **Filesystem interface is added**, with empty `MountPoints`.
3. **Loop interface properties appear** — crucially `BackingFile` is set to
   the image path.

### 2. Mount

See [04-job-lifecycle.md](04-job-lifecycle.md) for the mount job sequence.

After mount:

```
12:03:37.002: /org/.../block_devices/loop3: org.freedesktop.UDisks2.Filesystem: Properties Changed
  MountPoints:          /run/media/user/F758-CF8B
```

### 3. Unmount (`udisksctl unmount -b /dev/loop3`)

```
12:03:42.506: Added /org/.../jobs/10843
    Operation:          filesystem-unmount
    Objects:            /org/.../block_devices/loop3
12:03:42.537: /org/.../jobs/10843: ...Job::Completed (true, '')
12:03:42.537: /org/.../block_devices/loop3: ...Filesystem: Properties Changed
  MountPoints:
12:03:42.537: Removed /org/.../jobs/10843
```

`MountPoints` becomes empty after unmount. The Filesystem interface **remains**
— it is not removed until the device is detached.

### 4. Loop delete (`udisksctl loop-delete -b /dev/loop3`)

Before detach:

```
BackingFile:  /tmp/test.img
```

After detach:

```
12:03:42.548: /org/.../block_devices/loop3: org.freedesktop.UDisks2.Loop: Properties Changed
  SetupByUID:           0
  Autoclear:            false
  BackingFile:
```

Three key changes:
- `BackingFile` becomes **empty** — this is the definitive signal that the
  loop device is detached.
- `SetupByUID` resets to `0`.
- `Autoclear` becomes `false`.

Then block identity is cleared:

```
12:03:42.641: /org/.../block_devices/loop3: org.freedesktop.UDisks2.Block: Properties Changed
  IdUUID:
  IdVersion:
  IdType:
  IdUsage:
  Size:                 0
  Symlinks:             /dev/disk/by-diskseq/7508

12:03:42.641: /org/.../block_devices/loop3: Removed interface org.freedesktop.UDisks2.Filesystem
```

## The BackingFile property

`BackingFile` is the single most important property for confirming loop device
detachment.

| State | Value | Meaning |
|-------|-------|---------|
| Pre-setup | (no loop object) | Device does not exist |
| Setup | `/path/to/file.img` | Loop is mapped to a backing file |
| Detached | `""` (empty) | Loop is free; backing file released |

### Detecting detachment

When a loop device's `BackingFile` transitions from a non-empty path to the
empty string, the loop device has been successfully detached. This is the
signal `unmount-image`'s `_UdisksMonitor` uses to set
`backing_cleared`.

### Important caveats

1. **The empty string is a valid value** — it means "no backing file". Do not
   confuse it with the property being absent.
2. **After detach, the loop device node may linger** — `BackingFile` clears
   before the kernel recycles the `/dev/loopN` node. The device may still
   appear in `/dev/` momentarily.
3. **Autoclear loops** — if `udisksctl loop-setup` was called with
   `--no-user-interaction`, the `Autoclear` property is set to `true`. When the
   last user of the loop closes it, the kernel automatically tears it down.
   UDisks2 may then set `BackingFile` to empty even without an explicit
   `loop-delete`.
4. **Re-setup race** — if the kernel recycles a loop device number quickly, a
   new `loop-setup` can set `BackingFile` back to a path on the same loop
   number. Always compare `BackingFile` with `current_device` to ensure you
   are watching the right device.

## Auto-mounter re-mount race

A desktop auto-mounter (gvfs, udisks2 itself with `HintAuto`) may re-mount a
filesystem after a manual unmount. On UDisks2, this triggers new
`filesystem-mount` jobs. `unmount-image` detects this via
`mount_detected` and re-enters the unmount→delete loop.
