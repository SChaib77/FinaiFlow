#!/bin/bash
# FinaiFlow 2.0 Production Deployment Script
# This script handles the complete deployment process

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
PROJECT_NAME="finaiflow"
COMPOSE_FILE="docker-compose.production.yml"
ENV_FILE=".env"
BACKUP_DIR="./backups"

# Functions
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

check_prerequisites() {
    log_info "Checking prerequisites..."
    
    # Check Docker
    if ! command -v docker &> /dev/null; then
        log_error "Docker is not installed!"
        exit 1
    fi
    
    # Check Docker Compose
    if ! command -v docker-compose &> /dev/null; then
        log_error "Docker Compose is not installed!"
        exit 1
    fi
    
    # Check .env file
    if [ ! -f "$ENV_FILE" ]; then
        log_error ".env file not found! Copy .env.example to .env and configure it."
        exit 1
    fi
    
    log_info "Prerequisites check passed!"
}

backup_database() {
    log_info "Creating database backup..."
    
    # Create backup directory if it doesn't exist
    mkdir -p "$BACKUP_DIR"
    
    # Generate backup filename with timestamp
    BACKUP_FILE="$BACKUP_DIR/backup_$(date +%Y%m%d_%H%M%S).sql"
    
    # Run backup
    docker-compose -f "$COMPOSE_FILE" exec -T postgres pg_dump -U finaiflow_user finaiflow_db > "$BACKUP_FILE"
    
    if [ $? -eq 0 ]; then
        log_info "Database backup created: $BACKUP_FILE"
    else
        log_error "Database backup failed!"
        exit 1
    fi
}

pull_latest_code() {
    log_info "Pulling latest code from repository..."
    
    # Check if git is available
    if command -v git &> /dev/null; then
        git pull origin main
    else
        log_warn "Git not found, skipping code update"
    fi
}

build_images() {
    log_info "Building Docker images..."
    
    docker-compose -f "$COMPOSE_FILE" build --no-cache
    
    if [ $? -eq 0 ]; then
        log_info "Docker images built successfully!"
    else
        log_error "Docker image build failed!"
        exit 1
    fi
}

deploy_services() {
    log_info "Deploying services..."
    
    # Stop existing services
    log_info "Stopping existing services..."
    docker-compose -f "$COMPOSE_FILE" down
    
    # Start services
    log_info "Starting services..."
    docker-compose -f "$COMPOSE_FILE" up -d
    
    if [ $? -eq 0 ]; then
        log_info "Services deployed successfully!"
    else
        log_error "Service deployment failed!"
        exit 1
    fi
}

run_migrations() {
    log_info "Running database migrations..."
    
    # Wait for database to be ready
    sleep 10
    
    # Run Alembic migrations
    docker-compose -f "$COMPOSE_FILE" exec -T api alembic upgrade head
    
    if [ $? -eq 0 ]; then
        log_info "Database migrations completed!"
    else
        log_error "Database migrations failed!"
        exit 1
    fi
}

health_check() {
    log_info "Performing health checks..."
    
    # Wait for services to start
    sleep 15
    
    # Check API health
    if curl -f http://localhost/health > /dev/null 2>&1; then
        log_info "API health check passed!"
    else
        log_error "API health check failed!"
        exit 1
    fi
    
    # Check other services
    docker-compose -f "$COMPOSE_FILE" ps
}

cleanup_old_images() {
    log_info "Cleaning up old Docker images..."
    
    docker image prune -f
    
    log_info "Cleanup completed!"
}

# Main deployment flow
main() {
    log_info "Starting FinaiFlow 2.0 deployment..."
    
    check_prerequisites
    
    # Ask for confirmation
    read -p "Do you want to backup the database before deployment? (y/n): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        backup_database
    fi
    
    pull_latest_code
    build_images
    deploy_services
    run_migrations
    health_check
    cleanup_old_images
    
    log_info "Deployment completed successfully!"
    log_info "Application is running at http://localhost"
    log_info "Monitoring dashboard: http://localhost:3000 (Grafana)"
}

# Run main function
main "$@"