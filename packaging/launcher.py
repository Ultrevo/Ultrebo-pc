# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Ultrevo. See LICENSE and NOTICE.
"""Entry point used by PyInstaller."""
import sys

from ultrebo.app import main

if __name__ == "__main__":
    sys.exit(main())
