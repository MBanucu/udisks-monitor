# 05 — Property Changes

`Properties Changed` events are emitted when one or more properties on a D-Bus
interface change value. Only changed properties are listed — never the full set.

## Event format

```
12:03:36.774: /org/freedesktop/UDisks2/block_devices/loop3: org.freedesktop.UDisks2.Block: Properties Changed
  IdUUID:               F758-CF8B
  IdType:               vfat
  Size:                  1048576
```

Header: `<object_path>: <interface_dotted>: Properties Changed`
Body: indented `  PropertyName:  value` pairs.

## Interfaces and their properties

### org.freedesktop.UDisks2.Block

Properties on block device objects.

| Property | Type | Description |
|----------|------|-------------|
| `IdUUID` | string | Filesystem UUID |
| `IdVersion` | string | Filesystem version string |
| `IdType` | string | Filesystem type (e.g. `vfat`, `ext4`) |
| `IdUsage` | string | Usage (`filesystem`, `raid`, `crypto`, `other`, ``, etc.) |
| `Size` | uint64 | Device size in bytes |
| `Symlinks` | string[] | Symlinks in `/dev/disk/by-*` |
| `UserspaceMountOptions` | string | Options passed to mount (e.g. `uhelper=udisks2`) |
| `Device` | byte array | Device number (`/dev` major:minor) |
| `PreferredDevice` | byte array | Preferred device node |
| `ReadOnly` | bool | True if device is read-only |
| `Drive` | object path | Parent drive object |
| `CryptoBackingDevice` | object path | Underlying encrypted device |
| `HintAuto` | bool | Should be auto-mounted |
| `HintSystem` | bool | Is a system device |
| `HintPartitionable` | bool | Is partitionable |
| `HintIgnore` | bool | Should be ignored by UI |
| `HintIconName` | string | Icon name hint |
| `HintName` | string | Human-readable name hint |
| `HintSymbolicIconName` | string | Symbolic icon name hint |
| `Configuration` | dict | Persistent configuration |

### org.freedesktop.UDisks2.Filesystem

Present on block devices that contain a mountable filesystem.

| Property | Type | Description |
|----------|------|-------------|
| `MountPoints` | string[] | List of mount points (empty if not mounted) |
| `Size` | uint64 | Filesystem size (0 before mount) |

`MountPoints` is the most important property for monitoring — it tells you
if and where a device is mounted.

### org.freedesktop.UDisks2.Loop

Present on loop devices.

| Property | Type | Description |
|----------|------|-------------|
| `BackingFile` | string | Path to backing file, empty when detached |
| `SetupByUID` | uint32 | UID that set up the loop device |
| `Autoclear` | bool | Whether the loop is auto-cleared on close |

`BackingFile` is critical for loop device lifecycle tracking: when it becomes
empty string `""`, the loop device has been detached.

### org.freedesktop.UDisks2.Partition

Present on partition block devices.

| Property | Type | Description |
|----------|------|-------------|
| `Number` | uint32 | Partition number |
| `Type` | string | Partition type GUID/scheme |
| `Offset` | uint64 | Byte offset |
| `Size` | uint64 | Partition size |
| `Table` | object path | Parent partition table |
| `Flags` | uint64 | Partition flags |
| `Name` | string | Partition name/label |
| `IsContained` | bool | Whether it's a "contained" partition |

### org.freedesktop.UDisks2.Drive

Properties on drive objects.

| Property | Type | Description |
|----------|------|-------------|
| `Vendor` | string | Manufacturer |
| `Model` | string | Model string |
| `Serial` | string | Serial number |
| `Size` | uint64 | Drive size |
| `ConnectionBus` | string | `usb`, `sata`, etc. |
| `Ejectable` | bool | Can be ejected |
| `Removable` | bool | Can be removed |
| `MediaAvailable` | bool | Media present |
| `MediaRemovable` | bool | Media is removable |
| `Optical` | bool | Is an optical drive |
| `Seat` | string | Login seat |

### org.freedesktop.UDisks2.Job

Properties on job objects (see [04-job-lifecycle.md](04-job-lifecycle.md)).

## Multi-line properties

Some properties span multiple lines when the value is a list. Example:

```
  Symlinks:             /dev/disk/by-diskseq/7504
                        /dev/disk/by-loop-inode/259:14-10548605
                        /dev/disk/by-uuid/F758-CF8B
```

Continuation lines are indented to align with the value, making them
categorically different from a new property line (which would have
`  PropertyName:  ` at the start).

## Empty-value properties

A property that becomes empty is printed with trailing whitespace or nothing
after the colon:

```
  BackingFile:
```

This is semantically a change to the **empty string**. Parsers must treat
whitespace-only or missing values as empty, not as absent.

## Ordering

Properties are printed in the order UDisks2's GDBus code emits them. There is
no guaranteed sort order. Multiple `Properties Changed` events for the same
interface can fire in quick succession — each only contains the deltas.
