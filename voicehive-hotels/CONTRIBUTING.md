# Contributing to VoiceHive Hotels

Thank you for your interest in contributing to VoiceHive Hotels! This guide will help you get started.

## Code of Conduct

- Be respectful and inclusive
- Welcome newcomers and help them get started
- Focus on what's best for the community
- Show empathy towards other community members

## Getting Started

### Prerequisites

- Python 3.11+
- Docker Desktop
- Git
- Make

### Development Setup

1. Fork the repository
2. Clone your fork:
   ```bash
   git clone https://github.com/YOUR-USERNAME/voicehive-hotels.git
   cd voicehive-hotels
   ```

3. Set up development environment:
   ```bash
   make setup-dev
   ```

4. Start local services:
   ```bash
   make up
   ```

5. Run tests:
   ```bash
   make test
   ```

## Development Process

### 1. Create a Branch

```bash
git checkout -b feature/your-feature-name
# or
git checkout -b fix/your-bug-fix
```

### 2. Make Changes

- Follow the coding standards in [WARP.md](WARP.md)
- Write tests for new functionality
- Update documentation as needed

### 3. Test Your Changes

```bash
# Run all tests
make test

# Test specific component
make test-connector VENDOR=apaleo

# Run linting
make lint

# Format code
make format
```

### 4. Commit Your Changes

We use conventional commits:

```bash
git commit -m "feat(connectors): add support for Mews webhook events"
git commit -m "fix(orchestrator): handle timeout in PMS calls"
git commit -m "docs: update API documentation"
```

Commit types:
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `style`: Code style changes (formatting, etc)
- `refactor`: Code refactoring
- `test`: Test additions or changes
- `chore`: Maintenance tasks

### 5. Push and Create PR

```bash
git push origin feature/your-feature-name
```

Then create a Pull Request on GitHub.

## Pull Request Guidelines

### PR Title

Use the same conventional commit format:
- `feat(component): description`
- `fix(component): description`

### PR Description

Include:
- What changes you made
- Why you made them
- How to test them
- Any breaking changes

### PR Checklist

- [ ] Tests pass locally
- [ ] New tests added for new features
- [ ] Documentation updated
- [ ] No security vulnerabilities
- [ ] Follows coding standards

## Adding a New PMS Connector

This is one of the most common contributions. Follow these steps:

### 1. Generate Scaffold

```bash
make new-connector VENDOR=example
```

### 2. Implement the Connector

Edit `connectors/adapters/example/connector.py`:

```python
from ...contracts import BaseConnector, PMSConnector

class ExampleConnector(BaseConnector):
    vendor_name = "example"
    
    # Implement all required methods
    async def get_availability(self, ...):
        # Your implementation
        pass
```

### 3. Update Capability Matrix

Edit `connectors/capability_matrix.yaml`:

```yaml
vendors:
  example:
    display_name: "Example PMS"
    capabilities:
      availability: true
      reservations: true
      # ... etc
```

### 4. Write Tests

Create `connectors/tests/vendor_tck/test_example.py`:

```python
import pytest
from ...adapters.example.connector import ExampleConnector

class TestExampleConnector:
    # Vendor-specific tests
    pass
```

### 5. Run Golden Tests

```bash
make test-connector VENDOR=example
```

All golden contract tests must pass!

### 6. Generate Documentation

```bash
make generate-docs VENDOR=example
```

## Testing Guidelines

### Unit Tests

- Test individual functions/methods
- Mock external dependencies
- Aim for >95% coverage

### Integration Tests

- Test with real services (in dev environment)
- Test error scenarios
- Test performance

### Golden Contract Tests

- Never modify these without team discussion
- All connectors must pass 100%
- Add new tests for new universal features

## Security Guidelines

### Never Commit

- API keys or secrets
- Personal data
- Internal URLs or IPs

### Always Do

- Use environment variables for config
- Validate all inputs
- Handle errors gracefully
- Log security events

### Security Review

For PRs that:
- Handle authentication
- Process personal data
- Modify security controls
- Add new dependencies

Request a security review from the security team.

## Documentation

### Code Documentation

- Add docstrings to all public functions
- Include type hints
- Add usage examples

### API Documentation

- Update OpenAPI spec for API changes
- Include request/response examples
- Document error codes

### User Documentation

- Update README for major features
- Add to relevant guides
- Include screenshots if applicable

## Performance Guidelines

### Benchmarks

For performance-critical code:

```python
# Add benchmark
def benchmark_new_feature():
    # Your benchmark
    pass
```

### Performance Targets

- API response time < 200ms
- Memory usage < 512MB per pod
- CPU usage < 70% under normal load

## Review Process

1. **Automated Checks**: CI/CD runs tests, security scans
2. **Code Review**: At least one maintainer reviews
3. **Performance Review**: For performance-critical changes
4. **Security Review**: For security-related changes

## Release Process

1. PRs merged to `main`
2. Automated tests run
3. Docker images built
4. Deployed to staging
5. Integration tests run
6. Promoted to production

## Getting Help

- **Discord**: [Join our Discord](https://discord.gg/voicehive)
- **GitHub Issues**: For bugs and features
- **Email**: developers@voicehive-hotels.com

## Recognition

Contributors are recognized in:
- [CONTRIBUTORS.md](CONTRIBUTORS.md)
- Release notes
- Project documentation

Thank you for contributing to VoiceHive Hotels! 🎉
