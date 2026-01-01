#!/bin/bash

# MediaWiki non-images backup script - SAFE version with .htaccess inclusion
# Excludes ONLY the root ./images/ contents (uploads + thumbnails)
# Preserves images/ folders in skins, extensions, etc.

BACKUP_DATE=$(date +%Y%m%d)
WIKI_ZIP="../mediawiki_non_images_backup_${BACKUP_DATE}.zip"

# Step 1: Create the main ZIP with exclusions (this skips ./images/.htaccess too)
zip -r -y -9 "$WIKI_ZIP" . \
    -x "./images/*" \
    -x "./images"

if [ $? -eq 0 ]; then
    echo
    echo "Backup complete: $WIKI_ZIP"
    echo "Size: $(du -h "$WIKI_ZIP" | cut -f1)"
    echo
    echo "This backup includes:"
    echo "  - LocalSettings.php, .htaccess (root), composer.json, etc."
    echo "  - All extensions and skins (including their own images/ folders)"
else
    echo "Error: Failed to create ZIP file!"
    exit 1
fi

