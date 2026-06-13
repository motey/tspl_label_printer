# TSPL Label Printer — Project Description & Goals

## Vision

Turn a cheap, USB-only TSPL thermal label printer into a "smart", network-accessible
label printer that can be driven from a phone, a desktop, or another machine — running
on a small always-on computer (e.g. a Raspberry Pi) next to the printer.

There are two intertwined goals:

1. **Primary goal — Homebox label printing.**
   Make it trivial to print labels (QR code + item name/asset ID) for items managed in a
   self-hosted [Homebox](https://github.com/sysadminsmedia/homebox) inventory server.
   This is the concrete itch this project scratches.

2. **Side quest — a generic USB TSPL printer interface.**
   The Homebox use case sits on top of a general-purpose library + service that can drive
   *any* TSPL printer over USB and print PDFs, images, text, barcodes and QR codes. Useful
   on its own, independent of Homebox.

The development/reference hardware is a **Vretti USB Etikettendrucker (label printer) with
TSPL support**, ~203 dpi.

---

## Architecture

Three layers, lowest dependency footprint possible (talk to the printer directly over USB
rather than relying on CUPS/vendor drivers):

```
┌────────────────────────────────────────────────────┐
│  Web UI (mobile + desktop)        REST API (tokens)  │  ← interface layer
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

- **Connection layer** — raw USB endpoint I/O, device discovery, reconnect.
- **Library layer** — convert PDFs/PNGs/text/barcodes/QR into TSPL command streams; query
  status. No web/server concerns. Usable as a standalone Python library.
- **Service layer** — accept print jobs, persist them, serialize access to the single
  physical printer through a background worker so concurrent requests don't collide.
- **Interface layer** — Web UI for humans, REST API for machines.

---

## Library requirements

Goal: a clean, importable Python library that is the *only* thing that knows TSPL.

- Talk to the printer at the lowest practical level (pyusb) — no external print-system
  dependency (no CUPS, no vendor driver).
- Configurable label size (width/height in mm) and DPI; derive pixel dimensions from these.
- Support printing:
  - **PDF** — render page(s) to a bitmap sized to the label. *(not yet implemented)*
  - **PNG / images** — with optional auto-resize-to-fit (keep aspect ratio), dithering for
    thermal output. *(implemented)*
  - **Raw text** — render text to the label with sane wrapping. *(only via markdown today)*
  - **Simple markdown** — headings, bullets, bold. *(implemented, basic)*
  - **Numbers/strings as barcodes** — Code128, EAN, UPC, Code39, etc. *(implemented)*
  - **Text/URLs as QR codes** — with ECC level + auto-sizing. *(implemented)*
  - **Composite labels** — e.g. QR + text, barcode + text (the Homebox label shape).
    *(basic helpers exist)*
- Query printer status (ready / head open / paper out / ribbon out / paused / error) and
  expose a typed status object. *(parsing exists; the live status path has bugs — see Known
  issues)*
- A `dry_run` mode that prints the generated TSPL to stdout instead of the device, for
  development without hardware. *(implemented)*

### Known issues / cleanup in the library (to fix while reviving)

- `TSPLPrinter.receive()` references `self.device`, which doesn't exist (the connection is
  `self.connection`); this path is dead.
- `is_ready()` / `get_error_message()` do dict-style access (`status["ready"]`) on a Pydantic
  model that exposes attributes (`status.ready`) — will raise.
- `TSPLPrinterStatusMessage` has no `error` field, but callers read `status["error"]`.
- `get_status()` sends the literal string `"b'\x1b!?'"` rather than the status-query bytes.
- Decide and document the real TSPL status-query command for the Vretti and verify the
  status-byte bit map against the actual device.

---

## Print service requirements

- A persistent **job queue** (sqlite) so requests are decoupled from the physical print and
  survive restarts. *(implemented)*
- A **single worker** that owns the printer and processes jobs one at a time. *(implemented
  via multiprocessing + watchdog with retry/backoff)*
- Persist per-job: input file/payload, type, requested label size, timestamps
  (queued/started/finished), final printer status, and error. *(partly implemented — only
  PNG today)*
- Configurable retention: auto-delete old jobs and their stored files after N days.
  *(implemented; not yet scheduled to run)*
- Extend the job model beyond PNG to all supported payload types (pdf/text/markdown/
  barcode/qrcode/composite) with their parameters. *(TODO)*

---

## Web interface & API requirements

### Base

- Desktop **and** mobile friendly modern UI.
- Auth modes, selectable by configuration:
  - **Open mode** — no login (LAN-only convenience).
  - **Login mode** — one or more users configured via env vars.
  - **API tokens** — one or more tokens configured via env vars for machine-to-machine use.
  - *(Today only a single optional bearer token exists — needs extending to multi-token /
    multi-user.)*

### Features (UI + API parity)

- Print: PDF, PNG, raw text, simple markdown, a number as a barcode, or text/URL as a QR
  code.
- Pick label size per job; fall back to a configurable default label size (env var) when
  none is given.
- Possibility to set label profiles (x and y size with a profile name e.g. "DHL Versandmarke", "Homebox Label")
- Show job history / queue status and printer status (ready, paper out, etc.).
- A label **preview** (render the bitmap and show it before printing) — saves wasted labels.
- API: documented OpenAPI spec (FastAPI already generates it; expose/ship it).

### API gaps to close

- `/print/png` is currently a stub: it never writes the uploaded bytes to disk and builds a
  filename from `uuid.uuid4` (the function object) instead of `uuid.uuid4()`.
- No endpoints yet for pdf/text/markdown/barcode/qrcode, job status, or printer status.

---

## Homebox integration (primary goal)

Homebox integration is a **self-contained, optional module**. The printer service works
fully on its own; when a Homebox URL + API key are configured (and the module enabled), an
extra "Homebox" section appears in the web UI. With nothing configured, there is no trace of
Homebox in the app. This keeps the side-quest (generic TSPL printer) cleanly separable from
the primary goal.

### Homebox API (v0.26.0+ — important)

As of **Homebox v0.26.0**, items and locations were merged into a single **entity** model.
The old `/v1/items*` and `/v1/locations*` endpoints are **gone**; integrations now use
`/v1/entities*`. Design against this from the start:

- **Auth:** static API keys (prefixed `hb_…`), sent as a bearer token
  (`Authorization: Bearer hb_…`). A key inherits the access level of the user who created
  it. The Homebox server admin must have set `HBOX_AUTH_API_KEY_PEPPER` (≥32 chars) for API
  keys to function at all.
- **Search items:** `GET /v1/entities?q=<query>` (returns items by default; paginated shape
  with an `items` array).
- **Search locations:** `GET /v1/entities?isLocation=true&q=<query>`.
- **Entity summary** carries what a label needs: `name`, `assetId`, and `parent`
  (the old `location` field is now `parent`). Subscribe to the `entity.mutation` WebSocket
  event if we ever want live updates.

The natural label is: **a QR code (linking to the entity's Homebox URL, or encoding the
asset ID) plus human-readable text (name / asset ID).**

### Integration paths

There are three ways to connect the two systems. **A** and **B** are the ones we build; **C**
is a documented fallback.

**A. Printer → Homebox (pull) — the in-app module.**
The web UI's Homebox section lets the user **search items and locations** (via
`/v1/entities`), pick one, preview, and print **Homebox's own label** — fetched from its
labelmaker API (`/v1/labelmaker/{item,location,asset}/{id}`, called *without* `print=true`
so Homebox renders the image but does not run its own print command; we print the returned
image ourselves). This keeps a single source of label rendering (Homebox's, controlled by
its `HBOX_LABEL_MAKER_*` sizing) rather than maintaining a second renderer for the Homebox
shape. *(Implemented this way per the maintainer's decision; the labelmaker output observed
on v0.26 is a PNG.)*

**B. External label service (push) — the blessed way to use Homebox's own print button.**
Homebox can delegate label *rendering* to an HTTP service via
`HBOX_LABEL_MAKER_LABEL_SERVICE_URL`: it sends a `GET` with `TitleText`, `DescriptionText`,
`URL`, `Width`, `Height`, `Dpi`, `ComponentPadding`, … and expects an `image/*` back. We
expose exactly such an endpoint, which:

1. renders the label with **our** engine, tuned to our stock (same renderer as path A), and
2. **enqueues the print as a side effect**, then returns the image to Homebox.

This is elegant: one mechanism renders *and* prints, requires no script deployed on the
Homebox host, and reuses our renderer for consistent output. Setup is a single env var on the
Homebox side (`HBOX_LABEL_MAKER_LABEL_SERVICE_URL` → our endpoint).

> **Caveat to verify before relying on the side-effect print:** confirm Homebox calls the
> label-service URL **only on an explicit print action**, not on label *preview* /
> regeneration. If it's also called for previews, side-effect printing would produce spurious
> labels — in that case, fall back to path C (which only fires on the print button) or gate
> our printing behind an explicit query flag. Also respect `HBOX_LABEL_MAKER_LABEL_SERVICE_TIMEOUT`
> (default 30s): we only *enqueue* within the request and return promptly; we never block on
> the physical print completing. If our service is down, Homebox's label creation/preview is
> affected (it depends on our URL).

**C. Print command (push, fallback) — `HBOX_LABEL_MAKER_PRINT_COMMAND`.**
Homebox's per-entity print action renders a `label.png` server-side and runs a configured
command with a `{{.FileName}}` placeholder. We make this turnkey with a **setup helper page**
that, given the printer service's hostname/port, **generates a ready-to-paste bash script**:

```sh
#!/usr/bin/env sh
# Set HBOX_LABEL_MAKER_PRINT_COMMAND to:  /path/to/this-script.sh {{.FileName}}
curl -fsS -X POST "http://<printer-host>:<port>/api/print/png" \
  -H "Authorization: Bearer <token-if-configured>" \
  -F "file=@$1"
```

Alongside the script, the helper shows the **Homebox env-var hints** to match our label
stock (all sized in **pixels**, derived from the user's mm + DPI):
`HBOX_LABEL_MAKER_WIDTH`, `HBOX_LABEL_MAKER_HEIGHT`, `HBOX_LABEL_MAKER_PADDING`,
`HBOX_LABEL_MAKER_FONT_SIZE`, and `HBOX_LABEL_MAKER_PRINT_COMMAND`.

Prefer C over B when: the user wants Homebox's **native** label layout (Homebox renders, we
just print the bytes); "print means print" semantics are required with zero risk of
preview-triggered prints; or our service should not be a hard dependency of Homebox's
label-creation flow. The trade-off is a small script deployed on the Homebox host.

### Open questions to settle before building

- Encode the entity's Homebox **URL** vs. the bare **asset ID** in the QR (URL is more useful
  on a phone; asset ID is shorter/offline-friendly). Make it configurable.
- A small, configurable **label template** for the Homebox label (which fields, font sizes,
  QR position) so it fits the user's actual label dimensions.
- Confirm the exact API base prefix on the target instance (`/api/v1/entities` vs
  `/v1/entities`) and pagination/response field names against the live OpenAPI spec.

---

## Configuration (env vars)

Already present: app name, log level, listen host/port, sqlite path, image storage dir,
single API token, job retention days, and a flexible `PRINTER_USB` selector
(`serial:` / `path:` / `port:` / `vid:pid:` / `bus:addr:`).

To add:
- `DEFAULT_LABEL_WIDTH_MM`, `DEFAULT_LABEL_HEIGHT_MM`, `DEFAULT_DPI`.
- Multi-token and multi-user auth config.
- **Homebox module:** an enable flag, plus `HOMEBOX_URL` and `HOMEBOX_API_KEY` (the `hb_…`
  key). The module activates only when these are set.
- QR content choice (entity URL vs asset ID) and default label-template settings.

---

## Current status (snapshot)

| Area | State |
|------|-------|
| USB connection layer | Works (discovery strategies, lazy connect + endpoint setup, fast-fail on EACCES) |
| PNG printing | Works |
| Markdown / barcode / QR / composites | Works; text/markdown/QR **auto-fit** to the label (fill/width modes) |
| PDF printing | **Implemented** (pypdfium2, no system deps) |
| Raw-text helper | **Implemented** (`print_text`, auto-fit) |
| Printer status (live) | **Fixed**; degrades gracefully — the dev printer (Poskey 420B) is write-only and never answers status, so status read returns None / "assume ready" and never blocks printing |
| Job queue + worker | **Works for all payload types** (generalized `job_type`+`params`+file model, worker dispatch) |
| REST API | **Complete:** print png/pdf/text/markdown/barcode/qrcode + `/jobs`, `/jobs/{id}`, `/worker/status`, `/printer/status` |
| CLI test bench | **Added** (`testbench.py`): per-type subcommands, `pattern`, `status`, `probe`, `raw`, dry-run |
| Web UI | **Done** — mobile-first HTMX + Jinja2 UI: print all types, label profiles, live preview, job + printer/worker status polling |
| Auth | **Done** — `AUTH_MODE` open (default) / protected; pluggable provider model behind the central `require_access` seam returning a `Principal`: multi-token (Bearer) + multi-user (login form + signed-cookie session). Open is default with a fat README warning. Designed OIDC-ready (drop-in provider; OIDC callback reuses the session). |
| Homebox integration (modular) | **Done** — config-gated: pull (search `/v1/entities`, then fetch + print **Homebox's own** label from `/v1/labelmaker/{kind}/{id}`), push label-service endpoint (`/api/homebox/label`, renders our engine + autoprint), and a setup-helper wizard generating the print-command script (host configurable) + `HBOX_LABEL_MAKER_*` env hints. Verified live against v0.26. |

---

## Roadmap (suggested order)

1. ✅ **DONE — Stabilize the library:** fixed the status/`receive` bugs, added `print_pdf`
   (pypdfium2) and `print_text`, verified in `dry_run` and on-device. Status read found
   unsupported on the dev printer (write-only USB) → now degrades gracefully.
    1B. ✅ **DONE** — `testbench.py` CLI (`pattern` alignment/ruler diagnostic, per-type
    subcommands, `probe`/`raw` for status debugging, dry-run). Confirmed positioning/sizing
    on-device; added auto-fit so text/QR scale to the configured label.
2. ✅ **DONE — Finish the API:** `/print/png` stores + enqueues; added pdf/text/markdown/
   barcode/qrcode endpoints, plus `/jobs`, `/jobs/{id}`, `/worker/status`, `/printer/status`.
3. ✅ **DONE — Generalize the job model:** typed `PrintJob` (`job_type`+`params`+optional
   file + per-job geometry/copies); worker dispatches every payload type.
4. ✅ **DONE — Web UI:** mobile-first HTMX + Jinja2 page (`/`) to print every type + label
   profiles + live preview + queue/printer/worker status polling. No build step; served by
   FastAPI from `templates/` + `static/`.
5. ✅ **DONE — Homebox module (pull):** config-gated. Search `/v1/entities` for
   items/locations, then **fetch and print Homebox's own label** from
   `/v1/labelmaker/{item,location,asset}/{id}` (we do not pass `print=true`; we print the
   returned image ourselves). Preview shows Homebox's label; results link back to Homebox.
6. ✅ **DONE — Homebox push path:** external-label-service endpoint `/api/homebox/label`
   (`HBOX_LABEL_MAKER_LABEL_SERVICE_URL`) renders with our engine + enqueues the print
   (toggle: `HOMEBOX_LABEL_SERVICE_AUTOPRINT`), plus a setup-helper **wizard**
   (`/ui/homebox/setup`) that generates the `HBOX_LABEL_MAKER_PRINT_COMMAND` script
   (printer host configurable) and the `HBOX_LABEL_MAKER_*` env-var hints.
7. ✅ **DONE — Auth:** `AUTH_MODE` open (default, with a prominent README warning) / protected,
   selected by config. Behind the central `require_access` seam (now returning a `Principal`)
   sits a pluggable provider model: **multi-token** (`AUTH_TOKENS`, Bearer) for machines and
   **multi-user** (`AUTH_USERS`, login form → signed-cookie session via `SessionMiddleware`)
   for humans; both can be active at once. Passwords are pbkdf2 (stdlib) with a
   `labeljetty-hash-password` CLI. Browsers redirect to `/login`; API clients get 401.
   Designed **OIDC-ready** — OIDC slots in as a third provider reusing the same session, no
   route changes. (`API_ACCESS_TOKEN` removed.)
8. **Packaging:** systemd unit / container image, udev rule for non-root USB access on the
   Pi, setup docs. ← **NEXT**

---

## Optional / stretch goals

- **Standard network-printer interface** so the printer can be used from native OS print
  dialogs. Feasibility assessment:
  - **Full IPP Everywhere (driverless) — treat as a separate project.** Showing up
    automatically in the OS "Add Printer" dialog with no driver requires a real IPP server
    (binary IPP attribute protocol: Get-Printer-Attributes, Create-Job, Send-Document,
    Get-Jobs, Cancel-Job…), `_ipp._tcp` mDNS/DNS-SD advertisement with correct TXT records,
    **and** decoding the raster formats clients actually send (PWG Raster / Apple Raster /
    PDF) before converting to TSPL. The raster decode + conformance to get the OS to accept
    us is the hard part. This is project-sized and pulls in dependencies that fight the
    "minimal" principle — keep it as its own optional module/repo, not part of the core.
  - **Raw port-9100 (JetDirect) socket — a cheap stepping stone.** A tiny TCP listener that
    pipes the incoming stream into the renderer/printer is easy to build, but the OS won't
    auto-discover it: the user must add it manually and deal with page size/driver, so it
    mostly serves power users. Reasonable as a low-effort interim if a native path is wanted
    before IPP exists.
- A small **TSPL playground** endpoint to send raw TSPL for debugging.
- Label **template library** (named, reusable layouts beyond the Homebox one).
- Multi-printer support (the architecture currently assumes one printer).

---

## Non-goals (for now)

- Replacing CUPS or being a full print spooler.
- Supporting non-TSPL printer languages (ZPL/EPL) — could be a future abstraction, not a
  current target.
- Cloud / multi-tenant hosting; this is a single-LAN, single-printer appliance.
