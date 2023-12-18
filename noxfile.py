import nox


@nox.session()
def clean(session):
    session.install("coverage")
    session.run("coverage", "erase")


@nox.session()
def py3(session):
    session.install(
        "pytest",
        "pytest-asyncio",
        "pytest-cov",
        "pytest-xdist",
        "pytest-timeout",
        "coverage",
    )
    session.install(".")
    session.run(
        "pytest",
        "-n=5",
        "--cov-append",
        "--cov=src/mail_devel",
        "--asyncio-mode=auto",
        "--timeout=5",
    )


@nox.session()
def report(session):
    session.install("coverage")
    session.run("coverage", "html")
    session.run("coverage", "report", "--fail-under=80")
