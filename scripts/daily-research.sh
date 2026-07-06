#!/usr/bin/env bash
# Optional daily researcher run. Writes data/suggestions.json, which the
# local page reads. No always-on server involved.
#
# cron (Linux):
#   crontab -e
#   30 7 * * * /path/to/sunny/scripts/daily-research.sh >> /tmp/sunny-research.log 2>&1
#
# launchd (macOS): create ~/Library/LaunchAgents/com.sunny.research.plist
# with a ProgramArguments entry pointing at this script and a
# StartCalendarInterval of Hour=7, Minute=30, then:
#   launchctl load ~/Library/LaunchAgents/com.sunny.research.plist

set -euo pipefail
cd "$(dirname "$0")/.."
exec python3 -m pipeline research
