#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Xiaoyou Core Application Entry Point.
Now refactored to use core.server module.
"""

import sys
import os

# Ensure the project root is in the python path
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.append(project_root)

try:
    from core.server.server import run_server
except ImportError as e:
    print(f"Error importing core modules: {e}")
    sys.exit(1)

if __name__ == "__main__":
    run_server()
