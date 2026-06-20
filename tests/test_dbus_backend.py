"""Unit tests for the D-Bus backend signal translation."""

import unittest

from dbus_fast.signature import Variant as _Variant

from udisks_monitor._backends._dbus import _DBusBackend, _device_from_path
from udisks_monitor._events import (
    DevicePropertyChanged,
    InterfaceAdded,
    InterfaceRemoved,
    JobAdded,
    JobCompleted,
    JobProperties,
    JobRemoved,
)


class TestDeviceFromPath(unittest.TestCase):
    def test_block_device_path(self):
        self.assertEqual(_device_from_path(
            '/org/freedesktop/UDisks2/block_devices/loop0'), 'loop0')
        self.assertEqual(_device_from_path(
            '/org/freedesktop/UDisks2/block_devices/sda1'), 'sda1')
        self.assertEqual(_device_from_path(
            '/org/freedesktop/UDisks2/block_devices/nvme0n1p2'), 'nvme0n1p2')

    def test_no_block_devices_returns_empty(self):
        self.assertEqual(_device_from_path(
            '/org/freedesktop/UDisks2/jobs/1'), '')
        self.assertEqual(_device_from_path(''), '')


class _Collector:
    def __init__(self):
        self.events = []

    def publish(self, event):
        self.events.append(event)

    def types(self):
        return [type(e) for e in self.events]

    def find(self, cls):
        return [e for e in self.events if isinstance(e, cls)]


class TestJobSignalTranslation(unittest.TestCase):
    def setUp(self):
        self.collector = _Collector()
        self.be = _DBusBackend(self.collector.publish)

    def test_job_added_and_properties_emitted_together(self):
        self.be._on_interfaces_added(
            '/org/freedesktop/UDisks2/jobs/42',
            {'org.freedesktop.UDisks2.Job': {
                'Operation': 'filesystem-mount',
                'Objects': ['/org/freedesktop/UDisks2/block_devices/loop0'],
            }})

        self.assertEqual(len(self.collector.events), 2)
        ja = self.collector.events[0]
        self.assertIsInstance(ja, JobAdded)
        self.assertEqual(ja.job_path, '/org/freedesktop/UDisks2/jobs/42')
        self.assertEqual(ja.job_id, 42)
        self.assertTrue(ja.timestamp)

        jp = self.collector.events[1]
        self.assertIsInstance(jp, JobProperties)
        self.assertEqual(jp.job_id, 42)
        self.assertEqual(jp.operation, 'filesystem-mount')
        self.assertEqual(jp.objects, '/org/freedesktop/UDisks2/block_devices/loop0')

    def test_job_completed_success(self):
        self.be._on_job_completed(
            '/org/freedesktop/UDisks2/jobs/7', True, '')

        self.assertEqual(len(self.collector.events), 1)
        jc = self.collector.events[0]
        self.assertIsInstance(jc, JobCompleted)
        self.assertEqual(jc.job_id, 7)
        self.assertTrue(jc.success)
        self.assertEqual(jc.message, '')

    def test_job_completed_failure(self):
        self.be._on_job_completed(
            '/org/freedesktop/UDisks2/jobs/7', False, 'device busy')

        jc = self.collector.events[0]
        self.assertFalse(jc.success)
        self.assertEqual(jc.message, 'device busy')

    def test_job_removed(self):
        self.be._on_interfaces_removed(
            '/org/freedesktop/UDisks2/jobs/42',
            ['org.freedesktop.UDisks2.Job'])

        jr = self.collector.events[0]
        self.assertIsInstance(jr, JobRemoved)
        self.assertEqual(jr.job_id, 42)


class TestInterfaceSignalTranslation(unittest.TestCase):
    def setUp(self):
        self.collector = _Collector()
        self.be = _DBusBackend(self.collector.publish)

    def test_interface_added(self):
        self.be._on_interfaces_added(
            '/org/freedesktop/UDisks2/block_devices/loop0',
            {'org.freedesktop.UDisks2.Filesystem': {
                'MountPoints': ['/run/media/user/VOL'],
                'Size': 0,
            }})

        self.assertEqual(len(self.collector.events), 1)
        ia = self.collector.events[0]
        self.assertIsInstance(ia, InterfaceAdded)
        self.assertEqual(ia.object_path,
                         '/org/freedesktop/UDisks2/block_devices/loop0')
        self.assertEqual(ia.device_name, 'loop0')
        self.assertEqual(ia.interface,
                         'org.freedesktop.UDisks2.Filesystem')
        self.assertEqual(ia.properties,
                         {'MountPoints': ['/run/media/user/VOL'], 'Size': 0})

    def test_interface_removed(self):
        self.be._on_interfaces_removed(
            '/org/freedesktop/UDisks2/block_devices/loop1',
            ['org.freedesktop.UDisks2.Filesystem'])

        ir = self.collector.events[0]
        self.assertIsInstance(ir, InterfaceRemoved)
        self.assertEqual(ir.device_name, 'loop1')
        self.assertEqual(ir.interface,
                         'org.freedesktop.UDisks2.Filesystem')

    def test_ignores_non_udisks_interfaces(self):
        self.be._on_interfaces_added(
            '/org/freedesktop/UDisks2/block_devices/loop0',
            {'org.freedesktop.UDisks2.Filesystem': {},
             'org.freedesktop.DBus.Properties': {}})
        self.assertEqual(len(self.collector.events), 1)

        self.be._on_interfaces_removed(
            '/org/freedesktop/UDisks2/block_devices/loop0',
            ['org.freedesktop.UDisks2.Filesystem',
             'org.freedesktop.DBus.Properties'])
        self.assertEqual(len(self.collector.events), 2)


class TestDevicePropertyChangedTranslation(unittest.TestCase):
    def setUp(self):
        self.collector = _Collector()
        self.be = _DBusBackend(self.collector.publish)

    def test_property_changed(self):
        self.be._on_properties_changed(
            '/org/freedesktop/UDisks2/block_devices/loop0',
            'org.freedesktop.UDisks2.Loop',
            {'BackingFile': '/tmp/img.img', 'Autoclear': True},
            [])

        self.assertEqual(len(self.collector.events), 2)
        dpc0 = self.collector.events[0]
        self.assertIsInstance(dpc0, DevicePropertyChanged)
        self.assertEqual(dpc0.device_name, 'loop0')
        self.assertEqual(dpc0.interface, 'org.freedesktop.UDisks2.Loop')
        self.assertEqual(dpc0.property, 'BackingFile')
        self.assertEqual(dpc0.value, '/tmp/img.img')

        dpc1 = self.collector.events[1]
        self.assertEqual(dpc1.property, 'Autoclear')
        self.assertTrue(dpc1.value)

    def test_ignores_non_block_device_paths(self):
        self.be._on_properties_changed(
            '/org/freedesktop/UDisks2/jobs/1',
            'org.freedesktop.UDisks2.Job',
            {'Progress': 0.5},
            [])
        self.assertEqual(len(self.collector.events), 0)

    def test_ignores_non_udisks_interfaces(self):
        self.be._on_properties_changed(
            '/org/freedesktop/UDisks2/block_devices/loop0',
            'org.freedesktop.DBus.Properties',
            {}, [])
        self.assertEqual(len(self.collector.events), 0)


class TestObjectsFieldVariants(unittest.TestCase):
    def setUp(self):
        self.collector = _Collector()
        self.be = _DBusBackend(self.collector.publish)

    def test_multiple_objects_joined_by_space(self):
        self.be._on_interfaces_added(
            '/org/freedesktop/UDisks2/jobs/1',
            {'org.freedesktop.UDisks2.Job': {
                'Operation': 'ata-smart-selftest',
                'Objects': [
                    '/org/freedesktop/UDisks2/block_devices/sda',
                    '/org/freedesktop/UDisks2/block_devices/sdb',
                ],
            }})
        jp = self.collector.find(JobProperties)[0]
        self.assertIn(' ', jp.objects)
        self.assertIn('sda', jp.objects)
        self.assertIn('sdb', jp.objects)

    def test_objects_not_a_list(self):
        self.be._on_interfaces_added(
            '/org/freedesktop/UDisks2/jobs/1',
            {'org.freedesktop.UDisks2.Job': {
                'Operation': 'loop-delete',
                'Objects': '/org/freedesktop/UDisks2/block_devices/loop0',
            }})
        jp = self.collector.find(JobProperties)[0]
        self.assertEqual(jp.objects,
                         '/org/freedesktop/UDisks2/block_devices/loop0')

    def test_objects_missing(self):
        self.be._on_interfaces_added(
            '/org/freedesktop/UDisks2/jobs/1',
            {'org.freedesktop.UDisks2.Job': {}})
        jp = self.collector.find(JobProperties)[0]
        self.assertEqual(jp.objects, '')

    def test_objects_is_variant_of_list(self):
        self.be._on_interfaces_added(
            '/org/freedesktop/UDisks2/jobs/1',
            {'org.freedesktop.UDisks2.Job': {
                'Operation': 'ata-smart-selftest',
                'Objects': _Variant('as', [
                    '/org/freedesktop/UDisks2/block_devices/sda',
                    '/org/freedesktop/UDisks2/block_devices/sdb',
                ]),
            }})
        jp = self.collector.find(JobProperties)[0]
        self.assertIn('sda', jp.objects)
        self.assertIn('sdb', jp.objects)

    def test_objects_is_variant_of_string(self):
        self.be._on_interfaces_added(
            '/org/freedesktop/UDisks2/jobs/1',
            {'org.freedesktop.UDisks2.Job': {
                'Operation': _Variant('s', 'loop-delete'),
                'Objects': _Variant('s',
                                    '/org/freedesktop/UDisks2/block_devices/loop0'),
            }})
        jp = self.collector.find(JobProperties)[0]
        self.assertEqual(jp.operation, 'loop-delete')
        self.assertEqual(jp.objects,
                         '/org/freedesktop/UDisks2/block_devices/loop0')


class TestVariantUnwrapping(unittest.TestCase):
    def setUp(self):
        self.collector = _Collector()
        self.be = _DBusBackend(self.collector.publish)

    def test_interface_added_properties_unwrapped(self):
        self.be._on_interfaces_added(
            '/org/freedesktop/UDisks2/block_devices/loop0',
            {'org.freedesktop.UDisks2.Filesystem': {
                'MountPoints': _Variant('as', ['/run/media/user/VOL']),
                'Size': _Variant('t', 0),
            }})
        ia = self.collector.find(InterfaceAdded)[0]
        self.assertEqual(ia.properties,
                         {'MountPoints': ['/run/media/user/VOL'], 'Size': 0})

    def test_properties_changed_values_unwrapped(self):
        self.be._on_properties_changed(
            '/org/freedesktop/UDisks2/block_devices/loop0',
            'org.freedesktop.UDisks2.Loop',
            {'BackingFile': _Variant('s', '/tmp/img.img'),
             'Autoclear': _Variant('b', True)},
            [])
        values = {e.property: e.value for e in self.collector.events}
        self.assertEqual(values['BackingFile'], '/tmp/img.img')
        self.assertTrue(values['Autoclear'] is True)
