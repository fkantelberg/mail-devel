FROM python:3.11-alpine

RUN pip install -U pip mail-devel

EXPOSE 4025 4080 4143 4465

ENTRYPOINT ["mail_devel"]
CMD ["--help"]
