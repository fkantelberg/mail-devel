import logging
import os
import ssl
import sys
from typing import List

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


def configure_logging(level: str, log_file: str = None) -> None:
    """Configure the logging"""
    level = LOG_LEVELS.get(level.lower(), logging.DEBUG)

    log = logging.getLogger()
    log.setLevel(level)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter(LOG_FORMAT, style="{"))
    log.addHandler(handler)

    if log_file:
        handler = logging.FileHandler(log_file)
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(logging.Formatter(LOG_FORMAT, style="{"))
        log.addHandler(handler)


def generate_ssl_context(
    *,
    cert: str = None,
    key: str = None,
    ca: str = None,
    crl: str = None,
    ciphers: List[str] = None,
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

    ciphers = sorted(c["name"] for c in ctx.get_ciphers())
    _logger.info("Ciphers: %s", ", ".join(ciphers))

    return ctx


def valid_file(path: str) -> str:
    """Check if a file exists and return the absolute path otherwise raise an
    error. This function is used for the argument parsing"""
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        raise FileNotFoundError()
    return path
