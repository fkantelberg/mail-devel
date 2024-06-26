import nox


@nox.session()
def clean(session: nox.Session) -> None:
    session.install("coverage")
    session.run("coverage", "erase")


@nox.session()
def py3(session: nox.Session) -> None:
    session.install(
        "-e",
        ".",
        "pytest",
        "pytest-asyncio",
        "pytest-cov",
        "pytest-xdist",
        "pytest-timeout",
        "coverage",
    )
    session.run(
        "pytest",
        "-n=5",
        "--cov=src/mail_devel",
        "--cov-append",
        "--asyncio-mode=auto",
        "--timeout=5",
    )


@nox.session()
def report(session: nox.Session) -> None:
    session.install("coverage")
    session.run("coverage", "html")
    session.run("coverage", "report", "--fail-under=80")
