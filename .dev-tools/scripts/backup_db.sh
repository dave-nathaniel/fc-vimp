#!/bin/bash

# Database Backup Script for Dockerized Django Application

set -e

# Load environment variables
if [ -f .env ]; then
    export $(cat .env | grep -v '^#' | xargs)
fi

# Configuration
BACKUP_DIR="./backups"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_FILE="$BACKUP_DIR/db_backup_$TIMESTAMP.sql"
CONTAINER_NAME="django_mysql"

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

# Create backup directory if it doesn't exist
mkdir -p "$BACKUP_DIR"

echo "Starting database backup..."
echo "Timestamp: $TIMESTAMP"

# Perform backup
docker exec $CONTAINER_NAME mysqldump \
    -u root \
    -p"$DB_ROOT_PASSWORD" \
    --databases "$DB_NAME" \
    --single-transaction \
    --quick \
    --lock-tables=false \
    > "$BACKUP_FILE"

# Compress backup
gzip "$BACKUP_FILE"
BACKUP_FILE="${BACKUP_FILE}.gz"

if [ -f "$BACKUP_FILE" ]; then
    FILE_SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
    echo -e "${GREEN}Backup completed successfully!${NC}"
    echo "Backup file: $BACKUP_FILE"
    echo "File size: $FILE_SIZE"
    
    # Keep only last 7 backups
    echo "Cleaning old backups (keeping last 7)..."
    cd "$BACKUP_DIR" && ls -t db_backup_*.sql.gz | tail -n +8 | xargs -r rm
    
    echo -e "${GREEN}Backup process completed!${NC}"
else
    echo -e "${RED}Backup failed!${NC}"
    exit 1
fi
