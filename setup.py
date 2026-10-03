#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from pathlib import Path

from setuptools import find_packages, setup

from src.wireviz import APP_URL, CMD_NAME, __version__

README_PATH = Path(__file__).parent / "docs" / "README.md"

setup(
    name=CMD_NAME,
    version=__version__,
    author="Daniel Rojas",
    # author_email='',
    description="Easily document cables and wiring harnesses",
    long_description=README_PATH.read_text(encoding="utf-8"),
    long_description_content_type="text/markdown",
    python_requires=">=3.9",
    install_requires=[
        "click>=8.0",
        "pyyaml>=5.4",
        "pillow>=10.3",  # CVE-2023-4863, CVE-2023-44271, CVE-2024-28219
        "graphviz>=0.20",
    ],
    extras_require={
        # print-ready sheet PDF (-f D); also needs the Pango system library
        # (WeasyPrint 70 needs Python 3.10 or later)
        "pdf": ["weasyprint>=70; python_version >= '3.10'"],
    },
    license="GPLv3",
    keywords="cable connector hardware harness wiring wiring-diagram wiring-harness",
    url=APP_URL,
    package_dir={"": "src"},
    package_data={CMD_NAME: ["templates/*.html"]},
    packages=find_packages("src"),
    entry_points={
        "console_scripts": [
            "wireviz=wireviz.wv_cli:wireviz",
        ],
    },
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Environment :: Console",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
        "Programming Language :: Python :: 3.14",
        "Topic :: Utilities",
        "License :: OSI Approved :: GNU General Public License v3 (GPLv3)",
    ],
)
