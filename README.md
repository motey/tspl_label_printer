# 🏷️ LabelJetty

<a href="docs/labejetti_screenshot.png"><img src="docs/labejetti_screenshot.png" alt="LabelJetty web UI" align="right" width="250"></a>

**Turn a cheap, USB-only TSPL thermal label printer into a smart, network-accessible label
printer** - drive it from your phone, your desktop, or another machine. Point it at a small
always-on box (a Raspberry Pi next to the printer is the classic setup) and print labels from
anywhere on your LAN.

It talks to the printer **directly over USB** (via `pyusb`/libusb) - no CUPS, no vendor
driver, no spooler - and gives you a mobile-first **web UI**, a **REST API**, and a Python
**library** for printing PNGs, PDFs, text, markdown, barcodes and QR codes. It also has an
optional, self-contained **[Homebox](https://github.com/sysadminsmedia/homebox)** integration
for printing inventory labels.

> **Status:** functional. Library, REST API, web UI (print · preview · live status), Homebox
> integration, and multi-token / multi-user auth all work.

## ✨ Features

- 📦 **[Homebox](https://github.com/sysadminsmedia/homebox) integration** (the headline feature) -
  search your self-hosted inventory and print item/location labels straight from the web UI, or
  wire up Homebox's own print button to LabelJetty. A self-contained, optional module that's
  invisible until you configure it. → [how it works](docs/advanced-usage.md#homebox-integration)
- **Direct USB** communication with TSPL printers - minimal dependency footprint, no CUPS.
- Print **PNG**, **PDF**, **plain text**, **basic markdown**, **barcodes** (Code128, EAN, UPC,
  Code39, ...) and **QR codes**, plus composite barcode/QR + text labels.
- **Auto-fit rendering** - text and markdown scale to fill the label automatically; QR codes
  render to a bitmap scaled and centered. No guessing font sizes per label stock.
  → [text & auto-fit](docs/advanced-usage.md#text-rendering--auto-fit)
- Configurable **label size** (mm) and **DPI**; pixel dimensions are derived for you. Named
  **label profiles** for your common sizes. → [configuration](docs/configuration.md)
- **Mobile-first web UI** - print every label type, live **preview** before you waste a label,
  and watch the job queue + printer/worker status update live.
- **REST API** (FastAPI) with a persistent **job queue** (SQLite) and a single background
  **worker** that owns the printer and prints one job at a time. Live API docs at `/docs`
  (Swagger), `/redoc`, and `/openapi.json`.
  → [REST API reference](docs/advanced-usage.md#the-rest-api)
- **Auth when you want it** - multi-token (for machines) and multi-user login (for humans),
  off by default for trusted-LAN convenience. Designed [OIDC-ready](docs/roadmap.md#oidc--sso-authentication)
  but not yet implemented. → [authentication](docs/advanced-usage.md#authentication)
- **Dry-run mode** and a **CLI test bench** for development and on-device geometry checks
  without wasting labels. → [testbench](docs/developing.md#real-world-print-tests-with-the-testbench)

## 🚀 Run it (Docker)

The image is published to Docker Hub as
[`motey/labeljetty`](https://hub.docker.com/r/motey/labeljetty) and is the recommended way to
deploy on an always-on box. For a real deployment, use **Docker Compose** - there's a ready-made
[`docker-compose.yml`](docker-compose.yml) in this repo:

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

Then open **http://localhost:8888/** for the web UI.

What the pieces do:

- **`devices: /dev/bus/usb`** gives the container the printer's USB bus. Permissions are still
  governed by a host **udev rule** (see
  [Configuration → Setting up the printer](docs/configuration.md#setting-up-the-printer)). You can
  scope this down to a single device node.
- **`PRINTER_USB`** selects *which* USB device is your printer. `vid:<vendor>:pid:<product>` is the
  robust form (survives replugging); find yours with `lsusb`. This is the only required setting.
- **`./data:/data`** persists the SQLite job DB and stored images. The container already points
  `SQLITE_PATH` / `IMAGE_STORAGE_DIRECTORY` at `/data` and binds to `0.0.0.0:8888`.

The committed [`docker-compose.yml`](docker-compose.yml) also has commented-out blocks for label
geometry, [authentication](docs/advanced-usage.md#authentication), and
[Homebox](docs/advanced-usage.md#homebox-integration).

<details>
<summary><b>Just kicking the tyres?</b> A one-off <code>docker run</code> (no compose file needed)</summary>

```sh
docker run --rm -p 8888:8888 \
  --device=/dev/bus/usb \
  -e PRINTER_USB=vid:2d37:pid:62de \
  -v "$(pwd)/data:/data" \
  motey/labeljetty:latest
```

This is fine for a quick test; prefer Compose for anything you want to keep running.
</details>

Every setting is an env var - see the full list in [Configuration](docs/configuration.md). Image
tags (`latest` / `beta` / `X.Y.Z` / `dev`) and supported architectures are documented in
[Advanced usage → Docker](docs/advanced-usage.md#docker-tags--architectures).

> The full **[configuration reference](docs/configuration.md)** (and how to set up the printer)
> lives in its own doc. Running **without** Docker (PyPI / source), the REST API, authentication,
> and Homebox setup are in **[Advanced usage](docs/advanced-usage.md)**.

## ⚠️ Important to know

> 🚧 **This is an early project.** It works and is actively used, but the developer still treats it
> as a **beta** - expect rough edges and bugs. Feedback, bug reports, and pull requests are very
> welcome: open an [issue](../../issues). See the [Roadmap](docs/roadmap.md) for what's planned.

- **No authentication by default.** Out of the box (`AUTH_MODE=open`) **every endpoint and the
  whole web UI are public** - anyone who can reach the host can print, browse the job queue,
  and read printer status. That's intentional for the common case (one printer on a trusted
  home LAN), but **do not expose it to the internet or an untrusted network** without turning
  on auth. See [Advanced usage → Authentication](docs/advanced-usage.md#authentication).

- **The reference hardware is a cheap Vretti 420B** (a Poskey-class TSPL printer, ~203 dpi, USB id
  `2d37:62de`) - that's what this is developed and tested against. It *should* work with any
  USB TSPL printer, but that one is the only one verified. **Feedback and pull requests for
  other printers are very welcome** - open an [issue](../../issues) with your model and results.
  See [Hardware](docs/hardware.md) for what to buy and where to find one.

- **Many cheap TSPL clones are write-only for status.** They print fine but never answer status
  queries, so live status (paper out / head open / ...) simply reads as "ready" on those models.
  Printing is unaffected. See
  [Configuration → Status reading is optional](docs/configuration.md#status-reading-is-optional).

## 💡 Motivation

The personal itch behind this project is **printing labels for a self-hosted
[Homebox](https://github.com/sysadminsmedia/homebox) inventory**: a QR code plus the item name
/ asset ID, on a small thermal label, from my phone. That's the concrete goal - but the Homebox
part is a clean, optional module on top of a **general-purpose TSPL printer service**, so it's
just as useful as a generic network label printer with no Homebox in sight.

A few principles shaped how it's built:

- **No CUPS wrapper.** Wrapping CUPS means a print queue, PPDs/drivers, and a spooler to babysit
  - heavy machinery for a single, simple thermal printer. Talking TSPL **directly over USB**
  with `pyusb` is dramatically simpler, easier to reason about, and works the same everywhere.
- **Lowest dependency cost possible.** No vendor drivers, no system print stack. Even the things
  that usually drag in system libraries are kept light: PDFs render with `pypdfium2` and QR
  codes with `segno`, both pure-wheel installs. The whole thing is meant to run happily on a
  Raspberry Pi.
- **Generic core, optional integrations.** The printer service knows nothing about Homebox;
  Homebox is a module that only appears when you configure it. The side-quest (a clean USB TSPL
  library + service) stays cleanly separable from the primary goal.

The deeper "why it's built this way" - the layered architecture and the trade-offs - is in
**[Design](docs/design.md)**.

## 📚 Documentation

| Doc | What's in it |
| --- | --- |
| **[Configuration](docs/configuration.md)** | Every setting (what you must / should / can set), plus setting up the printer (USB id, udev rule, `PRINTER_USB`). |
| **[Advanced usage](docs/advanced-usage.md)** | Running without Docker (PyPI / source), authentication, the REST API, text auto-fit, Homebox integration, and Docker tags/architectures. |
| **[Hardware](docs/hardware.md)** | Which cheap 420B-class printer to buy and where to find one (rough, LLM-sourced stub for now). |
| **[Design](docs/design.md)** | The architecture, the moving parts (connection → library → service → interface), and the motivation behind the design decisions. |
| **[Roadmap](docs/roadmap.md)** | What's planned next - printer auto-discovery, OIDC/SSO, and more. |
| **[Developing](docs/developing.md)** | A starting point for contributors: project layout, how to run from source, the test suite, and using `testbench.py` for real-world print tests. |
| **[Testing](docs/TESTING.md)** | Deep reference on the automated test harness - isolation, fixtures, coverage, and CI. |
| **[Build & release](docs/BUILD.md)** | How versioning (`hatch-vcs`), the Docker image, and the release workflows fit together. |

## 📄 License

[MIT](LICENSE)
