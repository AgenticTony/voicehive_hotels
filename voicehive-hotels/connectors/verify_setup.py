#!/usr/bin/env python3
"""
Quick verification script to ensure the connector factory is set up correctly
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def verify_imports():
    """Verify all imports work correctly"""
    print("Testing imports...")

    try:
        from connectors import (
            get_connector,
            list_available_connectors,
            get_connector_metadata,
            get_capability_matrix,
            ConnectorFactory,
            PMSConnector,
            BaseConnector,
            PMSError,
        )

        print("✓ All imports successful")
        return True
    except ImportError as e:
        print(f"✗ Import error: {e}")
        return False


def verify_factory():
    """Verify factory basic functionality"""
    print("\nTesting factory...")

    try:
        from connectors import list_available_connectors, get_capability_matrix

        # List available connectors
        vendors = list_available_connectors()
        print(f"✓ Found {len(vendors)} available connectors: {vendors}")

        # Get capability matrix
        matrix = get_capability_matrix()
        print(f"✓ Capability matrix loaded with {len(matrix)} vendors")

        return True
    except Exception as e:
        print(f"✗ Factory error: {e}")
        return False


def verify_mock_connector():
    """Verify mock connector works"""
    print("\nTesting mock connector...")

    try:
        from connectors import (
            register_connector,
            get_connector,
            ConnectorMetadata,
            ConnectorStatus,
        )
        from connectors.contracts import MockConnector

        # Register mock
        register_connector(
            "test_mock",
            MockConnector,
            ConnectorMetadata(
                vendor="test_mock",
                name="Test Mock",
                version="1.0.0",
                status=ConnectorStatus.AVAILABLE,
                capabilities={"reservations": True},
                regions=["eu-west-1"],
                rate_limits={"requests_per_minute": 60},
                authentication="api_key",
            ),
        )

        # Create instance
        config = {"api_key": "test", "base_url": "test", "hotel_id": "TEST01"}

        connector = get_connector("test_mock", config)
        print(f"✓ Mock connector created: {connector.vendor_name}")

        return True
    except Exception as e:
        print(f"✗ Mock connector error: {e}")
        import traceback

        traceback.print_exc()
        return False


def verify_apaleo_discovery():
    """Verify Apaleo connector is discovered"""
    print("\nChecking Apaleo connector discovery...")

    try:
        from connectors import list_available_connectors, get_connector_metadata

        vendors = list_available_connectors()
        if "apaleo" in vendors:
            metadata = get_connector_metadata("apaleo")
            print(f"✓ Apaleo connector found: {metadata.name} v{metadata.version}")
            print(f"  Status: {metadata.status.value}")
            print(
                f"  Capabilities: {sum(1 for v in metadata.capabilities.values() if v)} supported"
            )
            return True
        else:
            print("✗ Apaleo connector not discovered")
            print("  Check if connectors/adapters/apaleo/__init__.py exists")
            return False
    except Exception as e:
        print(f"✗ Discovery error: {e}")
        return False


def main():
    """Run all verification tests"""
    print("=== VoiceHive Hotels Connector Factory Verification ===\n")

    results = []

    # Run tests
    results.append(("Imports", verify_imports()))
    results.append(("Factory", verify_factory()))
    results.append(("Mock Connector", verify_mock_connector()))
    results.append(("Apaleo Discovery", verify_apaleo_discovery()))

    # Summary
    print("\n=== Summary ===")
    passed = sum(1 for _, result in results if result)
    total = len(results)

    for test, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{test}: {status}")

    print(f"\nTotal: {passed}/{total} tests passed")

    if passed == total:
        print("\n🎉 All tests passed! Connector factory is ready.")
        sys.exit(0)
    else:
        print("\n❌ Some tests failed. Please check the errors above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
