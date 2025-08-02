#!/bin/bash

# Database Restore Script for FinaiFlow
# This script restores PostgreSQL database from backups

set -euo pipefail

# Configuration
BACKUP_DIR="${BACKUP_DIR:-/var/backups/finaiflow}"
DB_HOST="${DB_HOST:-postgres}"
DB_PORT="${DB_PORT:-5432}"
DB_NAME="${DB_NAME:-finaiflow}"
DB_USER="${DB_USER:-postgres}"
S3_BUCKET="${S3_BUCKET:-}"
ENCRYPTION_KEY="${ENCRYPTION_KEY:-}"

# Function to log messages
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

# Function to send notifications
notify() {
    local status="$1"
    local message="$2"
    
    if [[ -n "${WEBHOOK_URL:-}" ]]; then
        curl -X POST "$WEBHOOK_URL" \
            -H "Content-Type: application/json" \
            -d "{\"status\": \"$status\", \"message\": \"$message\", \"service\": \"finaiflow-restore\"}" \
            2>/dev/null || true
    fi
    
    log "$status: $message"
}

# Function to list available backups
list_backups() {
    log "Available local backups:"
    
    if [[ -d "$BACKUP_DIR" ]]; then
        find "$BACKUP_DIR" -name "*.custom" -o -name "*.sql.gz" | sort -r | head -20
    else
        log "No local backup directory found"
    fi
    
    # List S3 backups if configured
    if [[ -n "$S3_BUCKET" ]] && command -v aws &> /dev/null; then
        log "Available S3 backups:"
        aws s3 ls "s3://$S3_BUCKET/backups/" --recursive | grep -E "\.(custom|sql\.gz)$" | tail -20
    fi
}

# Function to download backup from S3
download_from_s3() {
    local s3_path="$1"
    local local_path="$2"
    
    if command -v aws &> /dev/null; then
        aws s3 cp "$s3_path" "$local_path"
        log "Downloaded from S3: $s3_path"
    else
        log "AWS CLI not available"
        exit 1
    fi
}

# Function to decrypt file
decrypt_file() {
    local file="$1"
    
    if [[ -n "$ENCRYPTION_KEY" && "$file" == *.encrypted ]]; then
        local decrypted_file="${file%.encrypted}"
        openssl enc -aes-256-cbc -d -in "$file" -out "$decrypted_file" -k "$ENCRYPTION_KEY"
        rm "$file"
        log "File decrypted: $decrypted_file"
        echo "$decrypted_file"
    else
        echo "$file"
    fi
}

# Function to verify backup integrity
verify_backup() {
    local backup_file="$1"
    
    log "Verifying backup integrity..."
    
    # Check if checksum file exists
    if [[ -f "$backup_file.sha256" ]]; then
        if sha256sum -c "$backup_file.sha256" &>/dev/null; then
            log "Checksum verification passed"
        else
            log "ERROR: Checksum verification failed"
            exit 1
        fi
    else
        log "WARNING: No checksum file found, skipping verification"
    fi
    
    # Check if file is readable
    if [[ ! -r "$backup_file" ]]; then
        log "ERROR: Backup file is not readable"
        exit 1
    fi
}

# Function to create database backup before restore
create_pre_restore_backup() {
    local timestamp=$(date '+%Y%m%d_%H%M%S')
    local backup_file="$BACKUP_DIR/pre_restore_backup_$timestamp.custom"
    
    log "Creating pre-restore backup..."
    mkdir -p "$BACKUP_DIR"
    
    if pg_dump -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" \
        --verbose --no-password --format=custom --compress=9 \
        --file="$backup_file" 2>/dev/null; then
        log "Pre-restore backup created: $backup_file"
        echo "$backup_file"
    else
        log "WARNING: Could not create pre-restore backup (database may not exist)"
        echo ""
    fi
}

# Function to restore from custom format backup
restore_custom_backup() {
    local backup_file="$1"
    local create_db="${2:-false}"
    
    log "Restoring from custom format backup: $backup_file"
    
    # Create database if requested
    if [[ "$create_db" == "true" ]]; then
        log "Creating database: $DB_NAME"
        createdb -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" "$DB_NAME" || true
    fi
    
    # Restore database
    if pg_restore -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" \
        --verbose --clean --if-exists --no-owner --no-privileges \
        "$backup_file"; then
        log "Database restore completed successfully"
    else
        log "ERROR: Database restore failed"
        exit 1
    fi
}

# Function to restore from SQL dump
restore_sql_backup() {
    local backup_file="$1"
    local create_db="${2:-false}"
    
    log "Restoring from SQL backup: $backup_file"
    
    # Create database if requested
    if [[ "$create_db" == "true" ]]; then
        log "Creating database: $DB_NAME"
        createdb -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" "$DB_NAME" || true
    fi
    
    # Decompress if needed
    local sql_file="$backup_file"
    if [[ "$backup_file" == *.gz ]]; then
        sql_file="${backup_file%.gz}"
        gunzip -c "$backup_file" > "$sql_file"
    fi
    
    # Restore database
    if psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" \
        -f "$sql_file"; then
        log "Database restore completed successfully"
    else
        log "ERROR: Database restore failed"
        exit 1
    fi
    
    # Clean up decompressed file
    if [[ "$backup_file" == *.gz && -f "$sql_file" ]]; then
        rm "$sql_file"
    fi
}

# Function to restore tenant-specific data
restore_tenant_data() {
    local tenant_id="$1"
    local backup_file="$2"
    
    log "Restoring tenant data for: $tenant_id"
    
    # This would be implemented based on your multi-tenant architecture
    # For schema-based tenancy:
    if [[ "$backup_file" == *.custom ]]; then
        pg_restore -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" \
            --verbose --schema="tenant_$tenant_id" \
            "$backup_file"
    else
        # For SQL dumps, you'd need to filter the schema
        log "Tenant-specific restore from SQL dump not implemented"
        exit 1
    fi
}

# Function to perform point-in-time recovery
point_in_time_recovery() {
    local target_time="$1"
    local base_backup="$2"
    
    log "Performing point-in-time recovery to: $target_time"
    
    # This would require WAL archiving to be set up
    # Implementation depends on your PostgreSQL configuration
    log "Point-in-time recovery requires WAL archiving setup"
    log "Please ensure you have:"
    log "1. Base backup from before target time"
    log "2. WAL files from base backup to target time"
    log "3. recovery.conf configured properly"
    
    # Example recovery.conf content:
    cat << EOF > /tmp/recovery.conf.example
restore_command = 'cp /path/to/wal/archive/%f %p'
recovery_target_time = '$target_time'
recovery_target_action = 'promote'
EOF
}

# Function to validate restore
validate_restore() {
    log "Validating database restore..."
    
    # Check if database exists and is accessible
    if psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" \
        -c "SELECT 1" &>/dev/null; then
        log "Database is accessible"
    else
        log "ERROR: Database is not accessible"
        exit 1
    fi
    
    # Check table counts (basic validation)
    local table_count=$(psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" \
        -t -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public'")
    
    log "Found $table_count tables in public schema"
    
    # Run basic queries to ensure data integrity
    if psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" \
        -c "SELECT COUNT(*) FROM users LIMIT 1" &>/dev/null; then
        local user_count=$(psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" \
            -t -c "SELECT COUNT(*) FROM users")
        log "Found $user_count users in database"
    fi
    
    log "Basic validation completed"
}

# Main execution
main() {
    local action="${1:-list}"
    local backup_file="${2:-}"
    local create_db="${3:-false}"
    
    export PGPASSWORD="${DB_PASSWORD:-}"
    
    case "$action" in
        "list")
            list_backups
            ;;
        "restore")
            if [[ -z "$backup_file" ]]; then
                log "Usage: $0 restore <backup_file> [create_db]"
                exit 1
            fi
            
            # Handle S3 path
            if [[ "$backup_file" == s3://* ]]; then
                local local_file="$BACKUP_DIR/$(basename "$backup_file")"
                mkdir -p "$BACKUP_DIR"
                download_from_s3 "$backup_file" "$local_file"
                backup_file="$local_file"
            fi
            
            # Decrypt if needed
            backup_file=$(decrypt_file "$backup_file")
            
            # Verify backup
            verify_backup "$backup_file"
            
            # Create pre-restore backup
            pre_restore_backup=$(create_pre_restore_backup)
            
            log "Starting database restore..."
            notify "INFO" "Starting database restore from $backup_file"
            
            # Restore based on file type
            if [[ "$backup_file" == *.custom ]]; then
                restore_custom_backup "$backup_file" "$create_db"
            elif [[ "$backup_file" == *.sql || "$backup_file" == *.sql.gz ]]; then
                restore_sql_backup "$backup_file" "$create_db"
            else
                log "ERROR: Unsupported backup file format"
                exit 1
            fi
            
            # Validate restore
            validate_restore
            
            notify "SUCCESS" "Database restore completed successfully"
            ;;
        "tenant")
            local tenant_id="$2"
            local tenant_backup="$3"
            if [[ -z "$tenant_id" || -z "$tenant_backup" ]]; then
                log "Usage: $0 tenant <tenant_id> <backup_file>"
                exit 1
            fi
            restore_tenant_data "$tenant_id" "$tenant_backup"
            ;;
        "pitr")
            local target_time="$2"
            local base_backup="$3"
            if [[ -z "$target_time" || -z "$base_backup" ]]; then
                log "Usage: $0 pitr <target_time> <base_backup>"
                exit 1
            fi
            point_in_time_recovery "$target_time" "$base_backup"
            ;;
        *)
            log "Usage: $0 [list|restore|tenant|pitr] [options...]"
            log "  list                          - List available backups"
            log "  restore <backup_file> [true]  - Restore database (optionally create DB)"
            log "  tenant <tenant_id> <backup>   - Restore tenant-specific data"
            log "  pitr <time> <base_backup>     - Point-in-time recovery"
            exit 1
            ;;
    esac
}

# Handle signals for graceful shutdown
trap 'log "Restore interrupted"; exit 1' INT TERM

# Run main function
main "$@"