"""TSPLPrinter command layer, driven through a fake connection (no USB).

We assert on the TSPL byte stream the printer *would* send. Real printing is the
only thing not covered here — that lives in the manual ``testbench`` CLI.
"""

import pytest
from PIL import Image

from labeljetty.printer.tspl import TSPLPrinter
from tests.conftest import FakeConnection


def make_printer(status_byte: int = 0) -> tuple[TSPLPrinter, FakeConnection]:
    con = FakeConnection(status_byte=status_byte)
    printer = TSPLPrinter(
        connection=con, label_width_mm=57, label_height_mm=32, dpi=203
    )
    return printer, con


def _joined(con: FakeConnection) -> str:
    """All sent commands as one text blob (bytes decoded latin-1)."""
    parts = []
    for c in con.sent:
        parts.append(c if isinstance(c, str) else c.decode("latin-1"))
    return "".join(parts)


# --------------------------------------------------------------------------- #
#  Basic commands
# --------------------------------------------------------------------------- #
def test_basic_commands():
    printer, con = make_printer()
    printer.cls()
    printer.formfeed()
    printer.print_label(copies=3)
    assert "CLS\n" in con.sent
    assert "FORMFEED\n" in con.sent
    assert "PRINT 3\n" in con.sent


def test_set_size_uses_mm():
    printer, con = make_printer()
    printer._set_size()
    assert "SIZE 57 mm,32 mm\n" in con.sent


# --------------------------------------------------------------------------- #
#  Image pipeline emits SIZE → CLS → BITMAP → PRINT
# --------------------------------------------------------------------------- #
def test_text_print_emits_full_job():
    printer, con = make_printer()
    printer.print_text("Hi", copies=2)
    blob = _joined(con)
    assert "SIZE 57 mm,32 mm" in blob
    assert "CLS" in blob
    assert "BITMAP " in blob
    assert "PRINT 2" in blob


def test_qrcode_print_uses_bitmap_pipeline():
    printer, con = make_printer()
    printer.print_qrcode("https://example.com")
    assert "BITMAP " in _joined(con)


def test_barcode_uses_native_barcode_command():
    printer, con = make_printer()
    printer.print_barcode("12345678", barcode_type="128")
    blob = _joined(con)
    assert 'BARCODE ' in blob
    assert '"128"' in blob
    assert '"12345678"' in blob


def test_barcode_with_text_emits_text_and_barcode():
    printer, con = make_printer()
    printer.print_barcode_with_text("999", text="LABEL")
    blob = _joined(con)
    assert "TEXT " in blob
    assert "BARCODE " in blob


# --------------------------------------------------------------------------- #
#  Status handling
# --------------------------------------------------------------------------- #
def test_get_status_parses_connection_byte():
    printer, _ = make_printer(status_byte=0x04)  # paper empty
    status = printer.get_status()
    assert status.paper_empty
    assert status.error


def test_dry_run_status_is_ready():
    printer = TSPLPrinter(connection=None, dry_run_mode=True)
    assert printer.get_status().ready
    assert printer.is_ready()


def test_is_ready_true_when_status_unavailable(monkeypatch):
    printer, _ = make_printer()
    # A write-only clone never answers → get_status None → assume ready.
    monkeypatch.setattr(printer, "get_status", lambda: None)
    assert printer.is_ready() is True


def test_get_error_message():
    printer, _ = make_printer(status_byte=0x01)  # head open
    assert "head" in printer.get_error_message().lower()
    ready, _ = make_printer(status_byte=0x00)
    assert ready.get_error_message() is None


def test_wait_until_ready_returns_true_when_ready():
    printer, _ = make_printer(status_byte=0x00)
    assert printer.wait_until_ready(timeout=1) is True


# --------------------------------------------------------------------------- #
#  1-bit preparation / bitmap encoding
# --------------------------------------------------------------------------- #
def test_prepare_1bit_pads_width_to_multiple_of_8():
    printer, _ = make_printer()
    img = Image.new("L", (455, 100), 255)
    out = printer._prepare_1bit(img)
    assert out.mode == "1"
    assert out.width % 8 == 0
    assert out.width == 456


def test_bitmap_requires_1bit():
    printer, _ = make_printer()
    with pytest.raises(ValueError):
        printer._bitmap_tspl(Image.new("L", (8, 8), 255))


def test_build_methods_return_label_sized_images():
    printer, _ = make_printer()
    for img in (
        printer.build_text_image("hi"),
        printer.build_qrcode_image("x"),
        printer.build_barcode_image("123"),
    ):
        assert img.size == (printer.width_px, printer.height_px)
