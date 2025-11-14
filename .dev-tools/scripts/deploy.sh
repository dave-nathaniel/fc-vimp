#!/bin/bash

# Django Docker Deployment Script
# This script handles the initial deployment of your Django application

set -e  # Exit on any error

echo "=================================================="
echo "Django Docker Deployment Script"
echo "=================================================="
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if .env file exists
if [ ! -f .env ]; then
    echo -e "${YELLOW}Warning: .env file not found!${NC}"
    echo "Creating .env from .env.defaults..."
    
    if [ -f .defaults.env ]; then
        ./.dev-tools/scripts/make_env.sh
    else
        echo -e "${RED}Error: .defaults.env not found!${NC}"
        echo "Please create a .defaults.env file in the root directory"
        exit 1
    fi
fi

echo "Step 1: Stopping any existing containers..."
docker compose down

echo ""
echo "Step 2: Building Docker images..."
docker compose build --no-cache

echo ""
echo "Step 3: Starting database and Redis services..."
docker compose up -d db redis

echo "Waiting for database to be ready..."
sleep 15

echo ""
echo "Step 4: Running database migrations..."
docker compose run --rm web python manage.py migrate

echo ""
echo "Step 5: Collecting static files..."
docker compose run --rm web python manage.py collectstatic --noinput

echo ""
echo "Step 6: Creating superuser (optional)..."
read -p "Do you want to create a superuser? (y/n): " CREATE_SUPERUSER
if [ "$CREATE_SUPERUSER" = "y" ]; then
    docker compose run --rm web python manage.py createsuperuser
fi

echo ""
echo "Step 7: Starting all services..."
docker compose up -d

echo ""
echo -e "${GREEN}=================================================="
echo "Deployment completed successfully!"
echo "==================================================${NC}"
echo ""
echo "Your application is now running:"
echo "  - Django App: http://localhost (via Nginx)"
echo "  - Django Admin: http://localhost/admin"
echo "  - Direct Django: http://localhost:8000"
echo ""
echo "Useful commands:"
echo "  - View logs: docker compose logs -f"
echo "  - View specific service logs: docker compose logs -f web"
echo "  - Stop services: docker compose down"
echo "  - Restart services: docker compose restart"
echo "  - Run Django commands: docker compose exec web python manage.py [command]"
echo ""
echo -e "${YELLOW}Next steps:${NC}"
echo "  1. Update nginx/conf.d/django.conf with your domain name"
echo "  2. Configure SSL certificates for HTTPS"
echo "  3. Review and adjust your .env file"
echo "  4. Set up database backups"
echo ""
