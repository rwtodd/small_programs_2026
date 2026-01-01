#!/bin/bash

# MediaWiki images incremental backup script
# Creates ONE ZIP containing all files added since the last timestamp
# Run from the MediaWiki root directory (where 'images' folder is)

IMAGES_DIR="images"
INCREMENTAL_DATE=$(date +%Y%m%d)
TIMESTAMP_FILE="rwt-backup.timestamp"  # We'll create/update this
INCREMENTAL_ZIP="../images_incremental_${INCREMENTAL_DATE}.zip"

# Check if we have a timestamp from the last full backup
if [ ! -f "$TIMESTAMP_FILE" ]; then
    echo "Error: Timestamp file '$TIMESTAMP_FILE' not found!"
    echo "Create it by running: touch -t 202601010000 $TIMESTAMP_FILE  # adjust to your full backup date"
    exit 1
fi

echo "Creating incremental backup for files newer than $(date -r "$TIMESTAMP_FILE")"
echo "Scanning $IMAGES_DIR for new files..."
echo

# Temporary file list
FILE_LIST=$(mktemp)

# Find all regular files newer than the timestamp, preserving full paths
find "$IMAGES_DIR" -type f -newer "$TIMESTAMP_FILE" > "$FILE_LIST"

# Count them
NEW_COUNT=$(wc -l < "$FILE_LIST")

if [ "$NEW_COUNT" -eq 0 ]; then
    echo "No new files found since last full backup. Nothing to do."
    rm "$FILE_LIST"
    exit 0
fi

echo "Found $NEW_COUNT new files. Creating incremental archive: $INCREMENTAL_ZIP"

# Create ZIP with full path structure preserved
# -@ reads filenames from stdin
zip -r -9 -y "$INCREMENTAL_ZIP" -@ < "$FILE_LIST"

if [ $? -eq 0 ]; then
    echo
    echo "Incremental backup complete: $INCREMENTAL_ZIP"
    echo "   Contains $NEW_COUNT new files"
    echo "   Size: $(du -h "$INCREMENTAL_ZIP" | cut -f1)"
else
    echo "Error creating ZIP file!"
    rm "$FILE_LIST"
    exit 1
fi

# Clean up
rm "$FILE_LIST"

# Optional: Update timestamp to now (only if you want future incrementals from THIS point)
# Comment this out if you want to keep accumulating against the original full backup
touch "$TIMESTAMP_FILE"

echo
echo "Note: Timestamp is now $(date -r "$TIMESTAMP_FILE")"
echo "      Run your full backup script again when ready for a new baseline."

