#!/bin/sh
exec env PYTHONPATH=/app/share/sticky-notes python3 -m stickynotes "$@"
