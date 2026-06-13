"""USB connection layer — device lookup + wire encoding, all without real USB.

``usb.core.find`` is patched to return fake devices, so no hardware is touched.
"""

import types

import pytest
import usb.core
import usb.util

from labeljetty.printer.connection import TSPLPrinterConnectionUSB as Conn


class FakeDev:
    def __init__(self, bus=1, address=4, port_numbers=(3, 1, 2),
                 idVendor=0x2d37, idProduct=0x62de, serial="ABC123"):
        self.bus = bus
        self.address = address
        self.port_numbers = list(port_numbers)
        self.idVendor = idVendor
        self.idProduct = idProduct
        self.iSerialNumber = 3
        self._serial = serial


@pytest.fixture
def fake_usb(monkeypatch):
    """Patch usb.core.find + usb.util.get_string with a single fake device."""
    dev = FakeDev()

    def fake_find(find_all=False, idVendor=None, idProduct=None):
        matches = [dev]
        if idVendor is not None:
            matches = [d for d in matches if d.idVendor == idVendor]
        if idProduct is not None:
            matches = [d for d in matches if d.idProduct == idProduct]
        return iter(matches) if find_all else (matches[0] if matches else None)

    monkeypatch.setattr(usb.core, "find", fake_find)
    monkeypatch.setattr(usb.util, "get_string", lambda d, idx: d._serial)
    return dev


# --------------------------------------------------------------------------- #
#  Wire encoding
# --------------------------------------------------------------------------- #
def test_to_wire_appends_newline_for_normal_commands():
    assert Conn._to_wire("SIZE 50 mm", raw=False) == b"SIZE 50 mm\n"


def test_to_wire_strips_then_terminates():
    assert Conn._to_wire("  CLS\n", raw=False) == b"CLS\n"


def test_to_wire_raw_passes_bytes_untouched():
    # Real-time commands like <ESC>!? must NOT get a trailing newline.
    assert Conn._to_wire(b"\x1b!?", raw=True) == b"\x1b!?"


def test_to_wire_raw_encodes_str():
    assert Conn._to_wire("AB", raw=True) == b"AB"


# --------------------------------------------------------------------------- #
#  Lookups
# --------------------------------------------------------------------------- #
def test_by_vendor_and_product_id(fake_usb):
    c = Conn.by_vendor_and_product_id("2d37", "62de")
    assert c.dev is fake_usb


def test_by_vendor_id_only(fake_usb):
    assert Conn.by_vendor_and_product_id("2d37").dev is fake_usb


def test_by_vendor_no_match_raises(fake_usb):
    with pytest.raises(ValueError):
        Conn.by_vendor_and_product_id("dead", "beef")


def test_by_vendor_requires_an_argument():
    with pytest.raises(ValueError):
        Conn.by_vendor_and_product_id(None, None)


def test_by_bus_and_device_id(fake_usb):
    assert Conn.by_bus_and_device_id(1, 4).dev is fake_usb


def test_by_bus_no_match_raises(fake_usb):
    with pytest.raises(ValueError):
        Conn.by_bus_and_device_id(9, 9)


def test_by_serial(fake_usb):
    assert Conn.by_serial("ABC123").dev is fake_usb


def test_by_serial_empty_raises():
    with pytest.raises(ValueError):
        Conn.by_serial("")


def test_by_port_string(fake_usb):
    assert Conn.by_port("3-1-2").dev is fake_usb


def test_by_device_path_full(fake_usb):
    assert Conn.by_device_path("/dev/bus/usb/001/004").dev is fake_usb


def test_by_device_path_short(fake_usb):
    assert Conn.by_device_path("001/004").dev is fake_usb


def test_by_device_path_bad_format():
    with pytest.raises(ValueError):
        Conn.by_device_path("not-a-path")


def test_by_device_path_non_numeric():
    with pytest.raises(ValueError):
        Conn.by_device_path("aa/bb")
