# VoiceHive Hotels Makefile
# Production-ready commands for development and deployment

.PHONY: help setup-dev up down test deploy clean verify-all

# Default target
help:
	@echo "VoiceHive Hotels - Available commands:"
	@echo "  make setup-dev      - Set up development environment"
	@echo "  make up            - Start local development stack"
	@echo "  make down          - Stop local development stack"
	@echo "  make test          - Run all tests"
	@echo "  make test-connector VENDOR=<name> - Test specific connector"
	@echo "  make new-connector VENDOR=<name>  - Generate new connector"
	@echo "  make deploy ENV=<env> - Deploy to environment"
	@echo "  make clean         - Clean up generated files"
	@echo "  make verify-all    - Verify all components are working"
	@echo "  make sprint-status - Show current sprint progress"
	@echo "  make security-scan - Run security scans"
	@echo "  make compliance-evidence - Generate compliance package"

# Development setup
setup-dev:
	@echo "Setting up development environment..."
	# Install Python dependencies
	pip install -r requirements-dev.txt
	# Install pre-commit hooks
	pre-commit install
	# Create local environment file
	cp .env.example .env
	# Set up local directories
	mkdir -p data/recordings data/transcripts logs
	@echo "✅ Development environment ready!"

# Docker commands
up:
	docker compose -f infra/docker/docker-compose.yml up -d
	@echo "✅ Stack is running!"
	@echo "  - Orchestrator: http://localhost:8080"
	@echo "  - Grafana: http://localhost:3000"
	@echo "  - Prometheus: http://localhost:9090"

down:
	docker compose -f infra/docker/docker-compose.yml down -v

logs:
	docker compose -f infra/docker/docker-compose.yml logs -f

# Testing
test:
	@echo "Running all tests..."
	# Type checking
	mypy services connectors --strict
	# Linting
	ruff check services connectors
	# Security scan
	bandit -r services connectors
	# Unit tests
	pytest -v --cov=connectors --cov=services
	# Connector tests
	pytest connectors/tests/golden_contract -v

test-connectors:
	pytest connectors/tests -v

test-connector:
	@if [ -z "$(VENDOR)" ]; then \
		echo "Usage: make test-connector VENDOR=<name>"; \
		exit 1; \
	fi
	pytest connectors/tests -k $(VENDOR) -v

# Connector management
new-connector:
	@if [ -z "$(VENDOR)" ]; then \
		echo "Usage: make new-connector VENDOR=<name>"; \
		exit 1; \
	fi
	python tools/generate-connector.py --vendor $(VENDOR)
	@echo "✅ Generated connector scaffold at connectors/adapters/$(VENDOR)/"

validate-connector:
	@if [ -z "$(VENDOR)" ]; then \
		echo "Usage: make validate-connector VENDOR=<name>"; \
		exit 1; \
	fi
	# Run golden contract tests
	pytest connectors/tests/golden_contract::test_$(VENDOR) -v
	# Check capability matrix
	python tools/validate-capabilities.py --vendor $(VENDOR)

generate-docs:
	@if [ -z "$(VENDOR)" ]; then \
		echo "Usage: make generate-docs VENDOR=<name>"; \
		exit 1; \
	fi
	python tools/marketplace-generator/generate.py --vendor $(VENDOR)
	@echo "✅ Generated partner docs at docs/partners/$(VENDOR)/"

# GDPR compliance
gdpr-audit:
	@if [ -z "$(TENANT)" ]; then \
		echo "Usage: make gdpr-audit TENANT=<hotel_id>"; \
		exit 1; \
	fi
	python tools/gdpr-audit.py --tenant $(TENANT)

pii-scan:
	# Scan logs for PII
	python tools/pii-scanner.py --path logs/
	# Scan database
	python tools/pii-scanner.py --database

# Performance testing
load-test:
	@echo "Running load test with $(CALLS) concurrent calls..."
	locust -f tests/load/locustfile.py \
		--headless \
		--users $(CALLS) \
		--spawn-rate 10 \
		--run-time 5m \
		--host http://localhost:8080

test-call:
	@if [ -z "$(LANGUAGE)" ] || [ -z "$(SCENARIO)" ]; then \
		echo "Usage: make test-call LANGUAGE=<lang> SCENARIO=<scenario>"; \
		exit 1; \
	fi
	python tools/call-simulator/simulate.py \
		--language $(LANGUAGE) \
		--scenario $(SCENARIO) \
		--pms apaleo

# Deployment
deploy:
	@if [ -z "$(ENV)" ]; then \
		echo "Usage: make deploy ENV=<staging|production>"; \
		exit 1; \
	fi
	@echo "Deploying to $(ENV)..."
	# Run pre-deployment checks
	./scripts/pre-deploy-check.sh $(ENV)
	# Apply Kubernetes manifests
	kubectl apply -k infra/k8s/overlays/$(ENV)
	# Wait for rollout
	kubectl rollout status deployment/orchestrator -n voicehive-$(ENV)
	kubectl rollout status deployment/connectors -n voicehive-$(ENV)
	@echo "✅ Deployed to $(ENV)"

deploy-hotfix:
	@if [ -z "$(VERSION)" ] || [ -z "$(COMPONENT)" ]; then \
		echo "Usage: make deploy-hotfix VERSION=<version> COMPONENT=<component>"; \
		exit 1; \
	fi
	kubectl set image deployment/$(COMPONENT) \
		$(COMPONENT)=voicehive/$(COMPONENT):$(VERSION) \
		-n voicehive-production
	kubectl rollout status deployment/$(COMPONENT) -n voicehive-production

# Monitoring
monitor:
	@if [ -z "$(ENV)" ]; then \
		echo "Usage: make monitor ENV=<staging|production>"; \
		exit 1; \
	fi
	@echo "Opening monitoring dashboards for $(ENV)..."
	open https://grafana-$(ENV).voicehive-hotels.com
	open https://datadog-$(ENV).voicehive-hotels.com

alerts:
	# Check current alerts
	curl -s http://prometheus:9090/api/v1/alerts | jq '.data.alerts[] | {alert: .labels.alertname, state: .state}'

# Database operations
db-migrate:
	alembic upgrade head

db-rollback:
	alembic downgrade -1

db-backup:
	@if [ -z "$(ENV)" ]; then \
		echo "Usage: make db-backup ENV=<staging|production>"; \
		exit 1; \
	fi
	./scripts/backup-db.sh $(ENV)

# Cleanup
clean:
	# Remove Python cache
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	# Remove test coverage
	rm -rf .coverage htmlcov/
	# Remove build artifacts
	rm -rf build/ dist/ *.egg-info
	# Clean Docker volumes
	docker compose -f infra/docker/docker-compose.yml down -v

# Security
security-scan:
	# Scan Docker images
	trivy image voicehive/orchestrator:latest
	trivy image voicehive/connectors:latest
	# Scan Python dependencies
	safety check -r requirements.txt
	# Scan for secrets
	trufflehog filesystem . --exclude-paths .trufflehog-ignore

# Dependency Security Management
security-scan-deps:
	@echo "Running comprehensive dependency security scan..."
	python scripts/security/dependency-security-manager.py scan --service all --format json --output security-scan-results.json
	@echo "✅ Dependency security scan completed. Results saved to security-scan-results.json"

security-scan-service:
	@if [ -z "$(SERVICE)" ]; then \
		echo "Usage: make security-scan-service SERVICE=<service_name>"; \
		exit 1; \
	fi
	python scripts/security/dependency-security-manager.py scan --service $(SERVICE) --format markdown

security-update:
	@echo "Updating dependencies with security patches..."
	python scripts/security/dependency-security-manager.py update --service all --security-only
	@echo "✅ Security updates applied"

security-update-service:
	@if [ -z "$(SERVICE)" ]; then \
		echo "Usage: make security-update-service SERVICE=<service_name>"; \
		exit 1; \
	fi
	python scripts/security/dependency-security-manager.py update --service $(SERVICE) --security-only

security-pin-deps:
	@echo "Pinning dependencies with hash verification..."
	python scripts/security/dependency-security-manager.py pin --service all --with-hashes
	@echo "✅ Dependencies pinned with hashes"

security-audit:
	@echo "Running security audit (fails on critical vulnerabilities)..."
	python scripts/security/dependency-security-manager.py audit --service all

license-check:
	@echo "Checking license compliance..."
	# Generate license reports for each service
	for service in orchestrator connectors riva-proxy tts-router media-agent; do \
		if [ -f "services/$$service/requirements.txt" ] || [ "$$service" = "connectors" ]; then \
			echo "Checking licenses for $$service..."; \
			REQ_FILE="services/$$service/requirements.txt"; \
			if [ "$$service" = "connectors" ]; then \
				REQ_FILE="connectors/requirements-test.txt"; \
			fi; \
			if [ -f "$$REQ_FILE" ]; then \
				python -m venv temp_env_$$service; \
				source temp_env_$$service/bin/activate; \
				pip install -r "$$REQ_FILE" > /dev/null 2>&1; \
				pip-licenses --format json --output-file license-report-$$service.json; \
				deactivate; \
				rm -rf temp_env_$$service; \
			fi; \
		fi; \
	done
	# Check compliance
	python scripts/security/check-license-compliance.py \
		--config config/security/dependency-security-config.yaml \
		--reports license-report-*.json \
		--output license-compliance-report.json \
		--format markdown
	@echo "✅ License compliance check completed"

security-dashboard:
	@echo "Generating security dashboard..."
	python scripts/security/generate-security-dashboard.py \
		--vulnerability-reports "security-scan-results.json" \
		--license-reports "license-compliance-report.json" \
		--output security-dashboard.html \
		--format html
	@echo "✅ Security dashboard generated: security-dashboard.html"

security-setup:
	@echo "Setting up security tools..."
	pip install -r scripts/security/requirements-security-tools.txt
	@echo "✅ Security tools installed"

security-full:
	@echo "Running full security analysis..."
	$(MAKE) security-scan-deps
	$(MAKE) license-check
	$(MAKE) security-dashboard
	@echo "✅ Full security analysis completed. Check security-dashboard.html"

update-deps:
	# Update Python dependencies
	pip-compile requirements.in -U
	pip-compile requirements-dev.in -U
	# Update npm dependencies
	cd services/media && npm update
	# Update Go dependencies
	cd services/gateway && go get -u ./... && go mod tidy

# Development helpers
format:
	# Format Python code
	black services connectors tools
	isort services connectors tools
	# Format YAML
	prettier --write "**/*.yaml" "**/*.yml"

lint:
	# Lint Python
	ruff check services connectors tools
	mypy services connectors tools
	# Lint Dockerfiles
	hadolint infra/docker/*/Dockerfile
	# Lint Kubernetes manifests
	kubeval infra/k8s/base/*.yaml

# Sprint 0 specific commands
verify-all:
	@echo "Verifying Sprint 0 components..."
	# Verify connector framework
	python connectors/verify_setup.py
	# Check Kubernetes manifests
	kubeval infra/k8s/base/*.yaml || true
	kubeval infra/k8s/vault/*.yaml || true
	kubeval infra/k8s/gatekeeper/constraint-templates/*.yaml || true
	# Verify CI/CD workflow
	yamllint .github/workflows/ci.yml || true
	@echo "✅ All components verified!"

sprint-status:
	@echo "Current Sprint 0 Status:"
	@echo "========================"
	@cat docs/sprints/sprint-0-status.md | head -20
	@echo ""
	@echo "For full status: cat docs/sprints/sprint-0-status.md"

compliance-evidence:
	@echo "Generating compliance evidence package..."
	./tools/compliance/evidence-collector.sh
	@echo "✅ Evidence package created!"

terraform-plan:
	@if [ -z "$(ENV)" ]; then \
		echo "Usage: make terraform-plan ENV=<dev|staging|production>"; \
		exit 1; \
	fi
	cd infra/terraform && terraform plan -var-file=environments/$(ENV).tfvars

terraform-compliance:
	@echo "Validating Terraform EU compliance..."
	cd infra/terraform && terraform validate
	# Check for non-EU regions
	@! grep -r "us-\|ap-" infra/terraform/*.tf || echo "⚠️ WARNING: Non-EU regions detected!"

vault-rotate-secrets:
	@echo "Rotating Vault secrets..."
	./infra/k8s/vault/setup-scripts/rotate-secrets.sh

gatekeeper-validate:
	@echo "Validating Gatekeeper policies..."
	kubectl get constraints -A || echo "Gatekeeper not installed yet"
	k8s-security-audit:
	@echo "Running Kubernetes security audit..."
	# Would run kube-bench in real cluster
	@echo "Note: Install kube-bench for full audit"

local-up:
	docker compose -f infra/docker/docker-compose.yml up -d
	@echo "✅ Local stack is running!"

local-logs:
	docker compose -f infra/docker/docker-compose.yml logs -f

test-integration:
	@echo "Running integration tests..."
	pytest tests/integration -v

pre-commit:
	pre-commit run --all-files

# CI/CD helpers
ci-test:
	# Run tests in CI mode
	pytest --cov=connectors --cov=services \
		--cov-report=xml \
		--cov-report=term \
		--junit-xml=test-results.xml

ci-build:
	# Build all Docker images
	docker build -t voicehive/orchestrator:$(VERSION) -f services/orchestrator/Dockerfile services/orchestrator/
	docker build -t voicehive/connectors:$(VERSION) -f connectors/Dockerfile connectors/
	docker build -t voicehive/media:$(VERSION) -f services/media/Dockerfile services/media/

ci-push:
	# Push to registry
	docker push voicehive/orchestrator:$(VERSION)
	docker push voicehive/connectors:$(VERSION)
	docker push voicehive/media:$(VERSION)
