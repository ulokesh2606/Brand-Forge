#!/usr/bin/env bash
# exit on error
set -o errexit

# Install python dependencies
pip install -r requirements.txt

# Install Playwright browser and system-level dependencies for crawl4ai
# This is mandatory for crawl4ai to work on Render/Linux
python -m playwright install --with-deps chromium
