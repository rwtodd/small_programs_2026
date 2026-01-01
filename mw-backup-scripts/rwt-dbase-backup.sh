#!/bin/bash

BACKUP_DATE=$(date +%Y%m%d)

echo "Give your database password when it prompts you."

mysqldump -h kbdb.rwtodd.org --user='<<username here>>' --password --default-character-set=binary --no-tablespaces rwtodd_kbdb | xz > ../database-${BACKUP_DATE}.sql.xz

