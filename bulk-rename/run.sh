#!/bin/bash
# Wrapper script to run bulk-rename via bundler
# Usage: ./run.sh [args]
set -e
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
BUNDLE_GEMFILE="$DIR/Gemfile" exec bundle exec "$DIR/bin/bulk-rename" "$@"
