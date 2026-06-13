from typing import cast
from pathlib import Path
import uvicorn
import asyncio
from uvicorn.config import LOGGING_CONFIG
from uvicorn.config import LifespanType

from labeljetty.web.app import FastApiAppContainer
from labeljetty.service.worker import PrintServiceManager


def run():
    from labeljetty.config import Config
    from labeljetty.core.logging import get_logger, get_uvicorn_loglevel

    config = Config()
    log = get_logger()
    log.info(f"LOG_LEVEL: {config.LOG_LEVEL}")
    log.info(f"UVICORN_LOG_LEVEL: {get_uvicorn_loglevel()}")
    log.info(f"Create image storage directory at '{config.IMAGE_STORAGE_DIRECTORY}'")
    log.info(f"USB Printer at {config.PRINTER_USB} if not exists")
    Path(config.IMAGE_STORAGE_DIRECTORY).mkdir(parents=True, exist_ok=True)

    event_loop = asyncio.get_event_loop()
    uvicorn_log_config = LOGGING_CONFIG
    fast_api_container = FastApiAppContainer()
    uvicorn_config = uvicorn.Config(
        app=fast_api_container.app,
        host=config.SERVER_LISTENING_HOST,
        port=config.SERVER_LISTENING_PORT,
        log_level=get_uvicorn_loglevel(),
        log_config=uvicorn_log_config,
        loop=event_loop,
        lifespan=cast(LifespanType, "on"),
    )
    uvicorn_server = uvicorn.Server(config=uvicorn_config)
    print_service = PrintServiceManager()
    fast_api_container.add_startup_callback(print_service.start)
    fast_api_container.add_shutdown_callback(print_service.shutdown)
    try:
        log.debug("Start uvicorn server...")
        event_loop.run_until_complete(uvicorn_server.serve())
    except (KeyboardInterrupt, Exception) as e:
        if isinstance(e, KeyboardInterrupt):
            log.info("KeyboardInterrupt shutdown...")
        if isinstance(e, Exception):
            log.info("Panic shutdown...")
        if isinstance(e, Exception):
            raise e


if __name__ == "__main__":
    run()
