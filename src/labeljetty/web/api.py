from typing import Annotated, List, Literal, Optional
from pathlib import Path
import uuid

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Path as PathParam,
    Query,
    Response,
    UploadFile,
    status,
)
from pydantic import BaseModel, Field

from labeljetty.service.worker import PrintServiceManager, WorkerStatusResponse
from labeljetty.core.db import get_session, PrintJob
from labeljetty.printer import JobType, TSPLPrinter, TSPLPrinterStatusMessage
from labeljetty.printer.render import render_label_png_bytes
from labeljetty.web.auth import require_access
from labeljetty.config import Config
from labeljetty.core.logging import get_logger
from sqlmodel import select

config = Config()
log = get_logger()


fast_api_router: APIRouter = APIRouter()


# --------------------------------------------------------------------------- #
#  Request bodies
# --------------------------------------------------------------------------- #
class LabelOptions(BaseModel):
    label_width_mm: Optional[int] = Field(
        default=None, description="Override label width in mm (else server default)."
    )
    label_height_mm: Optional[int] = Field(
        default=None, description="Override label height in mm (else server default)."
    )
    dpi: Optional[int] = Field(default=None, description="Override DPI.")
    copies: int = Field(default=1, ge=1)


class TextPrintRequest(LabelOptions):
    text: str
    font_size: Optional[int] = Field(
        default=None, description="Fixed font size in px; auto-fits the label if omitted."
    )
    fit: Literal["fill", "width"] = Field(
        default="fill",
        description="Auto-fit mode when font_size is omitted: 'fill' grows to fill "
        "the label; 'width' sizes to the label width keeping line breaks.",
    )


class MarkdownPrintRequest(LabelOptions):
    text: str
    fit: Literal["fill", "width"] = Field(
        default="fill", description="Auto-fit mode (see /print/text)."
    )


class BarcodePrintRequest(LabelOptions):
    data: str
    barcode_type: str = "128"
    text: Optional[str] = Field(
        default=None, description="Optional human text printed above the barcode."
    )


class QRCodePrintRequest(LabelOptions):
    data: str
    ecc_level: str = "M"
    text: Optional[str] = Field(
        default=None, description="Optional human text printed alongside the QR code."
    )


# --------------------------------------------------------------------------- #
#  Helpers
# --------------------------------------------------------------------------- #
def _require_worker_running() -> None:
    worker_status = PrintServiceManager.get_worker_status()
    if worker_status.status != "running":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Printing service not running (status: {worker_status.status}).",
        )


def _store_bytes(data: bytes, suffix: str) -> str:
    """Persist raw bytes to the image storage dir, return the generated filename."""
    storage_dir = Path(config.IMAGE_STORAGE_DIRECTORY)
    storage_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4()}{suffix}"
    (storage_dir / filename).write_bytes(data)
    return filename


def _store_upload(upload: UploadFile, suffix: str) -> str:
    """Persist an uploaded file to the image storage dir, return its filename."""
    return _store_bytes(upload.file.read(), suffix)


def _enqueue(
    job_type: JobType,
    *,
    opts: Optional[LabelOptions] = None,
    params: Optional[dict] = None,
    input_file_name: Optional[str] = None,
) -> PrintJob:
    """Create + persist a print job; the worker picks it up from the DB."""
    _require_worker_running()
    job = PrintJob(
        job_type=job_type,
        params=params or {},
        input_file_name=input_file_name,
        label_width_mm=opts.label_width_mm if opts else None,
        label_height_mm=opts.label_height_mm if opts else None,
        dpi=opts.dpi if opts else None,
        copies=opts.copies if opts else 1,
    )
    with get_session() as session:
        session.add(job)
        session.commit()
        session.refresh(job)
    return job


# --------------------------------------------------------------------------- #
#  Print endpoints
# --------------------------------------------------------------------------- #
@fast_api_router.post("/print/png", tags=["Print"])
async def print_png(
    access: Annotated[bool, Depends(require_access)],
    file: Annotated[UploadFile, File()],
    fit: Annotated[Literal["fit", "fill", "stretch", "original"], Form()] = "fit",
    label_width_mm: Annotated[Optional[int], Form()] = None,
    label_height_mm: Annotated[Optional[int], Form()] = None,
    dpi: Annotated[Optional[int], Form()] = None,
    copies: Annotated[int, Form()] = 1,
) -> PrintJob:
    filename = _store_upload(file, ".png")
    opts = LabelOptions(
        label_width_mm=label_width_mm,
        label_height_mm=label_height_mm,
        dpi=dpi,
        copies=copies,
    )
    return _enqueue("png", opts=opts, params={"fit": fit}, input_file_name=filename)


@fast_api_router.post("/print/pdf", tags=["Print"])
async def print_pdf(
    access: Annotated[bool, Depends(require_access)],
    file: Annotated[UploadFile, File()],
    page: Annotated[str, Form()] = "0",
    fit: Annotated[Literal["fit", "fill", "stretch", "original"], Form()] = "fit",
    label_width_mm: Annotated[Optional[int], Form()] = None,
    label_height_mm: Annotated[Optional[int], Form()] = None,
    dpi: Annotated[Optional[int], Form()] = None,
    copies: Annotated[int, Form()] = 1,
) -> PrintJob:
    filename = _store_upload(file, ".pdf")
    opts = LabelOptions(
        label_width_mm=label_width_mm,
        label_height_mm=label_height_mm,
        dpi=dpi,
        copies=copies,
    )
    # "all" or a page index
    page_param = page if page == "all" else int(page)
    return _enqueue(
        "pdf", opts=opts, input_file_name=filename, params={"page": page_param, "fit": fit}
    )


@fast_api_router.post("/print/text", tags=["Print"])
async def print_text(
    access: Annotated[bool, Depends(require_access)],
    body: TextPrintRequest,
) -> PrintJob:
    return _enqueue(
        "text",
        opts=body,
        params={"text": body.text, "font_size": body.font_size, "fit": body.fit},
    )


@fast_api_router.post("/print/markdown", tags=["Print"])
async def print_markdown(
    access: Annotated[bool, Depends(require_access)],
    body: MarkdownPrintRequest,
) -> PrintJob:
    return _enqueue(
        "markdown", opts=body, params={"text": body.text, "fit": body.fit}
    )


@fast_api_router.post("/print/barcode", tags=["Print"])
async def print_barcode(
    access: Annotated[bool, Depends(require_access)],
    body: BarcodePrintRequest,
) -> PrintJob:
    return _enqueue(
        "barcode",
        opts=body,
        params={
            "data": body.data,
            "barcode_type": body.barcode_type,
            "text": body.text,
        },
    )


@fast_api_router.post("/print/qrcode", tags=["Print"])
async def print_qrcode(
    access: Annotated[bool, Depends(require_access)],
    body: QRCodePrintRequest,
) -> PrintJob:
    return _enqueue(
        "qrcode",
        opts=body,
        params={
            "data": body.data,
            "ecc_level": body.ecc_level,
            "text": body.text,
        },
    )


# --------------------------------------------------------------------------- #
#  Job status
# --------------------------------------------------------------------------- #
class JobStatusResponse(BaseModel):
    job: PrintJob
    status: str


def _job_response(job: PrintJob) -> JobStatusResponse:
    return JobStatusResponse(job=job, status=job.get_status())


@fast_api_router.get("/jobs", tags=["Jobs"])
async def list_jobs(
    access: Annotated[bool, Depends(require_access)],
    limit: int = 100,
) -> List[JobStatusResponse]:
    with get_session() as session:
        stmt = select(PrintJob).order_by(PrintJob.created_at.desc()).limit(limit)
        jobs = session.exec(stmt).all()
        return [_job_response(j) for j in jobs]


@fast_api_router.get("/jobs/{job_id}", tags=["Jobs"])
async def get_job(
    access: Annotated[bool, Depends(require_access)],
    job_id: Annotated[uuid.UUID, PathParam()],
) -> JobStatusResponse:
    with get_session() as session:
        job = session.get(PrintJob, job_id)
        if job is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Job not found"
            )
        return _job_response(job)


# --------------------------------------------------------------------------- #
#  Printer / worker status
# --------------------------------------------------------------------------- #
@fast_api_router.get("/worker/status", tags=["Status"])
async def worker_status(
    access: Annotated[bool, Depends(require_access)],
) -> WorkerStatusResponse:
    return PrintServiceManager.get_worker_status()


class PrinterStatusResponse(BaseModel):
    reachable: bool = Field(description="Whether the printer's USB device was opened.")
    status_supported: bool = Field(
        description="Whether the printer answered the status query."
    )
    status: Optional[TSPLPrinterStatusMessage] = Field(
        default=None,
        description="Decoded status, or null if the printer does not report it.",
    )


@fast_api_router.get("/printer/status", tags=["Status"])
async def printer_status(
    access: Annotated[bool, Depends(require_access)],
) -> PrinterStatusResponse:
    con = None
    try:
        con = config.get_printer_connection()
        # Fail fast (max_retries=1): if the worker is mid-print and holds the
        # device, don't loop/flood — just report it as currently unreachable.
        con.connect(max_retries=1)
        printer = TSPLPrinter(
            connection=con,
            label_width_mm=config.DEFAULT_LABEL_WIDTH_MM,
            label_height_mm=config.DEFAULT_LABEL_HEIGHT_MM,
            dpi=config.DEFAULT_DPI,
        )
        msg = printer.get_status()
        return PrinterStatusResponse(
            reachable=True, status_supported=msg is not None, status=msg
        )
    except Exception as e:
        # Could not even open/talk to the device.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Could not reach printer: {e}",
        )
    finally:
        if con is not None:
            con.disconnect()


# --------------------------------------------------------------------------- #
#  Homebox push: external label service
# --------------------------------------------------------------------------- #
#  Homebox can delegate label *rendering* to an HTTP service via
#  HBOX_LABEL_MAKER_LABEL_SERVICE_URL. It issues a GET with TitleText /
#  DescriptionText / URL / Width / Height / Dpi / … and expects an image/* back.
#  We render the label with our own engine (tuned to our configured stock — the
#  same QR+text renderer as the pull module) and, by default, enqueue the print
#  as a side effect, then return the PNG.
#
#  NOTE(auth): Homebox fetches this URL with no custom headers, so it cannot
#  send a bearer token — this endpoint is intentionally outside the auth seam.
#  The planned auth session should add an optional URL-embedded token here.
@fast_api_router.get("/homebox/label", tags=["Homebox"])
async def homebox_label_service(
    TitleText: str = Query(default=""),
    DescriptionText: str = Query(default=""),
    URL: str = Query(default=""),
    # Homebox also sends Width/Height/Dpi (pixels); we render to OUR stock and
    # accept them only as informational — ignored on purpose for consistent output.
    Width: Optional[int] = Query(default=None),
    Height: Optional[int] = Query(default=None),
    Dpi: Optional[int] = Query(default=None),
):
    if not config.HOMEBOX_ENABLED:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    caption = TitleText
    if DescriptionText:
        caption = f"{TitleText} · {DescriptionText}" if TitleText else DescriptionText
    params = {
        "data": URL or TitleText or "",
        "text": caption or None,
        "ecc_level": "M",
    }

    png = render_label_png_bytes(
        "qrcode",
        params,
        width_mm=config.DEFAULT_LABEL_WIDTH_MM,
        height_mm=config.DEFAULT_LABEL_HEIGHT_MM,
        dpi=config.DEFAULT_DPI,
    )

    if config.HOMEBOX_LABEL_SERVICE_AUTOPRINT:
        # Side-effect print; never let a queue/print problem fail the image response.
        try:
            _enqueue("qrcode", params=params)
        except Exception as e:
            log.warning(f"Homebox label-service autoprint failed to enqueue: {e}")

    return Response(content=png, media_type="image/png")
