#!/bin/bash
# Production deployment script
# Использование: ./deploy.sh

set -e  # Exit on error

echo "🚀 Cripto Production Deployment"
echo "================================"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
PROJECT_PATH="/home/cripto/Cripto/Develop"
VENV_PATH="$PROJECT_PATH/venv313"
USER="cripto"

echo -e "${YELLOW}Step 1: Pre-deployment checks${NC}"
if [ ! -f "$PROJECT_PATH/.env.production" ]; then
    echo -e "${RED}❌ .env.production not found!${NC}"
    exit 1
fi

if [ ! -d "$VENV_PATH" ]; then
    echo -e "${RED}❌ Virtual environment not found!${NC}"
    exit 1
fi

echo -e "${GREEN}✅ Pre-deployment checks passed${NC}"

echo -e "${YELLOW}Step 2: Pull latest code${NC}"
cd "$PROJECT_PATH"
git pull origin main || echo "⚠️  Git pull failed - skipping"

echo -e "${YELLOW}Step 3: Install/update dependencies${NC}"
source "$VENV_PATH/bin/activate"
pip install -r requirements.txt --quiet

echo -e "${YELLOW}Step 4: Database migrations${NC}"
export $(cat "$PROJECT_PATH/.env.production" | xargs)
python manage.py migrate --noinput

echo -e "${YELLOW}Step 5: Collect static files${NC}"
python manage.py collectstatic --noinput

echo -e "${YELLOW}Step 6: Django checks${NC}"
python manage.py check --deploy || echo "⚠️  Some security warnings present - review PRODUCTION_CHECKLIST.md"

echo -e "${YELLOW}Step 7: Restart services${NC}"
sudo systemctl restart cripto-web
sudo systemctl restart cripto-worker

echo -e "${YELLOW}Step 8: Verify services${NC}"
sleep 2
if sudo systemctl is-active --quiet cripto-web; then
    echo -e "${GREEN}✅ Web service running${NC}"
else
    echo -e "${RED}❌ Web service failed!${NC}"
    sudo journalctl -u cripto-web -n 20
    exit 1
fi

if sudo systemctl is-active --quiet cripto-worker; then
    echo -e "${GREEN}✅ Worker service running${NC}"
else
    echo -e "${RED}❌ Worker service failed!${NC}"
    sudo journalctl -u cripto-worker -n 20
    exit 1
fi

echo -e "${GREEN}================================${NC}"
echo -e "${GREEN}✅ Deployment completed successfully!${NC}"
echo -e "${GREEN}================================${NC}"

# Summary
echo ""
echo "📊 Service Status:"
sudo systemctl status cripto-web --no-pager | grep "Active:"
sudo systemctl status cripto-worker --no-pager | grep "Active:"

echo ""
echo "📝 Recent logs:"
echo "--- Web logs ---"
sudo journalctl -u cripto-web -n 5 --no-pager
echo "--- Worker logs ---"
sudo journalctl -u cripto-worker -n 5 --no-pager
