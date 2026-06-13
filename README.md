# tspl_label_printer

Turn a cheap, USB-only **TSPL thermal label printer** into a smart, network-accessible label
printer that can be driven from a phone, a desktop, or another machine — typically running on
a small always-on computer (e.g. a Raspberry Pi) next to the printer.

It talks to the printer **directly over USB** (via `pyusb`/libusb) — no CUPS, no vendor
driver — and exposes both a Python library and a REST API for printing PNGs, PDFs, text,
markdown, barcodes and QR codes.

> Status: functional. The library, REST API, a mobile-first **web UI** (print + preview +
> live status), optional **Homebox** integration, and multi-token / multi-user
> **[authentication](#authentication)** all work; only packaging remains on the roadmap. See
> [`docs/design.md`](docs/design.md)
> for the full design and roadmap.
>
> ⚠️ **Authentication is OFF by default** (`AUTH_MODE=open`) — fine on a trusted LAN, but read
> [Authentication](#authentication) before exposing it anywhere else.

---

## Features

- **Direct USB** communication with TSPL printers — minimal dependency footprint.
- Print **PNG**, **PDF**, **plain text**, **basic markdown**, **barcodes** (Code128, EAN,
  UPC, Code39, …) and **QR codes**, plus composite barcode/QR + text labels.
- Configurable **label size** (mm) and **DPI**; pixel dimensions are derived automatically.
- **Auto-fit rendering**: plain text and markdown scale to fill the label by default (markdown
  keeps `#`/`##` headings proportionally larger; pass an explicit font size to fix it), and
  **QR codes are rendered to a bitmap scaled to fill the label** and centered (optionally with
  an auto-sized caption).
- **REST API** (FastAPI) with a persistent **job queue** (sqlite) and a single background
  **worker** that owns the printer and prints one job at a time.
- Live **printer status** (ready / head open / paper out / ribbon out / paused / error) — on
  printers that support status read (many cheap clones are print-only; printing still works).
- **Dry-run mode** that prints the generated TSPL to stdout for development without hardware.
- A **CLI test bench** for exercising the library and checking label positioning/sizing.

## Architecture

```
┌────────────────────────────────────────────────────┐
│  REST API (FastAPI, token auth)                      │  ← interface layer
├────────────────────────────────────────────────────┤
│  Print service: job queue (sqlite) + worker process  │  ← service layer
├────────────────────────────────────────────────────┤
│  TSPLPrinter library (render → TSPL commands)         │  ← library layer
├────────────────────────────────────────────────────┤
│  TSPLPrinterConnectionUSB (pyusb send/receive)        │  ← connection layer
└────────────────────────────────────────────────────┘
                         │ USB
                   ┌───────────┐
                   │  Printer  │
                   └───────────┘
```

The reference hardware is a **Vretti / Poskey-class USB label printer with TSPL support**
(~203 dpi).

---

## Requirements

- **Python 3.11+**
- [`uv`](https://docs.astral.sh/uv/) for dependency/virtualenv management
- **libusb** (usually present on Linux; `pyusb` talks to it)
- A USB **TSPL** label printer

## Installation

The project uses `uv`. From the repository root:

```sh
# Install uv (if you don't have it)
curl -fsSL https://astral.sh/uv/install.sh | sh

# Create the virtualenv and install all dependencies
uv sync
```

`uv run …` automatically uses the project's virtualenv — you never have to activate it
manually.

---

## Printer setup

Talking to the printer over raw USB needs two things: **permission** to access the USB device
node, and a **`PRINTER_USB` selector** telling the service which device to use.

To create your configuration, copy the documented sample and edit it:

```sh
cp sample.env .env
```

[`sample.env`](sample.env) lists every setting with
its default; only `PRINTER_USB` must be filled in.

### 1. Find your printer

```sh
lsusb
```

Look for your label printer, e.g.:

```
Bus 001 Device 015: ID 2d37:62de Zhuhai Poskey Technology Co.,Ltd 420B
```

Here the **vendor:product id** is `2d37:62de` — note these down.

### 2. Grant USB access (udev rule)

By default a normal user cannot open the USB device, which fails with:

```
usb.core.USBError: [Errno 13] Access denied (insufficient permissions)
```

Fix it with a udev rule that gives the `plugdev` group access (most desktop users are already
in `plugdev` — check with `groups`). Replace the ids with **your** printer's:

```sh
sudo tee /etc/udev/rules.d/99-tspl-printer.rules >/dev/null <<'EOF'
# TSPL label printer — allow plugdev group to access it over raw USB
SUBSYSTEM=="usb", ATTRS{idVendor}=="2d37", ATTRS{idProduct}=="62de", MODE="0660", GROUP="plugdev"
EOF

# Reload rules and re-trigger (or just unplug/replug the printer)
sudo udevadm control --reload-rules
sudo udevadm trigger
```

If you are not in `plugdev`, add yourself and log out/in:

```sh
sudo usermod -aG plugdev "$USER"
```

> Quick alternative for a one-off test: run the command with `sudo` (e.g.
> `sudo uv run labeljetty-testbench status`). The udev rule is the proper,
> persistent solution and is what you want on an always-on box.

### 3. Select the printer (`PRINTER_USB`)

Configuration lives in [`.env`](.env). The
`PRINTER_USB` variable selects the device. The most robust selector is **vendor:product id**,
because — unlike a USB bus/address — it survives replugging:

```sh
# .env
PRINTER_USB=vid:2d37:pid:62de
```

Supported `PRINTER_USB` forms:

| Form                          | Example                          | Notes                                  |
| ----------------------------- | -------------------------------- | -------------------------------------- |
| Vendor + product id           | `vid:2d37:pid:62de`              | **Recommended** — stable across replug |
| Vendor id only (first match)  | `vid:2d37`                       | If you only have one matching device   |
| Serial number                 | `serial:ABC123456`               | If the printer exposes a serial        |
| USB port path                 | `port:3-1-2`                     | Stable per physical port               |
| Device path                   | `path:/dev/bus/usb/001/015`      | Changes on replug                      |
| Bus + address                 | `bus:1:addr:15`                  | Changes on replug                      |

### 4. Verify

Print the built-in alignment pattern — the surest test that the printer works and that the
label geometry is right:

```sh
uv run labeljetty-testbench pattern
```

A correctly configured label shows a border flush to all four edges, with the millimetre
ruler ticks landing on whole millimetres. Adjust `--width-mm` / `--height-mm` / `--dpi` to
match your label stock.

> **Heads-up — status reading is optional.** Many cheap TSPL printers (Xprinter / Poskey-class
> clones) have an effectively **write-only USB interface**: they print fine but never answer
> status queries. On such a printer `testbench.py status` prints *"status: not available"* and
> the API's `/printer/status` returns `status_supported: false`. **This does not affect
> printing** — the service treats an unreadable status as "ready" and prints anyway. You only
> get live status (ready / paper out / head open / …) on printers that implement it. Use
> `testbench.py probe` to check whether yours does.

---

## Configuration

All settings are read from environment variables (or
[`.env`](.env) — see
[`sample.env`](sample.env) for a documented template).

| Variable                  | Default              | Description                                              |
| ------------------------- | -------------------- | ------------------------------------------------------- |
| `PRINTER_USB`             | *(required)*         | Which USB printer to use (see forms above)              |
| `SERVER_LISTENING_HOST`   | `localhost`          | API bind host (use `0.0.0.0` to expose on the LAN)      |
| `SERVER_LISTENING_PORT`   | `8888`               | API port                                                |
| `AUTH_MODE`               | `open`               | `open` (no auth) or `protected` — see [Authentication](#authentication) |
| `AUTH_TOKENS`             | `[]`                 | JSON list of API tokens for machines, e.g. `[{"name":"ci","token":"…"}]` |
| `AUTH_USERS`              | `[]`                 | JSON list of login users, e.g. `[{"username":"tim","password_hash":"pbkdf2_sha256$…"}]` |
| `SESSION_SECRET`          | *(ephemeral)*        | Secret signing session cookies; set a stable value so logins survive restarts |
| `SQLITE_PATH`             | `./printjobs.sqlite` | Job-queue database (relative to the working directory)  |
| `IMAGE_STORAGE_DIRECTORY` | `./../images`        | Where uploaded files are stored (relative to cwd)       |
| `DELETE_OLD_JOBS_AFTER_DAYS` | `100`             | Retention for old jobs and their files                  |
| `DEFAULT_LABEL_WIDTH_MM`  | `100`                | Default label width when a job doesn't specify one      |
| `DEFAULT_LABEL_HEIGHT_MM` | `30`                 | Default label height                                    |
| `DEFAULT_DPI`             | `203`                | Default printer resolution                              |
| `LOG_LEVEL`               | `DEBUG`              | `CRITICAL`/`ERROR`/`WARNING`/`INFO`/`DEBUG`             |

> **Note:** `SQLITE_PATH` and `IMAGE_STORAGE_DIRECTORY` are resolved **relative to the current
> working directory**. Run the service from the same directory each time (this README assumes
> the repository root), or set absolute paths in `.env`.

---

## Authentication

> # ⚠️ THE DEFAULT IS NO AUTHENTICATION
>
> Out of the box (`AUTH_MODE=open`) **every endpoint and the whole web UI are public** —
> anyone who can reach the host can print, browse the job queue, and read printer status.
> This is intentional for the common case: a single printer on a **trusted home LAN**.
>
> **Do NOT expose this service to the internet, an untrusted network, or a shared host in
> open mode.** Before doing so, set `AUTH_MODE=protected` and configure at least one token or
> user — or put the service behind your own reverse-proxy auth / VPN.

There are two modes, selected by `AUTH_MODE`:

- **`open`** (default) — no authentication. LAN-only convenience.
- **`protected`** — every API and UI route requires a valid credential. Multiple credential
  **providers** can be active at once; any one of them satisfies a request:
  - **API tokens** (`AUTH_TOKENS`) — for machines/scripts. Sent as `Authorization: Bearer <token>`.
  - **Local users** (`AUTH_USERS`) — for humans. They log in at `/login`; a signed session
    cookie keeps them authenticated. (Browsers hitting a protected route while logged out are
    redirected to `/login`; API clients receive `401`.)

> The auth layer is built around a pluggable provider model and a `Principal` identity, so
> **OIDC / SSO is planned as a drop-in third provider** without changing any routes.

### Protected setup

```sh
# Generate a password hash for a login user (never store plaintext):
uv run labeljetty-hash-password
# → pbkdf2_sha256$600000$…$…

# .env
AUTH_MODE=protected
AUTH_TOKENS=[{"name":"ci","token":"choose-a-long-random-secret"}]
AUTH_USERS=[{"username":"tim","password_hash":"pbkdf2_sha256$600000$…$…"}]
SESSION_SECRET=another-long-random-string   # so logins survive restarts
```

If `AUTH_MODE=protected` but neither tokens nor users are configured, startup fails fast
(otherwise you'd lock yourself out). If `SESSION_SECRET` is unset, an ephemeral one is used
and logins reset on restart (a warning is logged).

> **Migration:** the old single `API_ACCESS_TOKEN` variable has been **removed**. Replace it
> with `AUTH_MODE=protected` + an `AUTH_TOKENS` entry.

---

## Running the service

From the repository root:

```sh
uv run labeljetty
```

The service starts the REST API, the **web UI**, and the background print worker. Open
[`http://<host>:<port>/`](http://localhost:8888/) in a browser for the mobile-first UI
(print every label type, pick a label profile, **preview** before printing, and watch the
job queue + printer/worker status live). Interactive API docs (Swagger UI) are served at
`/docs`, and the OpenAPI schema at `/openapi.json`.

### Web UI & Homebox

The UI at `/` covers everything the API does, plus label **profiles** (named sizes via
`LABEL_PROFILES`) and a live label preview. When `HOMEBOX_URL` + `HOMEBOX_API_KEY` are set
(see [`sample.env`](sample.env)), an optional **Homebox** section
appears: search your inventory and print **Homebox's own label** (fetched from its
labelmaker API), and a setup wizard at `/ui/homebox/setup` helps wire up Homebox's native
print button (external label service or a generated print-command script). With nothing
configured there is no trace of Homebox in the app.

### REST API

All routes are under the `/api` prefix. In `protected` mode, send an API token as
`-H "Authorization: Bearer <token>"` (see [Authentication](#authentication)).

| Method & path             | Body                                  | Purpose                              |
| ------------------------- | ------------------------------------- | ------------------------------------ |
| `POST /api/print/png`     | multipart `file=@label.png`           | Enqueue a PNG print                  |
| `POST /api/print/pdf`     | multipart `file=@doc.pdf`, `page`     | Enqueue a PDF print (page or `all`)  |
| `POST /api/print/text`    | JSON `{"text": "..."}` (optional `font_size`, `fit`; auto-fits if omitted) | Enqueue plain text |
| `POST /api/print/markdown`| JSON `{"text": "# Hi\n* a"}`          | Enqueue basic markdown               |
| `POST /api/print/barcode` | JSON `{"data": "123", "barcode_type": "128", "text": "..."}` | Enqueue a barcode |
| `POST /api/print/qrcode`  | JSON `{"data": "https://…", "ecc_level": "M", "text": "..."}` | Enqueue a QR code |
| `GET  /api/jobs`          | `?limit=100`                          | List recent jobs + their status      |
| `GET  /api/jobs/{job_id}` | —                                     | Status of a single job               |
| `GET  /api/worker/status` | —                                     | Background worker health             |
| `GET  /api/printer/status`| —                                     | `{reachable, status_supported, status}`; `503` only if the device can't be opened |

All print endpoints also accept optional `label_width_mm`, `label_height_mm`, `dpi` and
`copies` to override the defaults per job. `/print/png` and `/print/pdf` additionally take
`fit` — how the image scales to the label: `fit` (contain, default), `fill` (cover/crop),
`stretch` (exact size) or `original` (keep the image's own size). Text and markdown use
their own `fit` (`fill`/`width`); see [Text rendering & auto-fit](#text-rendering--auto-fit).

Example:

```sh
BASE=http://127.0.0.1:8888/api

curl -s -X POST $BASE/print/text -H 'content-type: application/json' \
  -d '{"text":"hello label","copies":2}'
curl -s -X POST $BASE/print/png -F file=@tests/fixtures/label_test.png
curl -s "$BASE/jobs?limit=10"
```

---

## Text rendering & auto-fit

Plain-text and markdown labels **auto-scale to your label** by default — you don't have to
guess a font size for each stock. Markdown keeps headings proportionally larger (`#` = 2×,
`##` = 1.5× the body). Two things control sizing:

- **Fixed size** — pass an explicit font size (`--font-size` on the test bench, `font_size`
  in the `/print/text` body) to disable auto-fit and use that exact size.
- **Fit mode** (`fit`, default `fill`) — how auto-fit chooses the size:

  | `fit`   | Behaviour                                                                                  |
  | ------- | ------------------------------------------------------------------------------------------ |
  | `fill`  | Grow the text to fill the label (width **and** height), wrapping lines as needed. Maximises size; short text may wrap to use the vertical space (e.g. `Box 12` → two big lines). |
  | `width` | Size the text to the label **width**, keeping your line breaks (no extra wrapping); height may be left blank (e.g. `Box 12` stays one line). Falls back to `fill` if a line is too long to fit unwrapped. |

Examples:

```sh
# default (fill) — fills the whole label
uv run labeljetty-testbench text "Box 12"

# width — keep it on one line, sized to the label width
uv run labeljetty-testbench text "Box 12" --fit width

# fixed size, no auto-fit
uv run labeljetty-testbench text "Box 12" --font-size 40

# markdown supports --fit too
uv run labeljetty-testbench markdown "# Title
* one
* two" --fit width
```

Via the API:

```sh
curl -s -X POST $BASE/print/text -H 'content-type: application/json' \
  -d '{"text":"Box 12", "fit":"width"}'
```

---

## Testing

There are two complementary layers:

1. **Automated test suite** (`tests/`) — a hardware-free `pytest` harness covering
   every unit, the print-service worker, and all REST + web-UI endpoints. It needs
   no `.env`, printer, or network. Run it with:

   ```sh
   uv sync --group dev
   uv run python -m pytest
   ```

   Full setup, isolation design, fixtures, and CI details are in
   [docs/TESTING.md](docs/TESTING.md).

2. **CLI test bench** ([`src/labeljetty/testbench.py`](src/labeljetty/testbench.py)) —
   for **manual hardware testing**, which is intentionally never automated. It drives
   the `TSPLPrinter` library directly, either against the real USB printer or in
   `--dry-run` mode (the generated TSPL is printed to stdout instead of being sent to
   the device), so you can check label positioning/sizing on the real printer.

### Dry-run (no hardware needed)

All commands are run from the **repository root**:

```sh
# Print an alignment/ruler test pattern as TSPL to stdout
uv run labeljetty-testbench --dry-run pattern

# Other renderers in dry-run mode
uv run labeljetty-testbench --dry-run text "Hello world"
uv run labeljetty-testbench --dry-run markdown "# Title
* one
* two"
uv run labeljetty-testbench --dry-run barcode 12345678 --text "Item 42"
uv run labeljetty-testbench --dry-run qrcode "https://example.com" --text "box 1"
uv run labeljetty-testbench --dry-run pdf /path/to/file.pdf --page 0
uv run labeljetty-testbench --dry-run status
```

Global options apply to every subcommand:

| Option         | Default  | Meaning                                                   |
| -------------- | -------- | --------------------------------------------------------- |
| `--dry-run`    | off      | Print TSPL to stdout instead of sending to the printer    |
| `--width-mm`   | from env | Label width in mm (`DEFAULT_LABEL_WIDTH_MM`, else 100)     |
| `--height-mm`  | from env | Label height in mm (`DEFAULT_LABEL_HEIGHT_MM`, else 30)    |
| `--dpi`        | from env | Printer resolution (`DEFAULT_DPI`, else 203)              |
| `--usb`        | from env | Override the `PRINTER_USB` selector (ignored in dry-run)  |

Per-subcommand options include `--font-size` / `--fit` (text & markdown; see
[Text rendering & auto-fit](#text-rendering--auto-fit)), `--page` (pdf), `--type`/`--text`
(barcode), and `--ecc`/`--text` (qrcode).

Run `uv run labeljetty-testbench --help` (or `… <command> --help`) for the
full list.

### Against the real printer

Drop `--dry-run` to send to hardware (requires the [printer setup](#printer-setup) above):

```sh
# Print the alignment pattern on a 50x30 mm label and verify it lands flush to the edges
uv run labeljetty-testbench --width-mm 50 --height-mm 30 pattern

# Query live printer status (head open / paper out / ribbon out / ...)
uv run labeljetty-testbench status

# Diagnose whether this printer answers status queries at all
uv run labeljetty-testbench probe
```

The **`pattern`** command is the quickest way to validate geometry: a correctly configured
label shows the border flush to all four edges, with the millimetre ruler ticks landing on
whole millimetres.

If `status` says *"not available"*, your printer is write-only for status (see the heads-up in
[Printer setup](#printer-setup)) — printing still works. The **`probe`** command confirms this,
and **`raw`** lets you send arbitrary bytes to the printer for debugging, e.g.
`testbench.py raw '1b213f'` (hex) or `testbench.py raw '~!T' --text`.

### Smoke-test the web API

Start the service (see [Running the service](#running-the-service)) and exercise the
endpoints. The API enqueues jobs that the background worker prints one at a time:

```sh
BASE=http://127.0.0.1:8888/api   # match your configured host/port

curl -s $BASE/worker/status                         # worker health
curl -s -X POST $BASE/print/png -F file=@tests/fixtures/label_test.png
curl -s "$BASE/jobs?limit=10"                       # inspect the queue
curl -s $BASE/printer/status                         # {reachable, status_supported, status}
```

---

## Roadmap & design

The detailed design, current status table, and roadmap live in
[`docs/design.md`](docs/design.md).
Highlights still to come: a generalized worker for all payload types, a mobile-first web UI
with label preview, optional **Homebox** inventory integration, multi-token/multi-user auth,
and packaging (systemd unit / container image / udev helper).

## License

[MIT](LICENSE)
