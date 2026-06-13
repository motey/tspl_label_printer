"""Server-rendered web UI (HTMX + Jinja2).

These routes render HTML for humans and live at the application root, beside the
machine-facing JSON API under ``/api``. They reuse the shared service layer
(enqueue helpers, the headless renderer, status queries) so there is no logic
duplication — only presentation. All routes go through the same ``require_access``
auth seam as the API.
"""

from __future__ import annotations

import base64
import tempfile
from pathlib import Path
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Form, Request, UploadFile, File
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import select

from labeljetty.web.auth import require_access
from labeljetty.web.api import _enqueue, _store_upload, _job_response
from labeljetty.config import Config
from labeljetty.core.db import PrintJob, get_session
from labeljetty.printer import JobType
from labeljetty.printer.render import render_label_png_bytes
from labeljetty.service.worker import PrintServiceManager
from labeljetty.core.logging import get_logger

config = Config()
log = get_logger()

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=TEMPLATES_DIR)

ui_router = APIRouter(include_in_schema=False)

# Job types that carry an uploaded file rather than form parameters.
FILE_JOB_TYPES = {"png", "pdf"}


def _base_context(request: Request) -> dict:
    """Context shared by every template (nav, profiles, feature flags)."""
    return {
        "request": request,
        "app_name": config.APP_NAME,
        "profiles": config.get_label_profiles(),
        "default_width_mm": config.DEFAULT_LABEL_WIDTH_MM,
        "default_height_mm": config.DEFAULT_LABEL_HEIGHT_MM,
        "default_dpi": config.DEFAULT_DPI,
        "homebox_enabled": config.homebox_configured(),
    }


def _geometry(
    label_width_mm: Optional[int],
    label_height_mm: Optional[int],
    dpi: Optional[int],
) -> tuple[int, int, int]:
    """Resolve a label geometry, falling back to server defaults."""
    return (
        label_width_mm or config.DEFAULT_LABEL_WIDTH_MM,
        label_height_mm or config.DEFAULT_LABEL_HEIGHT_MM,
        dpi or config.DEFAULT_DPI,
    )


def _build_params(
    job_type: JobType,
    *,
    text: Optional[str],
    data: Optional[str],
    barcode_type: str,
    ecc_level: str,
    font_size: Optional[int],
    fit: str,
    page: str,
    image_fit: str,
) -> dict:
    """Assemble the type-specific ``params`` dict from the shared form fields."""
    if job_type == "text":
        return {"text": text or "", "font_size": font_size, "fit": fit}
    if job_type == "markdown":
        return {"text": text or "", "fit": fit}
    if job_type == "barcode":
        return {"data": data or "", "barcode_type": barcode_type, "text": text or None}
    if job_type == "qrcode":
        return {"data": data or "", "ecc_level": ecc_level, "text": text or None}
    if job_type == "pdf":
        return {"page": page if page == "all" else int(page or 0), "fit": image_fit}
    if job_type == "png":
        return {"fit": image_fit}
    return {}


# --------------------------------------------------------------------------- #
#  Pages
# --------------------------------------------------------------------------- #
@ui_router.get("/", response_class=HTMLResponse)
async def index(
    request: Request, access: Annotated[bool, Depends(require_access)]
):
    return templates.TemplateResponse("index.html", _base_context(request))


# --------------------------------------------------------------------------- #
#  Preview (render only — no print)
# --------------------------------------------------------------------------- #
@ui_router.post("/ui/preview", response_class=HTMLResponse)
async def ui_preview(
    request: Request,
    access: Annotated[bool, Depends(require_access)],
    job_type: Annotated[JobType, Form()],
    text: Annotated[Optional[str], Form()] = None,
    data: Annotated[Optional[str], Form()] = None,
    barcode_type: Annotated[str, Form()] = "128",
    ecc_level: Annotated[str, Form()] = "M",
    font_size: Annotated[Optional[int], Form()] = None,
    fit: Annotated[str, Form()] = "fill",
    page: Annotated[str, Form()] = "0",
    image_fit: Annotated[str, Form()] = "fit",
    label_width_mm: Annotated[Optional[int], Form()] = None,
    label_height_mm: Annotated[Optional[int], Form()] = None,
    dpi: Annotated[Optional[int], Form()] = None,
    file: Annotated[Optional[UploadFile], File()] = None,
):
    w, h, d = _geometry(label_width_mm, label_height_mm, dpi)
    params = _build_params(
        job_type,
        text=text,
        data=data,
        barcode_type=barcode_type,
        ecc_level=ecc_level,
        font_size=font_size,
        fit=fit,
        page=page,
        image_fit=image_fit,
    )

    tmp_path: Optional[Path] = None
    try:
        if job_type in FILE_JOB_TYPES:
            if file is None or not file.filename:
                return templates.TemplateResponse(
                    "_preview.html",
                    {"request": request, "error": "Choose a file to preview."},
                )
            suffix = ".pdf" if job_type == "pdf" else ".png"
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(await file.read())
                tmp_path = Path(tmp.name)

        png = render_label_png_bytes(
            job_type,
            params,
            width_mm=w,
            height_mm=h,
            dpi=d,
            input_file_path=tmp_path,
        )
    except Exception as e:  # render errors → show inline, don't 500 the page
        log.warning(f"Preview render failed: {e}")
        return templates.TemplateResponse(
            "_preview.html", {"request": request, "error": str(e)}
        )
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)

    data_uri = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
    return templates.TemplateResponse(
        "_preview.html",
        {"request": request, "image": data_uri, "width_mm": w, "height_mm": h},
    )


# --------------------------------------------------------------------------- #
#  Print (enqueue)
# --------------------------------------------------------------------------- #
@ui_router.post("/ui/print", response_class=HTMLResponse)
async def ui_print(
    request: Request,
    access: Annotated[bool, Depends(require_access)],
    job_type: Annotated[JobType, Form()],
    text: Annotated[Optional[str], Form()] = None,
    data: Annotated[Optional[str], Form()] = None,
    barcode_type: Annotated[str, Form()] = "128",
    ecc_level: Annotated[str, Form()] = "M",
    font_size: Annotated[Optional[int], Form()] = None,
    fit: Annotated[str, Form()] = "fill",
    page: Annotated[str, Form()] = "0",
    image_fit: Annotated[str, Form()] = "fit",
    label_width_mm: Annotated[Optional[int], Form()] = None,
    label_height_mm: Annotated[Optional[int], Form()] = None,
    dpi: Annotated[Optional[int], Form()] = None,
    copies: Annotated[int, Form()] = 1,
    file: Annotated[Optional[UploadFile], File()] = None,
):
    from labeljetty.web.api import LabelOptions

    opts = LabelOptions(
        label_width_mm=label_width_mm,
        label_height_mm=label_height_mm,
        dpi=dpi,
        copies=copies,
    )
    params = _build_params(
        job_type,
        text=text,
        data=data,
        barcode_type=barcode_type,
        ecc_level=ecc_level,
        font_size=font_size,
        fit=fit,
        page=page,
        image_fit=image_fit,
    )
    try:
        input_file_name = None
        if job_type in FILE_JOB_TYPES:
            if file is None or not file.filename:
                raise ValueError("Choose a file to print.")
            input_file_name = _store_upload(
                file, ".pdf" if job_type == "pdf" else ".png"
            )
        job = _enqueue(
            job_type, opts=opts, params=params, input_file_name=input_file_name
        )
    except Exception as e:
        log.warning(f"Enqueue from UI failed: {e}")
        return templates.TemplateResponse(
            "_print_result.html", {"request": request, "error": str(e)}
        )

    # Tell the job list to refresh immediately.
    resp = templates.TemplateResponse(
        "_print_result.html", {"request": request, "job": job}
    )
    resp.headers["HX-Trigger"] = "jobsChanged"
    return resp


# --------------------------------------------------------------------------- #
#  Polled fragments: job list + status
# --------------------------------------------------------------------------- #
@ui_router.get("/ui/jobs", response_class=HTMLResponse)
async def ui_jobs(
    request: Request,
    access: Annotated[bool, Depends(require_access)],
    limit: int = 20,
):
    with get_session() as session:
        stmt = select(PrintJob).order_by(PrintJob.created_at.desc()).limit(limit)
        jobs = [_job_response(j) for j in session.exec(stmt).all()]
    return templates.TemplateResponse(
        "_jobs.html", {"request": request, "jobs": jobs}
    )


@ui_router.get("/ui/homebox", response_class=HTMLResponse)
async def ui_homebox(
    request: Request, access: Annotated[bool, Depends(require_access)]
):
    if not config.homebox_configured():
        return HTMLResponse("")  # module disabled → render nothing
    ctx = _base_context(request)
    ctx["homebox_url"] = config.HOMEBOX_URL
    return templates.TemplateResponse("_homebox.html", ctx)


@ui_router.get("/ui/homebox/search", response_class=HTMLResponse)
def ui_homebox_search(
    request: Request,
    access: Annotated[bool, Depends(require_access)],
    q: str = "",
    is_location: bool = False,
):
    """Sync route (threadpool) — performs a blocking Homebox API call."""
    if not config.homebox_configured():
        return HTMLResponse("")
    from labeljetty.integrations.homebox import HomeboxClient, HomeboxError

    if not q.strip():
        return templates.TemplateResponse(
            "_homebox_results.html", {"request": request, "results": []}
        )
    try:
        client = HomeboxClient()
        entities = client.search(q, is_location=is_location)
        results = [
            {"entity": e, "web_url": client.entity_web_url(e.id)} for e in entities
        ]
    except HomeboxError as e:
        return templates.TemplateResponse(
            "_homebox_results.html", {"request": request, "error": str(e)}
        )
    return templates.TemplateResponse(
        "_homebox_results.html", {"request": request, "results": results}
    )


def _homebox_fetch_label(kind: str, entity_id: str) -> tuple[bytes, str]:
    """Fetch Homebox's own label image; returns (bytes, file-suffix)."""
    from labeljetty.integrations.homebox import HomeboxClient

    client = HomeboxClient()
    data, content_type = client.fetch_label(kind, entity_id)
    suffix = ".pdf" if "pdf" in content_type.lower() or data[:4] == b"%PDF" else ".png"
    return data, suffix


@ui_router.post("/ui/homebox/preview", response_class=HTMLResponse)
def ui_homebox_preview(
    request: Request,
    access: Annotated[bool, Depends(require_access)],
    kind: str = Form(...),
    entity_id: str = Form(...),
):
    """Preview Homebox's own label (fetched from its labelmaker API)."""
    from labeljetty.integrations.homebox import HomeboxError

    if not config.homebox_configured():
        return HTMLResponse("")
    try:
        data, suffix = _homebox_fetch_label(kind, entity_id)
    except HomeboxError as e:
        return templates.TemplateResponse(
            "_preview.html", {"request": request, "error": str(e)}
        )
    if suffix == ".pdf":
        # Render the PDF page to an image just for on-screen preview.
        import tempfile
        from labeljetty.printer.render import render_label_png_bytes

        w, h, d = _geometry(None, None, None)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(data)
            tmp_path = Path(tmp.name)
        try:
            png = render_label_png_bytes(
                "pdf", {"page": 0}, width_mm=w, height_mm=h, dpi=d,
                input_file_path=tmp_path,
            )
        finally:
            tmp_path.unlink(missing_ok=True)
        data = png
    data_uri = "data:image/png;base64," + base64.b64encode(data).decode("ascii")
    return templates.TemplateResponse(
        "_preview.html", {"request": request, "image": data_uri, "homebox": True}
    )


@ui_router.post("/ui/homebox/print", response_class=HTMLResponse)
def ui_homebox_print(
    request: Request,
    access: Annotated[bool, Depends(require_access)],
    kind: str = Form(...),
    entity_id: str = Form(...),
):
    """Print Homebox's own label: fetch it from the labelmaker API and enqueue."""
    from labeljetty.integrations.homebox import HomeboxError
    from labeljetty.web.api import _store_bytes

    if not config.homebox_configured():
        return HTMLResponse("")
    try:
        data, suffix = _homebox_fetch_label(kind, entity_id)
        filename = _store_bytes(data, suffix)
        job_type = "pdf" if suffix == ".pdf" else "png"
        params = {"page": 0} if job_type == "pdf" else {}
        job = _enqueue(job_type, params=params, input_file_name=filename)
    except (HomeboxError, Exception) as e:
        return templates.TemplateResponse(
            "_print_result.html", {"request": request, "error": str(e)}
        )
    resp = templates.TemplateResponse(
        "_print_result.html", {"request": request, "job": job}
    )
    resp.headers["HX-Trigger"] = "jobsChanged"
    return resp


@ui_router.get("/ui/homebox/setup", response_class=HTMLResponse)
async def ui_homebox_setup(
    request: Request,
    access: Annotated[bool, Depends(require_access)],
    host: Optional[str] = None,
):
    """Setup-helper page: generate the Homebox print-command script + env hints.

    ``host`` lets the user enter the printer service's address as reachable *from
    the Homebox host* (the page's own URL is often localhost/127.0.0.1 and useless
    in the generated script).
    """
    if host:
        base = host.strip().rstrip("/")
        if not base.startswith(("http://", "https://")):
            base = "http://" + base
    else:
        base = str(request.base_url).rstrip("/")
    w_mm, h_mm = config.DEFAULT_LABEL_WIDTH_MM, config.DEFAULT_LABEL_HEIGHT_MM
    dpi = config.DEFAULT_DPI
    width_px = round(w_mm / 25.4 * dpi)
    height_px = round(h_mm / 25.4 * dpi)

    token = config.API_ACCESS_TOKEN
    auth_line = f'  -H "Authorization: Bearer {token}" \\\n' if token else ""
    print_script = (
        "#!/usr/bin/env sh\n"
        "# HBOX_LABEL_MAKER_PRINT_COMMAND = /path/to/this-script.sh {{.FileName}}\n"
        f'curl -fsS -X POST "{base}/api/print/png" \\\n'
        f"{auth_line}"
        '  -F "file=@$1"\n'
    )

    ctx = _base_context(request)
    ctx.update(
        {
            "label_service_url": f"{base}/api/homebox/label",
            "print_script": print_script,
            "autoprint": config.HOMEBOX_LABEL_SERVICE_AUTOPRINT,
            "width_px": width_px,
            "height_px": height_px,
            "padding_px": max(2, width_px // 20),
            "font_size_px": max(8, height_px // 6),
            "w_mm": w_mm,
            "h_mm": h_mm,
            "dpi": dpi,
            "host_value": host or "",
            "base": base,
        }
    )
    return templates.TemplateResponse("homebox_setup.html", ctx)


@ui_router.get("/ui/status", response_class=HTMLResponse)
async def ui_status(
    request: Request, access: Annotated[bool, Depends(require_access)]
):
    worker = PrintServiceManager.get_worker_status()

    printer_reachable = False
    printer_status = None
    printer_supported = False
    printer_error = None
    con = None
    try:
        from labeljetty.printer import TSPLPrinter

        con = config.get_printer_connection()
        # Fail fast and always release — see disconnect() / printer_status notes.
        con.connect(max_retries=1)
        printer = TSPLPrinter(
            connection=con,
            label_width_mm=config.DEFAULT_LABEL_WIDTH_MM,
            label_height_mm=config.DEFAULT_LABEL_HEIGHT_MM,
            dpi=config.DEFAULT_DPI,
        )
        msg = printer.get_status()
        printer_reachable = True
        printer_supported = msg is not None
        printer_status = msg
    except Exception as e:
        printer_error = str(e)
    finally:
        if con is not None:
            con.disconnect()

    return templates.TemplateResponse(
        "_status.html",
        {
            "request": request,
            "worker": worker,
            "printer_reachable": printer_reachable,
            "printer_supported": printer_supported,
            "printer_status": printer_status,
            "printer_error": printer_error,
        },
    )
