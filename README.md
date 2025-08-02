# FinaiFlow 2.0 - Production-Grade Multi-Tenant SaaS Platform

## Overview

FinaiFlow 2.0 is a production-ready, enterprise-grade multi-tenant SaaS platform built with modern technologies and best practices. It features comprehensive authentication, multi-tenancy, monitoring, and disaster recovery capabilities.

## 🚀 Features

### Core Features
- **Multi-tenant Architecture** with schema isolation
- **Enterprise Authentication** with JWT, 2FA, and passwordless login
- **OAuth2 Integration** (Google, Microsoft, GitHub)
- **Background Job Processing** with Celery
- **Real-time Monitoring** with Prometheus and Grafana
- **Comprehensive Logging** with ELK stack
- **Production-ready** with Docker and Kubernetes

### Security Features
- JWT with refresh token rotation
- Two-Factor Authentication (TOTP)
- Passwordless magic link authentication
- Rate limiting and IP-based restrictions
- Audit trail for all authentication events
- Account lockout policies
- Session management with Redis

### DevOps Features
- Multi-stage Docker builds
- Kubernetes-ready with Helm charts
- GitHub Actions CI/CD pipeline
- Automated testing and security scanning
- Monitoring and alerting
- Backup and disaster recovery procedures

## 🏗️ Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Load Balancer │────│   API Gateway   │────│   FastAPI App   │
└─────────────────┘    └─────────────────┘    └─────────────────┘
                                                        │
                       ┌─────────────────┐             │
                       │   PostgreSQL    │─────────────┘
                       │  (Multi-tenant) │
                       └─────────────────┘
                                │
                       ┌─────────────────┐
                       │      Redis      │
                       │ (Cache/Session) │
                       └─────────────────┘
                                │
                       ┌─────────────────┐
                       │     Celery      │
                       │   (Background)  │
                       └─────────────────┘
```

## 🛠️ Technology Stack

- **Backend**: FastAPI + Python 3.11
- **Database**: PostgreSQL 15 with AsyncPG
- **Cache**: Redis 7
- **Task Queue**: Celery + Redis
- **Authentication**: JWT + OAuth2 + TOTP
- **Monitoring**: Prometheus + Grafana
- **Logging**: ELK Stack (Elasticsearch, Logstash, Kibana)
- **Container**: Docker + Kubernetes
- **CI/CD**: GitHub Actions

## 🚀 Quick Start

### Prerequisites
- Docker and Docker Compose
- Python 3.11+
- Node.js (for frontend, if applicable)

### Development Setup

1. **Clone the repository**:
   ```bash
   git clone https://github.com/your-org/finaiflow-2.0.git
   cd finaiflow-2.0
   ```

2. **Set up environment variables**:
   ```bash
   cp .env.example .env
   # Edit .env with your configuration
   ```

3. **Start with Docker Compose**:
   ```bash
   docker-compose up -d
   ```

4. **Run database migrations**:
   ```bash
   docker-compose exec api alembic upgrade head
   ```

5. **Access the application**:
   - API: http://localhost:8000
   - API Docs: http://localhost:8000/docs
   - Grafana: http://localhost:3000 (admin/admin)
   - Kibana: http://localhost:5601
   - Flower: http://localhost:5555

### Production Deployment

#### Kubernetes Deployment

1. **Configure secrets**:
   ```bash
   kubectl create namespace finaiflow
   kubectl create secret generic finaiflow-secrets --from-env-file=.env.production -n finaiflow
   ```

2. **Deploy to Kubernetes**:
   ```bash
   kubectl apply -k k8s/overlays/production
   ```

3. **Verify deployment**:
   ```bash
   kubectl get pods -n finaiflow
   kubectl get ingress -n finaiflow
   ```

## 📚 Documentation

### API Documentation
- **Interactive API Docs**: `/docs` (Swagger UI)
- **ReDoc**: `/redoc`
- **OpenAPI Spec**: `/openapi.json`

### Key Endpoints

#### Authentication
- `POST /api/v1/auth/login` - User login
- `POST /api/v1/auth/refresh` - Refresh access token
- `POST /api/v1/auth/logout` - User logout
- `POST /api/v1/auth/2fa/setup` - Setup 2FA
- `POST /api/v1/auth/magic-link` - Request magic link

#### OAuth2
- `GET /api/v1/auth/oauth/{provider}` - Get OAuth authorization URL
- `POST /api/v1/auth/oauth/{provider}/callback` - Handle OAuth callback

#### User Management
- `GET /api/v1/auth/profile` - Get user profile
- `POST /api/v1/auth/change-password` - Change password

### Environment Variables

#### Required Variables
```bash
# Database
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/finaiflow
REDIS_URL=redis://localhost:6379

# Security
SECRET_KEY=your-secret-key-change-in-production
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=7

# OAuth2 (Optional)
GOOGLE_CLIENT_ID=your-google-client-id
GOOGLE_CLIENT_SECRET=your-google-client-secret
GITHUB_CLIENT_ID=your-github-client-id
GITHUB_CLIENT_SECRET=your-github-client-secret
```

#### Optional Variables
```bash
# Email
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-email@gmail.com
SMTP_PASSWORD=your-app-password

# Monitoring
PROMETHEUS_ENABLED=true
JAEGER_ENABLED=false

# Rate Limiting
RATE_LIMIT_ENABLED=true
RATE_LIMIT_REQUESTS=100
RATE_LIMIT_WINDOW=60
```

## 🔐 Security

### Authentication Flow

1. **Standard Login**:
   ```
   User → Login Endpoint → JWT Access/Refresh Tokens → Protected Resources
   ```

2. **2FA Login**:
   ```
   User → Login → 2FA Challenge → TOTP/Backup Code → JWT Tokens
   ```

3. **OAuth2 Login**:
   ```
   User → OAuth Provider → Authorization Code → Token Exchange → JWT Tokens
   ```

4. **Magic Link Login**:
   ```
   User → Email Address → Magic Link Email → Click Link → JWT Tokens
   ```

### Security Features

- **JWT Authentication** with secure token rotation
- **Multi-Factor Authentication** with TOTP and backup codes
- **Rate Limiting** per user and IP address
- **Account Lockout** after failed login attempts
- **Audit Logging** for all authentication events
- **Session Management** with Redis
- **CORS Protection** with configurable origins
- **SQL Injection Protection** with SQLAlchemy ORM
- **XSS Protection** with proper content types
- **HTTPS Enforcement** in production

## 📊 Monitoring and Logging

### Metrics (Prometheus)
- HTTP request metrics (rate, duration, status codes)
- Database connection metrics
- Redis metrics
- Celery task metrics
- Custom business metrics

### Logging (ELK Stack)
- Structured JSON logging
- Request/response logging
- Error tracking with stack traces
- Audit trail logging
- Performance monitoring

### Dashboards (Grafana)
- Application performance overview
- Database metrics
- System resource usage
- Business metrics
- Error rate monitoring

## 🏥 Health Checks

### Endpoints
- `GET /health` - Application health status
- `GET /metrics` - Prometheus metrics

### Kubernetes Probes
```yaml
livenessProbe:
  httpGet:
    path: /health
    port: 8000
  initialDelaySeconds: 30
  periodSeconds: 10

readinessProbe:
  httpGet:
    path: /health
    port: 8000
  initialDelaySeconds: 5
  periodSeconds: 5
```

## 🔄 CI/CD Pipeline

### GitHub Actions Workflow

1. **Code Quality Checks**:
   - Linting (Black, isort, flake8)
   - Type checking (mypy)
   - Security scanning (bandit, safety)

2. **Testing**:
   - Unit tests with pytest
   - Integration tests
   - Code coverage reporting

3. **Build and Deploy**:
   - Docker image building
   - Container registry push
   - Kubernetes deployment
   - Health checks

### Deployment Environments
- **Development**: Auto-deploy on push to `develop`
- **Staging**: Auto-deploy on push to `main`
- **Production**: Manual deploy on release creation

## 💾 Backup and Disaster Recovery

### Backup Strategy
- **Database**: Daily full backups, 4-hour incremental backups
- **Files**: Daily snapshots with S3 cross-region replication
- **Configuration**: Version controlled in Git
- **Retention**: 30 days local, 90 days in S3

### Recovery Procedures
- **RTO (Recovery Time Objective)**: 4 hours
- **RPO (Recovery Point Objective)**: 1 hour
- **Automated backup verification**
- **Disaster recovery testing**: Quarterly

See [Disaster Recovery Plan](docs/DISASTER_RECOVERY.md) for detailed procedures.

## 🧪 Testing

### Running Tests
```bash
# Install test dependencies
pip install pytest pytest-asyncio pytest-cov

# Run all tests
pytest

# Run with coverage
pytest --cov=app --cov-report=html

# Run specific test file
pytest tests/test_auth.py
```

### Test Structure
```
tests/
├── unit/           # Unit tests
├── integration/    # Integration tests
├── e2e/           # End-to-end tests
└── fixtures/      # Test fixtures
```

## 🤝 Contributing

### Development Setup
1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests
5. Run the test suite
6. Submit a pull request

### Code Standards
- Follow PEP 8 style guide
- Use type hints
- Write comprehensive tests
- Update documentation
- Follow conventional commits

### Pre-commit Hooks
```bash
pip install pre-commit
pre-commit install
```

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🆘 Support

### Documentation
- [API Documentation](docs/API.md)
- [Deployment Guide](docs/DEPLOYMENT.md)
- [Troubleshooting Guide](docs/TROUBLESHOOTING.md)
- [Disaster Recovery Plan](docs/DISASTER_RECOVERY.md)

### Getting Help
- GitHub Issues for bug reports and feature requests
- Discussions for questions and community support
- Email: support@finaiflow.com

### Status Page
- Production Status: https://status.finaiflow.com
- Incident History: Available on status page

---

**Built with ❤️ by the FinaiFlow Team**