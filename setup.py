import os
from glob import glob

from setuptools import find_packages, setup


def read(fname):
    with open(os.path.join(os.path.dirname(__file__), fname), encoding="utf-8") as f:
        return f.read()


static_files = []
for pat in ("css", "js", "html"):
    static_files.extend(glob(f"src/mail_devel/resources/*.{pat}"))

setup(
    name="mail-devel",
    version="0.1.0",
    author="Florian Kantelberg",
    author_email="florian.kantelberg@mailbox.org",
    description="IMAP and SMTP in memory test server",
    long_description=read("README.md"),
    long_description_content_type="text/markdown",
    license="MIT",
    keywords="imap smtp development",
    url="https://github.com/fkantelberg/mail-devel",
    packages=find_packages("src"),
    package_dir={"": "src"},
    data_files=static_files,
    include_package_data=True,
    entry_points={"console_scripts": ["mail_devel = mail_devel.__main__:main"]},
    install_requires=[
        "aiohttp",
        "aiohttp-jinja2",
        "aiosmtpd",
        "pymap",
    ],
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.7",
)
