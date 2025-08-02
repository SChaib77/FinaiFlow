#!/bin/bash

# Database Backup Script for FinaiFlow
# This script creates full and incremental backups of PostgreSQL database

set -euo pipefail

# Configuration
BACKUP_DIR="${BACKUP_DIR:-/var/backups/finaiflow}"
DB_HOST="${DB_HOST:-postgres}"
DB_PORT="${DB_PORT:-5432}"
DB_NAME="${DB_NAME:-finaiflow}"
DB_USER="${DB_USER:-postgres}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"
S3_BUCKET="${S3_BUCKET:-}"
ENCRYPTION_KEY="${ENCRYPTION_KEY:-}"

# Create backup directory
mkdir -p "$BACKUP_DIR"

# Function to log messages
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$BACKUP_DIR/backup.log"
}

# Function to send notifications
notify() {
    local status="$1"
    local message="$2"
    
    # Send to webhook if configured
    if [[ -n "${WEBHOOK_URL:-}" ]]; then
        curl -X POST "$WEBHOOK_URL" \
            -H "Content-Type: application/json" \
            -d "{\"status\": \"$status\", \"message\": \"$message\", \"service\": \"finaiflow-backup\"}" \
            2>/dev/null || true
    fi
    
    # Log locally
    log "$status: $message"
}

# Function to create full backup
create_full_backup() {
    local timestamp=$(date '+%Y%m%d_%H%M%S')
    local backup_file="$BACKUP_DIR/full_backup_$timestamp.sql"
    local compressed_file="$backup_file.gz"
    
    log "Starting full database backup..."
    
    # Create backup
    if pg_dump -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" \
        --verbose --no-password --format=custom --compress=9 \
        --file="$backup_file.custom" 2>&1 | tee -a "$BACKUP_DIR/backup.log"; then
        
        # Also create SQL dump for easier restore
        pg_dump -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" \
            --verbose --no-password --format=plain > "$backup_file"
        
        # Compress SQL dump
        gzip "$backup_file"
        
        # Encrypt if key provided
        if [[ -n "$ENCRYPTION_KEY" ]]; then
            encrypt_file "$compressed_file"
            encrypt_file "$backup_file.custom"
        fi
        
        # Calculate checksums
        sha256sum "$compressed_file" > "$compressed_file.sha256"
        sha256sum "$backup_file.custom" > "$backup_file.custom.sha256"
        
        local size=$(du -h "$compressed_file" | cut -f1)
        log "Full backup completed successfully. Size: $size"
        
        # Upload to S3 if configured
        if [[ -n "$S3_BUCKET" ]]; then
            upload_to_s3 "$compressed_file" "full/"
            upload_to_s3 "$backup_file.custom" "full/"
            upload_to_s3 "$compressed_file.sha256" "full/"
            upload_to_s3 "$backup_file.custom.sha256" "full/"
        fi
        
        notify "SUCCESS" "Full database backup completed. Size: $size"
        echo "$backup_file.custom" # Return backup file path
        
    else
        notify "ERROR" "Full database backup failed"
        exit 1
    fi
}

# Function to create incremental backup using WAL-E or pgBackRest
create_incremental_backup() {
    local timestamp=$(date '+%Y%m%d_%H%M%S')
    
    log "Starting incremental backup..."
    
    # This would use WAL-E or pgBackRest for incremental backups
    # For now, we'll create a logical backup of recent changes
    
    # Get latest changes (last 24 hours)
    local incremental_file="$BACKUP_DIR/incremental_$timestamp.sql"
    
    # Example: backup only recent data
    pg_dump -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" \
        --verbose --no-password \
        --where="created_at >= NOW() - INTERVAL '24 hours' OR updated_at >= NOW() - INTERVAL '24 hours'" \
        > "$incremental_file"
    
    # Compress
    gzip "$incremental_file"
    
    # Encrypt if key provided
    if [[ -n "$ENCRYPTION_KEY" ]]; then
        encrypt_file "$incremental_file.gz"
    fi
    
    local size=$(du -h "$incremental_file.gz" | cut -f1)
    log "Incremental backup completed. Size: $size"
    
    # Upload to S3 if configured
    if [[ -n "$S3_BUCKET" ]]; then
        upload_to_s3 "$incremental_file.gz" "incremental/"
    fi
    
    notify "SUCCESS" "Incremental backup completed. Size: $size"
}

# Function to encrypt files
encrypt_file() {
    local file="$1"
    if [[ -f "$file" && -n "$ENCRYPTION_KEY" ]]; then
        openssl enc -aes-256-cbc -salt -in "$file" -out "$file.encrypted" -k "$ENCRYPTION_KEY"
        rm "$file"
        mv "$file.encrypted" "$file"
        log "File encrypted: $file"
    fi
}

# Function to upload to S3
upload_to_s3() {
    local file="$1"
    local prefix="$2"
    local filename=$(basename "$file")
    
    if command -v aws &> /dev/null; then
        aws s3 cp "$file" "s3://$S3_BUCKET/backups/$prefix$filename" \
            --storage-class STANDARD_IA \
            --server-side-encryption AES256
        log "Uploaded to S3: s3://$S3_BUCKET/backups/$prefix$filename"
    else
        log "AWS CLI not available, skipping S3 upload"
    fi
}

# Function to cleanup old backups
cleanup_old_backups() {
    log "Cleaning up backups older than $RETENTION_DAYS days..."
    
    # Remove local files
    find "$BACKUP_DIR" -name "*.sql.gz" -mtime +$RETENTION_DAYS -delete
    find "$BACKUP_DIR" -name "*.custom" -mtime +$RETENTION_DAYS -delete
    find "$BACKUP_DIR" -name "*.sha256" -mtime +$RETENTION_DAYS -delete
    
    # Remove from S3 if configured
    if [[ -n "$S3_BUCKET" ]] && command -v aws &> /dev/null; then
        aws s3 rm "s3://$S3_BUCKET/backups/" --recursive \
            --exclude "*" \
            --include "*$(date -d "$RETENTION_DAYS days ago" '+%Y%m%d')*"
    fi
    
    log "Cleanup completed"
}

# Function to verify backup integrity
verify_backup() {
    local backup_file="$1"
    
    log "Verifying backup integrity..."
    
    # Verify checksum
    if [[ -f "$backup_file.sha256" ]]; then
        if sha256sum -c "$backup_file.sha256" &>/dev/null; then
            log "Checksum verification passed"
        else
            notify "ERROR" "Backup checksum verification failed"
            exit 1
        fi
    fi
    
    # Test restore to temporary database (optional)
    if [[ "${VERIFY_RESTORE:-false}" == "true" ]]; then
        local test_db="test_restore_$(date +%s)"
        createdb -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" "$test_db"
        
        if pg_restore -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$test_db" "$backup_file" &>/dev/null; then
            dropdb -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" "$test_db"
            log "Backup restore test passed"
        else
            dropdb -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" "$test_db" 2>/dev/null || true
            notify "ERROR" "Backup restore test failed"
            exit 1
        fi
    fi
}

# Main execution
main() {
    local backup_type="${1:-full}"
    
    log "Starting $backup_type backup process..."
    
    # Set PGPASSWORD for non-interactive operation
    export PGPASSWORD="${DB_PASSWORD:-}"
    
    case "$backup_type" in
        "full")
            backup_file=$(create_full_backup)
            verify_backup "$backup_file"
            ;;
        "incremental")
            create_incremental_backup
            ;;
        *)
            log "Usage: $0 [full|incremental]"
            exit 1
            ;;
    esac
    
    cleanup_old_backups
    
    log "Backup process completed successfully"
}

# Handle signals for graceful shutdown
trap 'log "Backup interrupted"; exit 1' INT TERM

# Run main function
main "$@"