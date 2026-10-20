import logging
import ssl
import subprocess

import pytest

from mail_devel import utils


def test_generate_ssl_context() -> None:
    with subprocess.Popen(["./certs.sh", "server"], stdin=subprocess.PIPE) as proc:
        proc.communicate(b"y\n" * 80)

    server = utils.generate_ssl_context(
        cert="pki/server.pem",
        key="pki/server.key",
        ca="pki/ca.pem",
        crl="pki/crl.pem",
    )

    assert isinstance(server, ssl.SSLContext)
    assert len(server.get_ciphers())


def test_configure_logging() -> None:
    utils.configure_logging("INFO", None)
    log = logging.getLogger()
    list(map(log.removeHandler, log.handlers))

    utils.configure_logging("DEBUG", "test.log")
    list(map(log.removeHandler, log.handlers))


def test_convert_size() -> None:
    assert utils.convert_size("1.5") == 1
    assert utils.convert_size("1.5K") == 1536


def test_valid_file() -> None:
    with pytest.raises(FileNotFoundError):
        assert utils.valid_file(__file__ + "a")
    assert utils.valid_file(__file__) == __file__
