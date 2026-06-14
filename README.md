# 🏷️ LabelJetty

<a href="docs/labejetti_screenshot.png"><img src="docs/labejetti_screenshot.png" alt="LabelJetty web UI" align="right" width="250"></a>

**Turn a cheap, USB-only TSPL thermal label printer into a smart, network-accessible label
printer** - drive it from your phone, desktop, or another machine over your LAN (a Raspberry Pi
next to the printer is the classic setup).

It talks to the printer **directly over USB** (`pyusb`/libusb) - no CUPS, no vendor driver - and
gives you a mobile-first **web UI**, a **REST API**, and a Python **library** for printing PNGs,
PDFs, text, markdown, barcodes and QR codes, plus an optional, self-contained
**[Homebox](https://github.com/sysadminsmedia/homebox)** integration for inventory labels.

> **Status:** functional (library, REST API, web UI, Homebox, multi-token/user auth all work) but
> still an early **beta** - expect rough edges, and please [file bugs / feedback](../../issues).
> See the [Roadmap](docs/roadmap.md) for what's next.

## ✨ Features

- 📦 **[Homebox](docs/advanced-usage.md#homebox-integration) integration** (the headline feature) -
  search your self-hosted inventory and print labels from the UI, or wire up Homebox's own print
  button. Optional and invisible until you configure it.
- **Direct USB** to TSPL printers - minimal dependencies, no CUPS.
- Print **PNG, PDF, text, markdown, barcodes** (Code128/EAN/UPC/Code39/...) and **QR codes**, plus
  composite barcode/QR + text labels.
- **[Auto-fit rendering](docs/advanced-usage.md#text-rendering--auto-fit)** - text, markdown and QR
  scale to the label automatically; no guessing font sizes.
- Configurable **label size & DPI**, with named **[profiles](docs/configuration.md)** for your stock.
- **Mobile-first web UI** - print every type, **preview** before printing, live job/printer status.
- **REST API** (FastAPI) on a persistent SQLite **job queue** + single **worker**; live docs at
  `/docs`, `/redoc`, `/openapi.json` ([reference](docs/advanced-usage.md#the-rest-api)).
- **[Auth](docs/advanced-usage.md#authentication) when you want it** - multi-token + multi-user
  login, off by default ([OIDC planned](docs/roadmap.md#oidc--sso-authentication)).
- **Dry-run mode** + a **[CLI test bench](docs/developing.md#real-world-print-tests-with-the-testbench)**
  for hardware-free development and on-device geometry checks.

## 🚀 Run it (Docker)

Published as [`motey/labeljetty`](https://hub.docker.com/r/motey/labeljetty). For a real deployment
use **Docker Compose** - a ready-made [`docker-compose.yml`](docker-compose.yml) is in this repo:

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
      PRINTER_USB: vid:2d37:pid:62de   # only required setting; find yours with `lsusb`
    volumes:
      - ./data:/data                   # persists the job DB + stored images
```

```sh
docker compose up -d   # then open http://localhost:8888/
```

`PRINTER_USB` is the only required setting (the `vid:...:pid:...` form survives replugging). The
host still needs a **udev rule** so the container can reach the USB device - see
[Configuration → Setting up the printer](docs/configuration.md#setting-up-the-printer). The
committed compose file also has commented blocks for label geometry,
[auth](docs/advanced-usage.md#authentication), and [Homebox](docs/advanced-usage.md#homebox-integration).

<details>
<summary><b>Just testing?</b> A one-off <code>docker run</code> (no compose file)</summary>

```sh
docker run --rm -p 8888:8888 --device=/dev/bus/usb \
  -e PRINTER_USB=vid:2d37:pid:62de -v "$(pwd)/data:/data" \
  motey/labeljetty:latest
```
</details>

Image tags (`latest` / `beta` / `X.Y.Z` / `dev`) and architectures are in
[Advanced usage → Docker](docs/advanced-usage.md#docker-tags--architectures); running **without
Docker** (PyPI / source) is in [Advanced usage](docs/advanced-usage.md).

## ⚠️ Important to know

- **No authentication by default.** With `AUTH_MODE=open` (the default) every endpoint and the
  whole web UI are public - fine for a trusted home LAN, but **don't expose it to an untrusted
  network** without turning on [auth](docs/advanced-usage.md#authentication).
- **Reference hardware is a cheap Vretti 420B** (Poskey-class TSPL, ~203 dpi, `2d37:62de`) - the
  only verified model. It *should* work with any USB TSPL printer; **feedback / PRs for other
  printers are welcome** ([issue](../../issues)). See [Hardware](docs/hardware.md) for what to buy.
- **Many cheap clones are write-only for status** - they print fine but always report "ready".
  Printing is unaffected ([details](docs/configuration.md#status-reading-is-optional)).

## 💡 Motivation

The itch behind this is **printing labels for a self-hosted
[Homebox](https://github.com/sysadminsmedia/homebox) inventory** (a QR + name/asset id, from a
phone) - but Homebox is a clean, optional module on top of a **general-purpose TSPL printer
service** that's just as useful on its own. Guiding principles:

- **No CUPS wrapper** - a single thermal printer doesn't need a spooler and PPDs; raw TSPL over USB
  is simpler and behaves the same everywhere.
- **Lowest dependency cost** - pure-wheel libraries only (`pypdfium2`, `segno`, ...), no system
  print stack; runs happily on a Pi.
- **Generic core, optional integrations** - the service knows nothing about Homebox until you
  configure it.

The architecture and trade-offs are in **[Design](docs/design.md)**.

## 📚 Documentation

| Doc | What's in it |
| --- | --- |
| **[Configuration](docs/configuration.md)** | Every setting (must / should / optional) + setting up the printer (USB id, udev rule, `PRINTER_USB`). |
| **[Advanced usage](docs/advanced-usage.md)** | Non-Docker install, authentication, the REST API, text auto-fit, Homebox, Docker tags/arches. |
| **[Hardware](docs/hardware.md)** | Which cheap 420B-class printer to buy and where (rough, LLM-sourced stub for now). |
| **[Design](docs/design.md)** | Architecture, the moving parts, and the reasoning behind the design. |
| **[Roadmap](docs/roadmap.md)** | What's planned next - printer auto-discovery, OIDC/SSO, and more. |
| **[Developing](docs/developing.md)** | Contributor onramp: project layout, running from source, tests, and the testbench. |
| **[Testing](docs/TESTING.md)** | Deep reference on the automated test harness (isolation, fixtures, coverage, CI). |
| **[Build & release](docs/BUILD.md)** | Versioning (`hatch-vcs`), the Docker image, and release workflows. |

## 📄 License

[MIT](LICENSE)
