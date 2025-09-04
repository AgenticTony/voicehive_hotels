#!/usr/bin/env python3
"""
Demonstration of Vault Integration for Secure Credential Management
Shows how PMS connectors use HashiCorp Vault instead of plain text configs
"""

import os
import sys
import json
import asyncio
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from connectors import get_connector, ConnectorFactory
from connectors.utils import DevelopmentVaultClient


def setup_dev_environment():
    """Set up development environment with sample secrets"""
    print("Setting up development environment...")

    # Create .secrets directory structure
    secrets_dir = Path(".secrets")

    # Create Apaleo credentials
    apaleo_dir = secrets_dir / "pms/apaleo/default"
    apaleo_dir.mkdir(parents=True, exist_ok=True)

    apaleo_creds = {
        "client_id": "demo-client-id",
        "client_secret": "demo-client-secret",
        "base_url": "https://api.apaleo.com",
        "property_id": "DEMO01",
    }

    with open(apaleo_dir / "api-credentials.json", "w") as f:
        json.dump(apaleo_creds, f, indent=2)

    print(f"✓ Created demo credentials at {apaleo_dir}")

    # Create hotel-specific credentials
    hotel01_dir = secrets_dir / "pms/apaleo/HOTEL01"
    hotel01_dir.mkdir(parents=True, exist_ok=True)

    hotel01_creds = {
        "client_id": "hotel01-client-id",
        "client_secret": "hotel01-client-secret",
        "base_url": "https://api.apaleo.com",
        "property_id": "HOTEL01",
    }

    with open(hotel01_dir / "api-credentials.json", "w") as f:
        json.dump(hotel01_creds, f, indent=2)

    print(f"✓ Created hotel-specific credentials at {hotel01_dir}")


async def demo_vault_integration():
    """Demonstrate Vault integration"""
    print("\n=== Vault Integration Demo ===\n")

    # Set development mode
    os.environ["VOICEHIVE_ENV"] = "development"

    print("1. Creating connector WITH Vault integration:")
    print("-" * 50)

    # Create connector with minimal config (credentials from Vault)
    config_with_vault = {
        "hotel_id": "HOTEL01"
        # No credentials needed - they come from Vault!
    }

    try:
        connector = get_connector("apaleo", config_with_vault)
        print("✓ Connector created successfully!")
        print(f"  - Client ID prefix: {connector.client_id[:8]}...")
        print(f"  - Base URL: {connector.base_url}")
        print(f"  - Property ID: {connector.property_id}")
        print("\nCredentials were securely loaded from Vault!")

    except Exception as e:
        print(f"✗ Failed to create connector: {e}")

    print("\n2. Creating connector WITHOUT Vault (fallback mode):")
    print("-" * 50)

    # Create factory without Vault
    factory_no_vault = ConnectorFactory(use_vault=False)

    # Now we need to provide all credentials
    config_without_vault = {
        "hotel_id": "HOTEL02",
        "client_id": "manual-client-id",
        "client_secret": "manual-client-secret",
        "base_url": "https://api.apaleo.com",
        "property_id": "HOTEL02",
    }

    connector2 = factory_no_vault.create("apaleo", config_without_vault)
    print("✓ Connector created with manual credentials")
    print(f"  - Client ID: {connector2.client_id}")
    print("\n⚠️  Warning: Credentials were passed in plain text!")

    print("\n3. Demonstrating credential precedence:")
    print("-" * 50)

    # Config with partial credentials - Vault fills in the rest
    partial_config = {
        "hotel_id": "HOTEL01",
        "property_id": "OVERRIDE-PROPERTY",  # This overrides Vault
    }

    connector3 = get_connector("apaleo", partial_config)
    print("✓ Connector created with merged credentials:")
    print(f"  - Property ID: {connector3.property_id} (from config)")
    print(f"  - Client ID prefix: {connector3.client_id[:8]}... (from Vault)")

    print("\n4. Vault encryption capabilities:")
    print("-" * 50)

    # Get Vault client
    vault_client = DevelopmentVaultClient()

    # Encrypt sensitive data
    sensitive_data = "Guest credit card: 4111-1111-1111-1111"
    encrypted = vault_client.encrypt_data(sensitive_data)
    print(f"Original: {sensitive_data}")
    print(f"Encrypted: {encrypted}")

    # Decrypt
    decrypted = vault_client.decrypt_data(encrypted)
    print(f"Decrypted: {decrypted}")

    print("\n✓ Data encryption/decryption working!")


def demo_production_setup():
    """Show production Vault setup"""
    print("\n=== Production Vault Setup ===\n")

    print("In production, credentials are stored in HashiCorp Vault:")
    print("")
    print("Vault Path Structure:")
    print("```")
    print("voicehive/")
    print("├── pms/")
    print("│   ├── apaleo/")
    print("│   │   ├── default/api-credentials")
    print("│   │   ├── HOTEL01/api-credentials")
    print("│   │   └── HOTEL02/api-credentials")
    print("│   ├── mews/")
    print("│   │   └── default/api-credentials")
    print("│   └── opera/")
    print("│       └── default/api-credentials")
    print("└── connectors/")
    print("    └── config")
    print("```")
    print("")
    print("Benefits:")
    print("✓ Centralized credential management")
    print("✓ Automatic rotation support")
    print("✓ Audit trail for all access")
    print("✓ Encryption at rest")
    print("✓ Fine-grained access policies")
    print("✓ No secrets in code or config files")

    print("\nKubernetes Integration:")
    print("- Pods authenticate using service accounts")
    print("- No static tokens needed")
    print("- Automatic token renewal")

    print("\nTo set up in production:")
    print("1. Deploy Vault using Helm chart")
    print("2. Run init-vault.sh to initialize")
    print("3. Run configure-policies.sh for access control")
    print("4. Run configure-pms-credentials.sh to load secrets")


async def main():
    """Run all demos"""
    print("=" * 70)
    print("VoiceHive Hotels - Vault Integration Demo")
    print("Secure Credential Management for PMS Connectors")
    print("=" * 70)

    # Set up dev environment
    setup_dev_environment()

    # Run demos
    await demo_vault_integration()
    demo_production_setup()

    print("\n" + "=" * 70)
    print("✅ Vault integration complete!")
    print("   No more hardcoded credentials in your code!")
    print("=" * 70)

    # Cleanup
    print("\nCleaning up demo secrets...")
    import shutil

    if Path(".secrets").exists():
        shutil.rmtree(".secrets")
        print("✓ Cleaned up .secrets directory")


if __name__ == "__main__":
    asyncio.run(main())
