[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
![PyPI - Python Version](https://img.shields.io/pypi/pyversions/mail-devel)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

# mail-devel

This tool combines an in-memory SMTP mail-sink with an IMAP server. All mails coming over SMTP
are stored in the IMAP inbox. This can be used to test outgoing and incoming mail configurations.
Built on top of [aiosmtpd](https://github.com/aio-libs/aiosmtpd) and [pymap](https://github.com/icgood/pymap/).

The frontend is minimally showing the content of the mailbox. Please connect a proper mail client
like Thunderbird for more advanced usage.

DO NOT USE FOR PRODUCTION.

### Supported

- SMTP (optionally with STARTTLS)
- SMTPS
- IMAP (optionally with STARTTLS)
