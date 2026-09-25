#!/bin/sh
exec env PYTHONPATH=/app/share/deluxe-sticky-notes python3 -m stickynotes "$@"
