import logging
import sys
import os
from typing import Literal

import structlog
from structlog.dev import ConsoleRenderer
from structlog.processors import JSONRenderer


from .read_config import get_log_options


def configure_logger(
    filename: str = "application.log",
    logging_level: (
        int | Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL", "FATAL"]
    ) = logging.INFO,
    enable_stdout: bool = True,
    enable_fileout: bool = True,
):
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M.%S", utc=True),
            structlog.processors.UnicodeDecoder(),
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        cache_logger_on_first_use=True,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
    )
    handler_stdout = logging.StreamHandler(sys.stdout)
    handler_stdout.setFormatter(
        structlog.stdlib.ProcessorFormatter(processor=ConsoleRenderer())
    )
    logoptions = get_log_options()
    if logoptions.directory_path:
        file_path = os.path.join(logoptions.directory_path, filename)
    else:
        file_path = filename
    handler_file = logging.FileHandler(file_path)
    handler_file.setFormatter(
        structlog.stdlib.ProcessorFormatter(processor=JSONRenderer())
    )

    root_logger = logging.getLogger()
    if enable_stdout:
        root_logger.addHandler(handler_stdout)
    if enable_fileout:
        root_logger.addHandler(handler_file)
    match logging_level:
        case int():
            root_logger.setLevel(logging_level)
        case "DEBUG":
            root_logger.setLevel(logging.DEBUG)
        case "INFO":
            root_logger.setLevel(logging.INFO)
        case "WARNING":
            root_logger.setLevel(logging.WARNING)
        case "ERROR":
            root_logger.setLevel(logging.ERROR)
        case "CRITICAL", "FATAL":
            root_logger.setLevel(logging.CRITICAL)
        case _:
            root_logger.setLevel(logging.INFO)
