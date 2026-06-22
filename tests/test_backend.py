"""Tests for backend selection."""

import unittest

from udisks_monitor._backends import _get_backend
from udisks_monitor._backends._base import _Backend
from udisks_monitor._backends._dbus import _DBusBackend
from udisks_monitor._backends._subprocess import _SubprocessBackend


def _null_publish(event):
    pass


class TestBackendSelection(unittest.TestCase):

    def test_subprocess_explicit(self):
        be = _get_backend('subprocess', _null_publish)
        self.assertIsInstance(be, _SubprocessBackend)

    def test_dbus_explicit(self):
        be = _get_backend('dbus', _null_publish)
        self.assertIsInstance(be, _DBusBackend)

    def test_auto_uses_dbus(self):
        be = _get_backend('auto', _null_publish)
        self.assertIsInstance(be, _DBusBackend)

    def test_invalid_backend_raises(self):
        with self.assertRaises(ValueError):
            _get_backend('bogus', _null_publish)
