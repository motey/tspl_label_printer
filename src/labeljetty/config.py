import os
from typing import TYPE_CHECKING, List, Self
from pathlib import Path
from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings
from typing import Literal, Optional

if TYPE_CHECKING:
    from labeljetty.printer.connection import TSPLPrinterConnectionUSB

# `.env` is looked up relative to the current working directory (the repo root,
# per the README) — the override env var takes precedence. It is intentionally
# not resolved relative to this file, which now lives inside the package.
env_file_path = os.environ.get(
    "TSPL_PRINTER_WEBAPI_DOT_ENV_FILE", Path(".env")
)


class LabelProfile(BaseModel):
    """A named label stock (width × height in mm), selectable in the web UI."""

    name: str
    width_mm: int
    height_mm: int
    dpi: Optional[int] = None


class Config(BaseSettings):
    APP_NAME: str = "TSPL Printer WebAPI"
    LOG_LEVEL: Literal["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"] = Field(
        default="DEBUG"
    )
    LOG_DISABLE_COLORS: bool = False
    UVICORN_LOG_LEVEL: Optional[str] = Field(
        default=None,
        description="The log level of the uvicorn server. If not defined it will be the same as LOG_LEVEL.",
    )
    SERVER_LISTENING_PORT: int = Field(default=8888)
    SERVER_LISTENING_HOST: str = Field(
        default="localhost",
        examples=["0.0.0.0", "localhost", "127.0.0.1", "176.16.8.123"],
    )
    SQLITE_PATH: str = Field(default="./printjobs.sqlite")
    IMAGE_STORAGE_DIRECTORY: str = Field(
        default="./images", description="Storage for posted images to print"
    )
    API_ACCESS_TOKEN: Optional[str] = Field(
        default=None,
        description="""If API_ACCESS_TOKEN is not empty, any API endpoints needs a authorization header (e.g. in curl `-H "Authorization: Bearer your-secret-token"`)""",
    )
    DELETE_OLD_JOBS_AFTER_DAYS: int = Field(
        default=100,
        description="Old job entries in the database will be removed with associated files.",
    )
    # Default label geometry — used when a print job does not specify its own.
    DEFAULT_LABEL_WIDTH_MM: int = Field(default=100)
    DEFAULT_LABEL_HEIGHT_MM: int = Field(default=30)
    DEFAULT_DPI: int = Field(default=203)
    # Named label profiles selectable in the web UI, as a JSON list, e.g.
    #   LABEL_PROFILES='[{"name":"Homebox","width_mm":57,"height_mm":32}]'
    # The server default geometry is always offered as a "Default" profile too.
    LABEL_PROFILES: List[LabelProfile] = Field(default_factory=list)

    # --- Homebox integration (optional module) ------------------------------ #
    # The module's UI section + endpoints appear only when HOMEBOX_URL and
    # HOMEBOX_API_KEY are both set (and HOMEBOX_ENABLED is true).
    HOMEBOX_ENABLED: bool = Field(default=True)
    HOMEBOX_URL: Optional[str] = Field(
        default=None, description="Base URL of the Homebox server, e.g. https://box.example.com"
    )
    HOMEBOX_API_KEY: Optional[str] = Field(
        default=None, description="Homebox API key (prefixed 'hb_…')."
    )
    HOMEBOX_API_PREFIX: str = Field(
        default="/api/v1",
        description="API path prefix on the Homebox server (entities live at <prefix>/entities).",
    )
    HOMEBOX_ENTITY_URL_TEMPLATE: str = Field(
        default="/item/{id}",
        description="Web path (appended to HOMEBOX_URL) an entity opens at; '{id}' is substituted. Used for the QR link.",
    )
    HOMEBOX_LABEL_SERVICE_AUTOPRINT: bool = Field(
        default=True,
        description=(
            "For the push 'external label service' endpoint: also enqueue the print "
            "as a side effect of Homebox requesting the label image. Disable if your "
            "Homebox build calls the label-service URL for previews too (would cause "
            "spurious prints) — then use the print-command script (path C) instead."
        ),
    )

    def homebox_configured(self) -> bool:
        """True when the Homebox module should be active."""
        return bool(self.HOMEBOX_ENABLED and self.HOMEBOX_URL and self.HOMEBOX_API_KEY)

    def get_label_profiles(self) -> List[LabelProfile]:
        """Configured profiles, preceded by the server-default geometry."""
        default = LabelProfile(
            name="Default",
            width_mm=self.DEFAULT_LABEL_WIDTH_MM,
            height_mm=self.DEFAULT_LABEL_HEIGHT_MM,
            dpi=self.DEFAULT_DPI,
        )
        return [default, *self.LABEL_PROFILES]
    # USB Printer - Choose ONE of these methods:
    PRINTER_USB: str = Field(
        description=(
            "USB printer identifier. Can be:\n"
            "  - Serial number:     'serial:ABC123456'\n"
            "  - Device path:       'path:/dev/bus/usb/001/004' or 'path:001/004'\n"
            "  - USB port:          'port:3-1-2'\n"
            "  - Vendor+Product ID: 'vid:1234:pid:5678' or 'vid:1234' (first match)\n"
            "  - Bus+Address:       'bus:1:addr:4'"
        ),
        examples=[
            "serial:ABC123456",
            "path:/dev/bus/usb/001/004",
            "port:3-1-2",
            "vid:1234:pid:5678",
            "bus:1:addr:4",
        ],
    )

    @model_validator(mode="after")
    def validate_printer_config(self) -> Self:
        """Ensure printer USB identifier is provided"""
        if not self.PRINTER_USB:
            raise ValueError(
                "PRINTER_USB must be set. Examples:\n"
                "  PRINTER_USB=serial:ABC123456\n"
                "  PRINTER_USB=port:3-1-2\n"
                "  PRINTER_USB=vid:1234:pid:5678"
            )
        return self

    def get_printer_connection(self) -> "TSPLPrinterConnectionUSB":
        """Returns a printer connection using the configured identifier"""
        from labeljetty.printer.connection import TSPLPrinterConnectionUSB

        usb_id = self.PRINTER_USB

        if usb_id.startswith("serial:"):
            serial = usb_id.split(":", 1)[1]
            return TSPLPrinterConnectionUSB.by_serial(serial)

        elif usb_id.startswith("path:"):
            path = usb_id.split(":", 1)[1]
            return TSPLPrinterConnectionUSB.by_device_path(path)

        elif usb_id.startswith("port:"):
            port = usb_id.split(":", 1)[1]
            return TSPLPrinterConnectionUSB.by_port(port)

        elif usb_id.startswith("bus:"):
            # Format: bus:1:addr:4
            parts = usb_id.split(":")
            if len(parts) != 4 or parts[2] != "addr":
                raise ValueError(
                    f"Invalid bus format: {usb_id}. Expected 'bus:1:addr:4'"
                )
            bus = int(parts[1])
            addr = int(parts[3])
            return TSPLPrinterConnectionUSB.by_bus_and_device_id(bus, addr)

        elif usb_id.startswith("vid:"):
            # Format: vid:1234:pid:5678 or vid:1234
            parts = usb_id.split(":")
            vendor = parts[1]
            product = parts[3] if len(parts) >= 4 and parts[2] == "pid" else None
            return TSPLPrinterConnectionUSB.by_vendor_and_product_id(vendor, product)

        else:
            raise ValueError(
                f"Invalid PRINTER_USB format: {usb_id}\n"
                "Must start with: serial:, path:, port:, bus:, or vid:"
            )

    ###### CONFIG END ######
    # "class Config:" is a pydantic-settings pre-defined config class to control the behaviour of our settings model
    # you could call it a "meta config" class
    # if you dont know what this is you can ignore it.
    # https://docs.pydantic.dev/latest/api/base_model/#pydantic.main.BaseModel.model_config

    class Config:
        env_nested_delimiter = "__"
        env_file = env_file_path
        env_file_encoding = "utf-8"
        extra = "ignore"
