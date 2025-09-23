# VoiceHive Hotels Developer Onboarding Guide

## Welcome to VoiceHive Hotels! 🎉

This guide will help you get up and running with the VoiceHive Hotels development environment. By the end of this guide, you'll have a fully functional local development setup and understand our development workflows.

## Prerequisites

### Required Software

Before starting, ensure you have the following installed:

#### 1. Development Tools

```bash
# macOS (using Homebrew)
brew install git
brew install docker
brew install kubectl
brew install helm
brew install terraform
brew install vault
brew install redis
brew install postgresql@15

# Verify installations
git --version          # Should be 2.30+
docker --version       # Should be 20.0+
kubectl version        # Should be 1.28+
helm version          # Should be 3.10+
terraform --version   # Should be 1.5+
```

#### 2. Programming Languages

```bash
# Python 3.11+
brew install python@3.11
python3.11 --version

# Node.js 18+ (for frontend tools)
brew install node@18
node --version
npm --version
```

#### 3. IDE and Extensions

We recommend **Visual Studio Code** with these extensions:

- Python
- Kubernetes
- Docker
- HashiCorp Terraform
- YAML
- GitLens
- Thunder Client (for API testing)

### Required Accounts and Access

#### 1. GitHub Access

- [ ] GitHub account with access to `voicehive/voicehive-hotels` repository
- [ ] SSH key configured for GitHub
- [ ] Added to the VoiceHive development team

#### 2. Cloud Services

- [ ] AWS CLI configured with development account access
- [ ] Access to development EKS cluster
- [ ] Vault access for secrets management

#### 3. Communication Tools

- [ ] Slack workspace access (#engineering, #devops channels)
- [ ] PagerDuty account (for on-call rotation)
- [ ] Confluence access for documentation

## Environment Setup

### 1. Repository Setup

#### Clone the Repository

```bash
# Clone the main repository
git clone git@github.com:voicehive/voicehive-hotels.git
cd voicehive-hotels

# Set up git hooks
cp .githooks/* .git/hooks/
chmod +x .git/hooks/*

# Create your feature branch
git checkout -b feature/your-name-setup
```

#### Environment Configuration

```bash
# Copy environment template
cp .env.example .env.local

# Edit with your local settings
vim .env.local
```

**Required Environment Variables:**

```bash
# Database
DATABASE_URL=postgresql://postgres:password@localhost:5432/voicehive_dev
REDIS_URL=redis://localhost:6379/0

# Authentication
JWT_SECRET=your-local-jwt-secret-here
VAULT_ADDR=http://localhost:8200
VAULT_TOKEN=your-vault-token

# External Services (Development)
LIVEKIT_API_KEY=dev_api_key
LIVEKIT_API_SECRET=dev_api_secret
LIVEKIT_WS_URL=ws://localhost:7880

# AI Services
OPENAI_API_KEY=your-openai-key
AZURE_SPEECH_KEY=your-azure-speech-key
AZURE_SPEECH_REGION=westus2

# Monitoring (Optional for local dev)
PROMETHEUS_URL=http://localhost:9090
GRAFANA_URL=http://localhost:3000
```

### 2. Local Infrastructure Setup

#### Option A: Docker Compose (Recommended for beginners)

```bash
# Start local infrastructure
cd infra/docker
docker-compose up -d

# Verify services are running
docker-compose ps

# Check logs if needed
docker-compose logs postgres
docker-compose logs redis
docker-compose logs vault
```

#### Option B: Local Installation

```bash
# Start PostgreSQL
brew services start postgresql@15
createdb voicehive_dev

# Start Redis
brew services start redis

# Start Vault (development mode)
vault server -dev -dev-root-token-id="dev-token" &
export VAULT_ADDR='http://127.0.0.1:8200'
export VAULT_TOKEN="dev-token"
```

### 3. Python Environment Setup

#### Create Virtual Environment

```bash
# Create and activate virtual environment
python3.11 -m venv venv
source venv/bin/activate

# Upgrade pip
pip install --upgrade pip

# Install dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt

# Install pre-commit hooks
pre-commit install
```

#### Verify Python Setup

```bash
# Run basic tests
python -c "import fastapi; print('FastAPI installed successfully')"
python -c "import asyncpg; print('Database driver installed')"
python -c "import redis; print('Redis client installed')"
```

### 4. Database Setup

#### Initialize Database

```bash
# Run database migrations
cd services/orchestrator
alembic upgrade head

# Seed development data
python scripts/seed_dev_data.py

# Verify database setup
python -c "
import asyncio
import asyncpg

async def test_db():
    conn = await asyncpg.connect('postgresql://postgres:password@localhost:5432/voicehive_dev')
    result = await conn.fetchval('SELECT COUNT(*) FROM hotels')
    print(f'Hotels in database: {result}')
    await conn.close()

asyncio.run(test_db())
"
```

#### Database Schema Overview

```sql
-- Key tables you'll work with
\dt  -- List all tables

-- Important tables:
-- hotels: Hotel configurations
-- calls: Call records and metadata
-- users: User accounts and roles
-- audit_log: Security and audit trail
-- pms_integrations: PMS system configurations
```

### 5. Kubernetes Development Setup

#### Connect to Development Cluster

```bash
# Configure kubectl for development cluster
aws eks update-kubeconfig --region us-west-2 --name voicehive-dev

# Verify connection
kubectl get nodes
kubectl get pods -n voicehive-dev

# Set default namespace
kubectl config set-context --current --namespace=voicehive-dev
```

#### Port Forwarding for Local Development

```bash
# Forward database (if using cluster DB)
kubectl port-forward svc/postgresql 5432:5432 &

# Forward Redis
kubectl port-forward svc/redis 6379:6379 &

# Forward Vault
kubectl port-forward svc/vault 8200:8200 &

# Forward monitoring services
kubectl port-forward svc/grafana 3000:3000 &
kubectl port-forward svc/prometheus 9090:9090 &
```

## Development Workflow

### 1. Running the Application Locally

#### Start the Orchestrator Service

```bash
cd services/orchestrator

# Activate virtual environment
source ../../venv/bin/activate

# Start the development server
uvicorn app:app --reload --host 0.0.0.0 --port 8000

# In another terminal, verify it's running
curl http://localhost:8000/health
```

#### Start Additional Services

```bash
# LiveKit Agent (in new terminal)
cd services/media/livekit-agent
python agent.py

# TTS Router (in new terminal)
cd services/tts/tts-router
python app.py

# ASR Proxy (in new terminal)
cd services/asr/riva-proxy
python server.py
```

### 2. Testing Your Setup

#### Run Health Checks

```bash
# Test all services
python scripts/health_check.py

# Expected output:
# ✅ Database connection: OK
# ✅ Redis connection: OK
# ✅ Vault connection: OK
# ✅ Orchestrator service: OK
# ✅ LiveKit agent: OK
```

#### Run Unit Tests

```bash
# Run all tests
pytest

# Run specific test categories
pytest tests/unit/
pytest tests/integration/
pytest tests/security/

# Run with coverage
pytest --cov=. --cov-report=html
open htmlcov/index.html
```

#### Test API Endpoints

```bash
# Test authentication
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"dev@voicehive.com","password":"dev123"}'

# Test protected endpoint
TOKEN="your-jwt-token-here"
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/v1/calls
```

### 3. Development Tools and Utilities

#### Database Management

```bash
# Connect to database
psql postgresql://postgres:password@localhost:5432/voicehive_dev

# Useful queries
SELECT * FROM hotels LIMIT 5;
SELECT * FROM calls ORDER BY created_at DESC LIMIT 10;
SELECT * FROM audit_log WHERE action = 'login' ORDER BY created_at DESC LIMIT 5;

# Reset database (if needed)
alembic downgrade base
alembic upgrade head
python scripts/seed_dev_data.py
```

#### Redis Management

```bash
# Connect to Redis
redis-cli

# Useful commands
KEYS *                    # List all keys
GET "session:user:123"    # Get session data
FLUSHDB                   # Clear database (use carefully!)
```

#### Vault Management

```bash
# List secrets
vault kv list secret/

# Get a secret
vault kv get secret/voicehive/database

# Put a secret
vault kv put secret/voicehive/test key=value
```

## Code Standards and Best Practices

### 1. Code Style

#### Python Code Style

We use **Black** for code formatting and **isort** for import sorting:

```bash
# Format code
black .
isort .

# Check code style
flake8 .
mypy .

# These run automatically with pre-commit hooks
```

#### Code Structure

```python
# File structure example
services/orchestrator/
├── app.py                 # FastAPI application
├── models.py             # Database models
├── auth/                 # Authentication modules
│   ├── __init__.py
│   ├── middleware.py
│   └── models.py
├── routers/              # API route handlers
│   ├── __init__.py
│   ├── auth.py
│   └── calls.py
├── services/             # Business logic
│   ├── __init__.py
│   ├── call_service.py
│   └── pms_service.py
└── tests/                # Test files
    ├── __init__.py
    ├── test_auth.py
    └── test_calls.py
```

### 2. Git Workflow

#### Branch Naming Convention

```bash
# Feature branches
feature/user-authentication
feature/pms-integration

# Bug fixes
bugfix/auth-token-expiry
bugfix/database-connection

# Hotfixes
hotfix/security-vulnerability
hotfix/production-issue
```

#### Commit Message Format

```bash
# Format: type(scope): description
feat(auth): add JWT token refresh mechanism
fix(database): resolve connection pool exhaustion
docs(api): update authentication examples
test(integration): add PMS connector tests
refactor(services): extract common utilities
```

#### Pull Request Process

1. **Create Feature Branch**

   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make Changes and Commit**

   ```bash
   git add .
   git commit -m "feat(feature): implement new functionality"
   ```

3. **Push and Create PR**

   ```bash
   git push origin feature/your-feature-name
   # Create PR in GitHub with proper template
   ```

4. **PR Requirements**
   - [ ] All tests pass
   - [ ] Code coverage maintained
   - [ ] Security scan passes
   - [ ] Documentation updated
   - [ ] At least 2 reviewer approvals

### 3. Testing Standards

#### Test Structure

```python
# Test file example: tests/test_auth.py
import pytest
from fastapi.testclient import TestClient
from app import app

client = TestClient(app)

class TestAuthentication:
    def test_login_success(self):
        response = client.post("/auth/login", json={
            "email": "test@example.com",
            "password": "password123"
        })
        assert response.status_code == 200
        assert "access_token" in response.json()

    def test_login_invalid_credentials(self):
        response = client.post("/auth/login", json={
            "email": "test@example.com",
            "password": "wrong_password"
        })
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_jwt_validation(self):
        # Test JWT token validation
        pass
```

#### Test Categories

- **Unit Tests**: Test individual functions/classes
- **Integration Tests**: Test service interactions
- **End-to-End Tests**: Test complete user workflows
- **Security Tests**: Test authentication and authorization
- **Performance Tests**: Test response times and load handling

## Debugging and Troubleshooting

### 1. Common Issues and Solutions

#### Database Connection Issues

```bash
# Check if PostgreSQL is running
brew services list | grep postgresql

# Check connection
psql postgresql://postgres:password@localhost:5432/voicehive_dev

# Common fixes
brew services restart postgresql@15
createdb voicehive_dev  # If database doesn't exist
```

#### Redis Connection Issues

```bash
# Check if Redis is running
brew services list | grep redis

# Test connection
redis-cli ping

# Common fixes
brew services restart redis
redis-server /usr/local/etc/redis.conf  # Manual start
```

#### Import/Module Issues

```bash
# Ensure virtual environment is activated
source venv/bin/activate

# Reinstall dependencies
pip install -r requirements.txt

# Check Python path
python -c "import sys; print(sys.path)"
```

### 2. Debugging Tools

#### Application Debugging

```python
# Add debug logging
import logging
logging.basicConfig(level=logging.DEBUG)

# Use debugger
import pdb; pdb.set_trace()

# Or use ipdb for better experience
import ipdb; ipdb.set_trace()
```

#### API Debugging

```bash
# Use httpie for API testing
http POST localhost:8000/auth/login email=test@example.com password=password123

# Use curl with verbose output
curl -v -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"password123"}'
```

#### Database Debugging

```sql
-- Enable query logging in PostgreSQL
ALTER SYSTEM SET log_statement = 'all';
SELECT pg_reload_conf();

-- View slow queries
SELECT query, mean_time, calls
FROM pg_stat_statements
ORDER BY mean_time DESC
LIMIT 10;
```

## Development Resources

### 1. Documentation Links

#### Internal Documentation

- [API Documentation](../api/README.md)
- [Architecture Overview](../architecture/system-architecture.md)
- [Security Guidelines](../security/README.md)
- [Deployment Guide](../deployment/production-runbook.md)

#### External Resources

- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [PostgreSQL Documentation](https://www.postgresql.org/docs/)
- [Redis Documentation](https://redis.io/documentation)
- [Kubernetes Documentation](https://kubernetes.io/docs/)

### 2. Development Tools

#### Recommended VS Code Settings

```json
{
  "python.defaultInterpreterPath": "./venv/bin/python",
  "python.linting.enabled": true,
  "python.linting.flake8Enabled": true,
  "python.formatting.provider": "black",
  "python.sortImports.args": ["--profile", "black"],
  "editor.formatOnSave": true,
  "editor.codeActionsOnSave": {
    "source.organizeImports": true
  }
}
```

#### Useful Aliases

```bash
# Add to your ~/.zshrc or ~/.bashrc
alias k='kubectl'
alias kgp='kubectl get pods'
alias kgs='kubectl get services'
alias kd='kubectl describe'
alias kl='kubectl logs'

alias dc='docker-compose'
alias dcu='docker-compose up -d'
alias dcd='docker-compose down'

alias va='source venv/bin/activate'
alias vd='deactivate'

alias pt='pytest'
alias ptc='pytest --cov=.'
```

### 3. Monitoring and Observability

#### Local Monitoring Setup

```bash
# Access local monitoring tools
open http://localhost:3000    # Grafana (admin/admin)
open http://localhost:9090    # Prometheus
open http://localhost:8200    # Vault UI
```

#### Log Analysis

```bash
# View application logs
tail -f logs/orchestrator.log

# Search logs
grep "ERROR" logs/orchestrator.log
grep -i "authentication" logs/orchestrator.log

# Use jq for JSON logs
tail -f logs/orchestrator.log | jq '.message'
```

## Team Communication

### 1. Slack Channels

- **#engineering**: General engineering discussions
- **#devops**: Infrastructure and deployment topics
- **#security**: Security-related discussions
- **#voicehive-alerts**: Automated alerts and notifications
- **#random**: Non-work related chat

### 2. Meeting Schedule

- **Daily Standup**: 9:00 AM PST (Monday-Friday)
- **Sprint Planning**: Every 2 weeks (Monday)
- **Retrospective**: Every 2 weeks (Friday)
- **Architecture Review**: Monthly (First Wednesday)
- **Security Review**: Monthly (Third Wednesday)

### 3. On-Call Rotation

New developers join the on-call rotation after:

- [ ] 3 months of experience with the codebase
- [ ] Completion of incident response training
- [ ] Shadow rotation with experienced team member
- [ ] Demonstrated proficiency with debugging tools

## Next Steps

### Week 1: Getting Familiar

- [ ] Complete environment setup
- [ ] Run all tests successfully
- [ ] Make a small documentation improvement
- [ ] Attend team meetings and introduce yourself

### Week 2: First Contribution

- [ ] Pick up a "good first issue" from GitHub
- [ ] Implement the feature/fix
- [ ] Submit your first pull request
- [ ] Participate in code review process

### Week 3-4: Deeper Dive

- [ ] Work on a more complex feature
- [ ] Learn about our monitoring and alerting
- [ ] Understand the deployment process
- [ ] Start participating in architecture discussions

### Month 2-3: Full Integration

- [ ] Take ownership of a component or feature area
- [ ] Participate in on-call rotation (with mentorship)
- [ ] Contribute to technical documentation
- [ ] Mentor newer team members

## Getting Help

### 1. Technical Questions

- **Slack**: Ask in #engineering channel
- **Code Reviews**: Tag specific team members for expertise areas
- **Architecture**: Schedule time with the architecture team
- **Security**: Consult with the security team lead

### 2. Process Questions

- **Git/GitHub**: Ask your mentor or team lead
- **Deployment**: Consult with DevOps team
- **Testing**: Pair with QA team members

### 3. Emergency Situations

- **Production Issues**: Follow incident response procedures
- **Security Concerns**: Contact security team immediately
- **Access Issues**: Contact IT support

## Useful Commands Cheat Sheet

### Development Commands

```bash
# Start development environment
make dev-start

# Run tests
make test
make test-integration
make test-security

# Code quality
make lint
make format
make security-scan

# Database operations
make db-migrate
make db-seed
make db-reset

# Docker operations
make docker-build
make docker-push
make docker-clean
```

### Kubernetes Commands

```bash
# Get resources
kubectl get pods,svc,ing -n voicehive-dev

# Describe resources
kubectl describe pod <pod-name> -n voicehive-dev

# View logs
kubectl logs -f deployment/orchestrator -n voicehive-dev

# Port forwarding
kubectl port-forward svc/orchestrator 8000:8000 -n voicehive-dev

# Execute commands in pods
kubectl exec -it deployment/orchestrator -n voicehive-dev -- bash
```

### Git Commands

```bash
# Update from main
git checkout main
git pull origin main
git checkout feature/your-branch
git rebase main

# Interactive rebase (clean up commits)
git rebase -i HEAD~3

# Stash changes
git stash
git stash pop

# View commit history
git log --oneline --graph
```

## Welcome to the Team! 🚀

You're now ready to start contributing to VoiceHive Hotels! Remember:

- **Ask questions** - Everyone is here to help
- **Start small** - Build confidence with smaller tasks first
- **Learn continuously** - The technology stack is always evolving
- **Share knowledge** - Help improve this guide for future developers
- **Have fun** - We're building something amazing together!

If you have any questions or run into issues, don't hesitate to reach out to your mentor or the team. Welcome aboard! 🎉
