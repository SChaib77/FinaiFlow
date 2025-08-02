#!/bin/bash
# FinaiFlow 2.0 Initial Setup Script
# This script sets up the environment for first-time deployment

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

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

log_step() {
    echo -e "${BLUE}[STEP]${NC} $1"
}

# Generate secure secret key
generate_secret_key() {
    if command -v openssl &> /dev/null; then
        openssl rand -hex 32
    else
        # Fallback to urandom
        tr -dc A-Za-z0-9 </dev/urandom | head -c 64
    fi
}

# Setup environment file
setup_env_file() {
    log_step "Setting up environment configuration..."
    
    if [ -f ".env" ]; then
        log_warn ".env file already exists. Backing up to .env.backup"
        cp .env .env.backup
    fi
    
    if [ ! -f ".env.example" ]; then
        log_error ".env.example not found!"
        exit 1
    fi
    
    # Copy example to .env
    cp .env.example .env
    
    # Generate secret key
    SECRET_KEY=$(generate_secret_key)
    
    # Update .env with generated values
    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS
        sed -i '' "s/your-super-secret-key-change-this-in-production/$SECRET_KEY/g" .env
    else
        # Linux
        sed -i "s/your-super-secret-key-change-this-in-production/$SECRET_KEY/g" .env
    fi
    
    log_info "Environment file created. Please edit .env to add your specific configurations."
}

# Create necessary directories
create_directories() {
    log_step "Creating necessary directories..."
    
    directories=(
        "logs"
        "uploads"
        "backups"
        "config/nginx"
        "config/nginx/ssl"
        "monitoring/prometheus"
        "monitoring/grafana/dashboards"
        "monitoring/grafana/provisioning"
    )
    
    for dir in "${directories[@]}"; do
        mkdir -p "$dir"
        log_info "Created directory: $dir"
    done
}

# Setup nginx configuration
setup_nginx_config() {
    log_step "Setting up Nginx configuration..."
    
    cat > config/nginx/nginx.conf << 'EOF'
user nginx;
worker_processes auto;
error_log /var/log/nginx/error.log warn;
pid /var/run/nginx.pid;

events {
    worker_connections 1024;
    use epoll;
    multi_accept on;
}

http {
    include /etc/nginx/mime.types;
    default_type application/octet-stream;

    # Logging
    access_log /var/log/nginx/access.log;

    # Performance
    sendfile on;
    tcp_nopush on;
    tcp_nodelay on;
    keepalive_timeout 65;
    types_hash_max_size 2048;

    # Security
    server_tokens off;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;

    # Gzip
    gzip on;
    gzip_vary on;
    gzip_proxied any;
    gzip_comp_level 6;
    gzip_types text/plain text/css text/xml text/javascript application/json application/javascript application/xml+rss application/rss+xml application/atom+xml image/svg+xml;

    # Rate limiting
    limit_req_zone $binary_remote_addr zone=api_limit:10m rate=10r/s;
    limit_req_status 429;

    # Upstream
    upstream api_backend {
        least_conn;
        server api:8000 max_fails=3 fail_timeout=30s;
    }

    # HTTP to HTTPS redirect
    server {
        listen 80;
        server_name _;
        return 301 https://$host$request_uri;
    }

    # HTTPS server
    server {
        listen 443 ssl http2;
        server_name _;

        # SSL configuration
        ssl_certificate /etc/nginx/ssl/cert.pem;
        ssl_certificate_key /etc/nginx/ssl/key.pem;
        ssl_protocols TLSv1.2 TLSv1.3;
        ssl_ciphers HIGH:!aNULL:!MD5;
        ssl_prefer_server_ciphers on;

        # API proxy
        location / {
            proxy_pass http://api_backend;
            proxy_http_version 1.1;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection 'upgrade';
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_cache_bypass $http_upgrade;

            # Rate limiting
            limit_req zone=api_limit burst=20 nodelay;

            # Timeouts
            proxy_connect_timeout 60s;
            proxy_send_timeout 60s;
            proxy_read_timeout 60s;
        }

        # Health check endpoint
        location /health {
            proxy_pass http://api_backend/health;
            access_log off;
        }

        # Metrics endpoint (internal only)
        location /metrics {
            proxy_pass http://api_backend/metrics;
            allow 127.0.0.1;
            deny all;
        }
    }
}
EOF
    
    log_info "Nginx configuration created"
}

# Generate self-signed SSL certificates (for development)
generate_ssl_certificates() {
    log_step "Generating self-signed SSL certificates..."
    
    if [ ! -f "config/nginx/ssl/cert.pem" ]; then
        openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
            -keyout config/nginx/ssl/key.pem \
            -out config/nginx/ssl/cert.pem \
            -subj "/C=US/ST=State/L=City/O=FinaiFlow/CN=localhost"
        
        log_info "SSL certificates generated (self-signed for development)"
    else
        log_info "SSL certificates already exist"
    fi
}

# Setup database initialization script
setup_database_init() {
    log_step "Setting up database initialization..."
    
    cat > scripts/init-db.sql << 'EOF'
-- FinaiFlow 2.0 Database Initialization Script

-- Create extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Create initial schema
CREATE SCHEMA IF NOT EXISTS public;

-- Grant permissions
GRANT ALL ON SCHEMA public TO finaiflow_user;
GRANT ALL ON ALL TABLES IN SCHEMA public TO finaiflow_user;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO finaiflow_user;

-- Create indexes for performance
-- These will be created by Alembic migrations, but we prepare the database
EOF
    
    log_info "Database initialization script created"
}

# Main setup flow
main() {
    echo -e "${BLUE}╔══════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║   FinaiFlow 2.0 Setup Script         ║${NC}"
    echo -e "${BLUE}╚══════════════════════════════════════╝${NC}"
    echo
    
    log_info "Starting FinaiFlow 2.0 initial setup..."
    
    # Run setup steps
    setup_env_file
    create_directories
    setup_nginx_config
    generate_ssl_certificates
    setup_database_init
    
    echo
    log_info "Setup completed successfully!"
    echo
    echo -e "${YELLOW}Next steps:${NC}"
    echo "1. Edit the .env file with your specific configuration"
    echo "2. For production, replace self-signed SSL certificates with real ones"
    echo "3. Run './scripts/deploy.sh' to deploy the application"
    echo
}

# Check if script is run with sudo
if [ "$EUID" -eq 0 ]; then
   log_warn "Please don't run this script as root/sudo"
   exit 1
fi

# Run main function
main "$@"