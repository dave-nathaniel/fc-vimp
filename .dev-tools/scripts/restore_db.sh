#!/bin/bash

# Database Restore Script for Dockerized Django Application

set -e

# Load environment variables
if [ -f .env ]; then
    export $(cat .env | grep -v '^#' | xargs)
fi

BACKUP_DIR="./backups"
CONTAINER_NAME="django_mysql"

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "Available backups:"
echo "===================="
ls -lh "$BACKUP_DIR"/db_backup_*.sql.gz 2>/dev/null || echo "No backups found!"
echo ""

read -p "Enter the backup filename to restore (or 'latest' for most recent): " BACKUP_CHOICE

if [ "$BACKUP_CHOICE" = "latest" ]; then
    BACKUP_FILE=$(ls -t "$BACKUP_DIR"/db_backup_*.sql.gz 2>/dev/null | head -1)
    if [ -z "$BACKUP_FILE" ]; then
        echo -e "${RED}No backup files found!${NC}"
        exit 1
    fi
else
    BACKUP_FILE="$BACKUP_DIR/$BACKUP_CHOICE"
fi

if [ ! -f "$BACKUP_FILE" ]; then
    echo -e "${RED}Backup file not found: $BACKUP_FILE${NC}"
    exit 1
fi

echo -e "${YELLOW}WARNING: This will replace your current database!${NC}"
read -p "Are you sure you want to restore from $BACKUP_FILE? (yes/no): " CONFIRM

if [ "$CONFIRM" != "yes" ]; then
    echo "Restore cancelled."
    exit 0
fi

echo "Restoring database from $BACKUP_FILE..."

# Decompress and restore
gunzip -c "$BACKUP_FILE" | docker exec -i $CONTAINER_NAME mysql \
    -u root \
    -p"$DB_ROOT_PASSWORD"

if [ $? -eq 0 ]; then
    echo -e "${GREEN}Database restored successfully!${NC}"
    echo "Please restart your Django services:"
    echo "  docker-compose restart web qcluster"
else
    echo -e "${RED}Database restore failed!${NC}"
    exit 1
fi
