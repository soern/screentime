#!/usr/bin/env python3
"""
Setup script for screentime.

Copyright (C) 2025  Sören Heisrath <screentime at projects dot heisrath dot org>

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""
from setuptools import setup, find_packages
from pathlib import Path

# Read README for long description
readme_file = Path(__file__).parent / "README.md"
long_description = ""
if readme_file.exists():
    with open(readme_file, 'r', encoding='utf-8') as f:
        long_description = f.read()

setup(
    name="screentime",
    version="1.0.0",
    description="Screen time tracker for X11 environments",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Sören Heisrath",
    author_email="screentime at projects dot heisrath dot org",
    python_requires=">=3.6",
    packages=find_packages(exclude=["tests", "tests.*"]),
    py_modules=["screentime", "daemon", "logging_setup"],
    include_package_data=True,
    package_data={
        "": ["config/*.json"],
    },
    data_files=[
        ("share/screentime/config", ["config/default_config.json"]),
    ],
    install_requires=[
        "python-xlib",
    ],
    entry_points={
        "console_scripts": [
            "screentime=screentime:main",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: End Users/Desktop",
        "License :: OSI Approved :: GNU General Public License v3 (GPLv3)",
        "Operating System :: POSIX :: Linux",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Topic :: System :: Monitoring",
    ],
)

