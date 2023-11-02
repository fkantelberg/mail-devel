ARG PYTHON_VERSION=3.11

FROM python:${PYTHON_VERSION}-alpine

RUN pip install -U pip mail-devel

EXPOSE 4025 4080 4143 4465

ENTRYPOINT ["mail_devel"]
CMD ["--help"]
