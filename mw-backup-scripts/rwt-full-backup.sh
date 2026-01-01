#!/bin/bash

# MediaWiki images full backup script - ADAPTIVE + MISC + NO THUMBNAILS
# Correctly handles MediaWiki hash structure: images/a/a0 ... images/a/af, etc.
# Excludes ./images/thumb/ entirely

IMAGES_DIR="images"
BACKUP_DATE=$(date +%Y%m%d)
SIZE_LIMIT_GB=2
SIZE_LIMIT_BYTES=$((SIZE_LIMIT_GB * 1024 * 1024 * 1024))

if [ ! -d "$IMAGES_DIR" ]; then
    echo "Error: Directory '$IMAGES_DIR' not found!"
    exit 1
fi

echo "Starting adaptive images backup (excluding thumb/ directory) on $BACKUP_DATE"
echo "Output: ../ (parent directory)"
echo

# 1. Backup hash directories (0-9, a-f)
for top_dir in "$IMAGES_DIR"/{0,1,2,3,4,5,6,7,8,9,a,b,c,d,e,f}; do
    [ ! -d "$top_dir" ] && continue

    top_base=$(basename "$top_dir")  # e.g., 'a'
    dir_size=$(du -sb "$top_dir" | cut -f1)

    if [ "$dir_size" -le "$SIZE_LIMIT_BYTES" ]; then
        echo "[$top_base] ≤ ${SIZE_LIMIT_GB}GB → single ZIP"
        zip -r -y "../images_${top_base}_backup_${BACKUP_DATE}.zip" "$top_dir"
    else
        echo "[$top_base] > ${SIZE_LIMIT_GB}GB → splitting by second-level (${top_base}/${top_base}0 to ${top_base}/${top_base}f)"
        for second_hex in {0,1,2,3,4,5,6,7,8,9,a,b,c,d,e,f}; do
            second_base="${top_base}${second_hex}"   # e.g., a0, a1, ..., af
            second_dir="$top_dir/$second_base"
            [ ! -d "$second_dir" ] && continue
            zip -r -y "../images_${top_base}_${second_base}_backup_${BACKUP_DATE}.zip" "$second_dir"
        done
    fi
done

# 2. Misc backup: all top-level items EXCEPT hash dirs and thumb/
echo
echo "Creating miscellaneous images backup (.htaccess, archive/, deleted/, temp/, lockdir/, math/, etc.)"
echo "Excluding: thumb/ (thumbnails — regeneratable)"

find "$IMAGES_DIR" -maxdepth 1 \
    ! -name '.' \
    ! -regex ".*/[0-9a-f]" \
    ! -name 'thumb' \
    ! -name 'images' \
    -print0 | \
zip -r -y -9 "../images_misc_backup_${BACKUP_DATE}.zip" -@

if [ $? -eq 0 ]; then
    misc_size=$(du -h "../images_misc_backup_${BACKUP_DATE}.zip" | cut -f1 2>/dev/null || echo "unknown")
    echo "→ Created: images_misc_backup_${BACKUP_DATE}.zip ($misc_size)"
else
    echo "Warning: Misc backup failed or empty (okay if nothing to back up)"
fi

echo
echo "Images backup complete!"
echo "  - Original uploads: preserved in correct hash structure"
echo "  - Thumbnails: fully excluded"
echo "  - Misc files: in images_misc_backup_*.zip (includes .htaccess)"


