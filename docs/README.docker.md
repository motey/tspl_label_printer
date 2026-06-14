# 🏷️ LabelJetty

**Turn a cheap, USB-only TSPL thermal label printer into a smart, network-accessible label
printer** - drive it from your phone, desktop, or another machine over your LAN. It talks to the
printer **directly over USB** (no CUPS, no vendor driver) and gives you a mobile-first web UI, a
REST API, and a Python library for printing PNGs, PDFs, text, markdown, barcodes and QR codes.
Optional, self-contained [Homebox](https://github.com/sysadminsmedia/homebox) integration is
built in.

<a href="https://github.com/motey/LabelJetty"><img src="https://raw.githubusercontent.com/motey/LabelJetty/main/docs/labejetti_screenshot.png" alt="LabelJetty web UI" width="250"></a>

## Quick start (Docker Compose)

Compose is the recommended way to deploy:

```yaml
services:
  labeljetty:
    image: motey/labeljetty:latest
    restart: unless-stopped
    ports:
      - "8888:8888"
    devices:
      - /dev/bus/usb:/dev/bus/usb      # the printer's USB bus
    environment:
      PRINTER_USB: vid:2d37:pid:62de   # the only required setting; find yours with `lsusb`
    volumes:
      - ./data:/data                   # persists the job DB + stored images
```

```sh
docker compose up -d
```

Then open **http://localhost:8888/**.

- **`devices: /dev/bus/usb`** gives the container the printer's USB bus (permissions are governed
  by a host **udev rule** you set once, see [Manual Docker setup](https://github.com/motey/LabelJetty/blob/main/docs/advanced-usage.md#grant-usb-access)).
- **`PRINTER_USB`** selects which USB device is your printer. Leave it **unset** to auto-detect a
  single connected TSPL printer, or pin one with `vid:<vendor>:pid:<product>` (the robust form;
  find yours with `lsusb`).
- **`./data:/data`** persists the SQLite job DB and stored images.

Every setting is an env var (and the operational ones can also be edited at runtime from the
optional in-app settings page, `SETTINGS_UI_ENABLED=true`). The
[Setup guide](https://github.com/motey/LabelJetty/blob/main/docs/setup.md)
walks through the printer, install, and your first label end to end.

### Just testing?

A one-off `docker run` (no compose file) is fine for a quick try:

```sh
docker run --rm -p 8888:8888 \
  --device=/dev/bus/usb \
  -e PRINTER_USB=vid:2d37:pid:62de \
  -v "$(pwd)/data:/data" \
  motey/labeljetty:latest
```

## Tags

| Tag | When it's pushed |
| --- | --- |
| `latest` | Every normal release |
| `beta` | Every pre-release |
| `X.Y.Z` | The exact version |
| `dev` | Every push to `main` (amd64-only, bleeding edge) |

Multi-arch (`linux/amd64` + `linux/arm64`, so 64-bit Raspberry Pi 3/4/5 works).

## Heads-up

- **No authentication by default** - fine on a trusted home LAN, but turn on `AUTH_MODE=protected`
  before exposing it to an untrusted network.
- **Reference hardware is a Vretti 420B** (Poskey-class TSPL, ~203 dpi). It should work with any
  USB TSPL printer; feedback/PRs for other models are welcome.

## More information

Full docs, configuration reference, authentication, the REST API, and Homebox setup live on
**GitHub: https://github.com/motey/LabelJetty**
