#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Entry point for building the BlueArch CLI binary.
Used by PyInstaller (Linux) and Nuitka (macOS).

Pre-imports core dependencies to ensure they're packaged in the binary,
even when they're conditionally imported at runtime.
"""

import sys
import os

# Add src/api to Python path
project_root = os.path.dirname(os.path.abspath(__file__))
api_root = os.path.join(project_root, "src", "api")
if api_root not in sys.path:
    sys.path.insert(0, api_root)

# Pre-import dependencies that need explicit packaging
try:
    import sqlalchemy
    import diskcache
    import rich
    import typer
    import boto3
    import pynamodb  # Keep during DynamoDB transition
    import fastapi
    # Belt-and-suspenders: ensure PyInstaller's static analysis sees these
    # even if their import sites are conditional/lazy.
    import fernet
    import termcolor
    import art
    import cachetools
except ImportError:
    pass

# Import and run the CLI
from bluearch import run

if __name__ == "__main__":
    run()
