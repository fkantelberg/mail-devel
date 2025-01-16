[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
![PyPI - Python Version](https://img.shields.io/pypi/pyversions/mail-devel)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

# mail-devel

This tool combines an in-memory SMTP mail-sink with an IMAP server. All mails coming over SMTP
are stored in the IMAP inbox. This can be used to test outgoing and incoming mail configurations.
Built on top of [aiosmtpd](https://github.com/aio-libs/aiosmtpd) and [pymap](https://github.com/icgood/pymap/).

The frontend is minimally handling the content of the mailbox. Please connect a proper mail client
like Thunderbird for more advanced usage.

DO NOT USE FOR PRODUCTION.

## Features

- Receive, send mails, and reply to mails
- Generate randomized mails using the HTTP frontend
- Manage IMAP flags and automated flagging
- Minimal HTTP frontend to support the basic testing
- SMTP auto respond feature for automatic testing (see `--smtp-responder`)
- Single or multi mail account mode (see [configuration](#configuration))

## Usage

### Docker

```bash
docker run -p 4080:4080 -p 4025:4025 -p 4143:4143 --rm fkantelberg/mail-devel --password abc
```

### Docker Compose

The following example assumes that the tool is run in a docker compose network as one of
the services and only need to publish the HTTP port.

- Minimally define password in `.env` with `MAILSINK_PASSWORD`
- Additionally define port in `.env` with `MAILSINK_HTTP`

Following the section from the `docker-compose.yaml`:

```yaml
services:
  mailsink:
    image: fkantelberg/mail-devel:${MAILSINK_TAG:-latest}
    environment:
      MAIL_USER: ${MAILSINK_USER:-test@example.org}
    command: [--password, $MAILSINK_PASSWORD, --smtp-flagged-seen]
    ports:
      - ${MAILSINK_HTTP:-127.0.0.1:4080}:4080
      # If you want to connect a normal mail client via SMTP and IMAP
      # - ${MAILSINK_SMTP:-127.0.0.1:4025}:4025
      # - ${MAILSINK_IMAP:-127.0.0.1:4143}:4143
```

### Python

```bash
$ pip install mail-devel
$ mail_devel --password secret
```

## Configuration

Please use `--help` for a more complete overview of the configurations.

- `--password`: The password for SMTP and IMAP
- `--auth-required`: Disables SMTP without authentication
- `--flagged-seen`: If set incoming mails are automatically flagged as seen/read. If you only want to flag mails coming via SMTP as seen use `--smtp-flagged-seen`
- `--multi-user`: Switches from single user to multi user mode

  - **Single User Mode:** All mails are collected in a single mailbox which belongs to the defined user.

  - **Multi User Mode:** The mails are collected in the specific mailboxes for each receiver of the messages using the `to`, `cc`, and `bcc` mail headers.

- `--auto-responder`: Automatically respond to the mails coming in via SMTP

  - `--auto-responder reply_once`: Reply once per mail thread
  - `--auto-responder reply_always`: Always reply to incoming mails
  - `--auto-responder path/to/script.py`: Custom auto responder. See [the examples](https://github.com/fkantelberg/mail-devel/blob/master/src/mail_devel/automation)

## Supported protocols for mails

- SMTP (optionally with STARTTLS)
- SMTPS
- IMAP (optionally with STARTTLS)

## References

- [Github](https://github.com/fkantelberg/mail-devel)
- [PyPI Package](https://pypi.org/project/mail-devel)
