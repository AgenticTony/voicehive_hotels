"""
Utility modules for PMS Connectors
"""

from .pii_redactor import (
    PIIRedactor,
    PIIRedactorFilter,
    get_default_redactor,
    redact_pii,
    setup_logging_redaction
)

from .logging import (
    ConnectorLogger,
    StructuredFormatter,
    log_performance,
    sanitize_url,
    correlation_id
)

from .vault_client import (
    VaultClient,
    AsyncVaultClient,
    DevelopmentVaultClient,
    get_vault_client,
    VaultError,
    VaultAuthError,
    VaultSecretNotFoundError
)

__all__ = [
    # PII Redaction
    "PIIRedactor",
    "PIIRedactorFilter", 
    "get_default_redactor",
    "redact_pii",
    "setup_logging_redaction",
    # Logging
    "ConnectorLogger",
    "StructuredFormatter",
    "log_performance",
    "sanitize_url",
    "correlation_id",
    # Vault
    "VaultClient",
    "AsyncVaultClient",
    "DevelopmentVaultClient",
    "get_vault_client",
    "VaultError",
    "VaultAuthError",
    "VaultSecretNotFoundError"
]
