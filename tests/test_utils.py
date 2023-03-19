import logging
import ssl
import subprocess

import pytest
from mail_devel import utils

CA_CERT = "pki/ca.pem"
SERVER_CERT = "pki/server.pem"
SERVER_KEY = "pki/server.key"
CRL = "pki/crl.pem"

with subprocess.Popen(["./certs.sh", "server"], stdin=subprocess.PIPE) as proc:
    proc.communicate(b"y\n" * 80)


def test_generate_ssl_context():
    server = utils.generate_ssl_context(
        cert=SERVER_CERT,
        key=SERVER_KEY,
        ca=CA_CERT,
        crl=CRL,
    )

    assert isinstance(server, ssl.SSLContext)
    assert len(server.get_ciphers())


def test_configure_logging():
    utils.configure_logging("INFO", None)
    log = logging.getLogger()
    list(map(log.removeHandler, log.handlers))

    utils.configure_logging("DEBUG", "test.log")
    list(map(log.removeHandler, log.handlers))


def test_valid_file():
    with pytest.raises(FileNotFoundError):
        assert utils.valid_file(__file__ + "a")
    assert utils.valid_file(__file__) == __file__
