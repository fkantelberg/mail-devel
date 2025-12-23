import logging
import os
import ssl
import sys
from email.message import Message

VERSION = "0.15.1"

DEFAULT_LOG_LEVEL = "info"
LOG_FORMAT = "{asctime} [{levelname:^8}] {message}"

LOG_LEVELS = {
    "critical": logging.CRITICAL,
    "debug": logging.DEBUG,
    "error": logging.ERROR,
    "info": logging.INFO,
    "warn": logging.WARN,
    "warning": logging.WARNING,
}

_logger = logging.getLogger(__name__)


def configure_logging(level_name: str, log_file: str | None = None) -> None:
    """Configure the logging"""
    level = LOG_LEVELS.get(level_name.lower(), logging.DEBUG)

    log = logging.getLogger()
    log.setLevel(level)

    formatter = logging.Formatter(LOG_FORMAT, style="{")

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setLevel(logging.DEBUG)
    stream_handler.setFormatter(formatter)
    log.addHandler(stream_handler)

    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        log.addHandler(file_handler)


def generate_ssl_context(
    *,
    cert: str | None = None,
    key: str | None = None,
    ca: str | None = None,
    crl: str | None = None,
    ciphers: str | None = None,
    check_hostname: bool = False,
) -> ssl.SSLContext:
    """Generate a SSL context for the tunnel"""

    # Set the protocol and create the basic context
    proto = ssl.PROTOCOL_TLS_SERVER
    ctx = ssl.SSLContext(proto)

    ctx.check_hostname = check_hostname
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2

    # Prevent the reuse of parameters
    ctx.options |= ssl.OP_SINGLE_DH_USE | ssl.OP_SINGLE_ECDH_USE

    # Load a certificate and key for the connection
    if cert:
        ctx.load_cert_chain(cert, keyfile=key)

    # Load the CA to verify the other side
    if ca:
        ctx.verify_mode = ssl.CERT_REQUIRED
        ctx.load_verify_locations(cafile=ca)

    if crl:
        ctx.verify_flags |= ssl.VERIFY_CRL_CHECK_LEAF
        ctx.load_verify_locations(cafile=crl)

    # Set possible ciphers to use
    if ciphers:
        ctx.set_ciphers(ciphers)

    # Output debugging
    _logger.info("CA usage: %s", bool(ca))
    _logger.info("Certificate: %s", bool(cert))
    _logger.info("Hostname verification: %s", bool(check_hostname))
    # pylint: disable=no-member
    _logger.info("Minimal TLS Version: %s", ctx.minimum_version.name)

    avail_ciphers = sorted(c["name"] for c in ctx.get_ciphers())
    _logger.info("Ciphers: %s", ", ".join(avail_ciphers))

    return ctx


def convert_size(x: str) -> int:
    x = x.upper()
    for c, m in {"K": 1 << 10, "M": 1 << 20, "G": 1 << 30}.items():
        if x.endswith(c):
            return int(m * float(x[:-1]))
    return int(float(x))


def extract_payload(message: Message, decode: bool) -> str:
    if decode:
        content = message.get_payload(decode=True)
        return content.decode() if isinstance(content, bytes) else ""

    content = message.get_payload(decode=False)
    return content if isinstance(content, str) else ""


def str2bool(x: str | None) -> bool:
    return (x or "").lower() in ("yes", "y", "on", "1")


def valid_file(path: str, is_directory: bool = False) -> str:
    """Check if a file exists and return the absolute path otherwise raise an
    error. This function is used for the argument parsing"""
    path = os.path.abspath(path)
    if is_directory and not os.path.isdir(path):
        raise NotADirectoryError()
    if not is_directory and not os.path.isfile(path):
        raise FileNotFoundError()
    return path
