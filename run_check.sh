#!/bin/bash
# Wrapper launchd/cron calls -- activates the venv then runs the checker.
cd "$(dirname "$0")"
source venv/bin/activate
python check_availability.py
