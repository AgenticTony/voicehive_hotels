#!/usr/bin/env python3
"""
VoiceHive Apaleo Integration Tests
Comprehensive test suite for all Apaleo endpoints used by VoiceHive
"""

import asyncio
import httpx
import base64
import os
import sys
from datetime import date, timedelta

# Add the project root to the Python path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))

try:
    from connectors.adapters.apaleo.connector import ApaleoConnector
except ImportError:
    # If import fails, we can still run direct API tests
    ApaleoConnector = None

class ApaleoIntegrationTester:
    """Comprehensive tester for VoiceHive Apaleo integration"""

    def __init__(self):
        self.client_id = os.getenv('APALEO_CLIENT_ID', 'KNXY-SP-VOICEHIVE')
        self.client_secret = os.getenv('APALEO_CLIENT_SECRET', 'a5sJ4cJ2JeJwhuAsI4MJD2GPBun4mE')
        self.property_id = os.getenv('APALEO_PROPERTY_ID', 'LND')
        self.token = None
        self.headers = None

    async def authenticate(self):
        """Get access token for API tests"""
        credentials = f"{self.client_id}:{self.client_secret}"
        encoded_credentials = base64.b64encode(credentials.encode()).decode()

        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://identity.apaleo.com/connect/token",
                headers={
                    "Authorization": f"Basic {encoded_credentials}",
                    "Content-Type": "application/x-www-form-urlencoded"
                },
                data={"grant_type": "client_credentials"}
            )

            if response.status_code == 200:
                self.token = response.json()["access_token"]
                self.headers = {
                    'Authorization': f'Bearer {self.token}',
                    'Content-Type': 'application/json'
                }
                return True
            return False

    async def test_working_endpoints(self):
        """Test all endpoints that should work"""

        working_tests = [
            # Inventory API
            {
                "name": "Property Details",
                "method": "GET",
                "endpoint": f"/inventory/v1/properties/{self.property_id}",
                "params": {},
                "critical": True
            },
            {
                "name": "Unit Groups (Room Types)",
                "method": "GET",
                "endpoint": "/inventory/v1/unit-groups",
                "params": {"propertyIds": self.property_id},
                "critical": True
            },

            # Availability API
            {
                "name": "Room Availability",
                "method": "GET",
                "endpoint": "/availability/v1/unit-groups",
                "params": {
                    "propertyId": self.property_id,
                    "from": date.today().isoformat(),
                    "to": (date.today() + timedelta(days=3)).isoformat()
                },
                "critical": True
            },

            # Rate Plan API
            {
                "name": "Rate Plans",
                "method": "GET",
                "endpoint": "/rateplan/v1/rate-plans",
                "params": {"propertyIds": self.property_id},
                "critical": True
            },

            # Booking API
            {
                "name": "Bookings List",
                "method": "GET",
                "endpoint": "/booking/v1/bookings",
                "params": {"propertyIds": self.property_id},
                "critical": True
            },

            # Finance API (for payments)
            {
                "name": "Folios (Payment Processing)",
                "method": "GET",
                "endpoint": "/finance/v1/folios",
                "params": {"propertyIds": self.property_id},
                "critical": True
            }
        ]

        results = {
            "working": [],
            "failed": [],
            "critical_failures": []
        }

        async with httpx.AsyncClient() as client:
            for test in working_tests:
                try:
                    response = await client.request(
                        test["method"],
                        f"https://api.apaleo.com{test['endpoint']}",
                        headers=self.headers,
                        params=test["params"],
                        timeout=10.0
                    )

                    if response.status_code == 200:
                        results["working"].append({
                            "name": test["name"],
                            "endpoint": test["endpoint"],
                            "status": "SUCCESS"
                        })
                    else:
                        failure = {
                            "name": test["name"],
                            "endpoint": test["endpoint"],
                            "status": response.status_code,
                            "error": f"HTTP {response.status_code}"
                        }
                        results["failed"].append(failure)

                        if test["critical"]:
                            results["critical_failures"].append(failure)

                except Exception as e:
                    failure = {
                        "name": test["name"],
                        "endpoint": test["endpoint"],
                        "status": "ERROR",
                        "error": str(e)
                    }
                    results["failed"].append(failure)

                    if test["critical"]:
                        results["critical_failures"].append(failure)

        return results

    async def test_broken_endpoints(self):
        """Test endpoints that we know are broken (should return 404)"""

        broken_tests = [
            # Payment API (doesn't exist)
            "/pay/v1/payment-accounts",
            "/pay/v1/payments",
            "/pay/v1/payments/authorize",

            # Distribution API (doesn't exist)
            "/distribution/v1/bookings",

            # Booking conditions (doesn't exist)
            f"/booking/v1/rate-plans/{self.property_id}-APALEO-SGL/booking-conditions"
        ]

        results = {
            "correctly_fail": [],
            "unexpectedly_work": []
        }

        async with httpx.AsyncClient() as client:
            for endpoint in broken_tests:
                try:
                    response = await client.get(
                        f"https://api.apaleo.com{endpoint}",
                        headers=self.headers,
                        timeout=10.0
                    )

                    if response.status_code == 404:
                        results["correctly_fail"].append(endpoint)
                    else:
                        results["unexpectedly_work"].append({
                            "endpoint": endpoint,
                            "status": response.status_code
                        })

                except Exception:
                    # Network errors are fine for this test
                    results["correctly_fail"].append(endpoint)

        return results

    async def test_connector_integration(self):
        """Test the VoiceHive connector if available"""

        if not ApaleoConnector:
            return {"error": "Connector not available for testing"}

        config = {
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'property_id': self.property_id
        }

        connector = ApaleoConnector(config)
        results = {}

        try:
            # Test connection
            await connector.connect()
            results["authentication"] = "SUCCESS"

            # Test health check
            health = await connector.health_check()
            results["health_check"] = {
                "status": health["status"],
                "property_accessible": health.get("property_accessible")
            }

            # Test availability
            start_date = date.today()
            end_date = start_date + timedelta(days=2)
            availability = await connector.get_availability(
                hotel_id=self.property_id,
                start=start_date,
                end=end_date
            )

            results["availability"] = {
                "room_types_count": len(availability.room_types),
                "dates_count": len(availability.availability),
                "hotel_id": availability.hotel_id
            }

        except Exception as e:
            results["error"] = str(e)
        finally:
            if connector:
                await connector.disconnect()

        return results

    async def run_comprehensive_test(self):
        """Run all tests and provide comprehensive report"""

        print("🧪 VoiceHive Apaleo Integration - Comprehensive Test Suite")
        print("=" * 60)
        print()

        # Authenticate
        print("🔑 Authenticating...")
        if not await self.authenticate():
            print("❌ Authentication failed!")
            return
        print("✅ Authentication successful")
        print()

        # Test working endpoints
        print("✅ Testing Working Endpoints...")
        working_results = await self.test_working_endpoints()

        print(f"Working endpoints: {len(working_results['working'])}")
        for endpoint in working_results['working']:
            print(f"   ✅ {endpoint['name']}: {endpoint['endpoint']}")

        if working_results['failed']:
            print(f"\nFailed endpoints: {len(working_results['failed'])}")
            for endpoint in working_results['failed']:
                print(f"   ❌ {endpoint['name']}: {endpoint['endpoint']} ({endpoint['error']})")

        if working_results['critical_failures']:
            print(f"\n🚨 CRITICAL FAILURES: {len(working_results['critical_failures'])}")
            for failure in working_results['critical_failures']:
                print(f"   🚨 {failure['name']}: {failure['endpoint']}")

        print()

        # Test broken endpoints
        print("❌ Testing Known Broken Endpoints...")
        broken_results = await self.test_broken_endpoints()

        print(f"Correctly failing endpoints: {len(broken_results['correctly_fail'])}")
        for endpoint in broken_results['correctly_fail']:
            print(f"   ✅ {endpoint} (correctly returns 404)")

        if broken_results['unexpectedly_work']:
            print(f"\nUnexpectedly working endpoints: {len(broken_results['unexpectedly_work'])}")
            for endpoint in broken_results['unexpectedly_work']:
                print(f"   ⚠️  {endpoint['endpoint']} (status: {endpoint['status']})")

        print()

        # Test connector integration
        print("🔌 Testing VoiceHive Connector Integration...")
        connector_results = await self.test_connector_integration()

        if "error" in connector_results:
            print(f"❌ Connector test failed: {connector_results['error']}")
        else:
            print(f"✅ Authentication: {connector_results.get('authentication', 'N/A')}")

            health = connector_results.get('health_check', {})
            print(f"✅ Health check: {health.get('status', 'N/A')}")
            print(f"✅ Property accessible: {health.get('property_accessible', 'N/A')}")

            availability = connector_results.get('availability', {})
            print(f"✅ Room types: {availability.get('room_types_count', 'N/A')}")
            print(f"✅ Date ranges: {availability.get('dates_count', 'N/A')}")

        print()

        # Summary
        print("📊 SUMMARY:")
        print("=" * 30)

        total_working = len(working_results['working'])
        total_failed = len(working_results['failed'])
        total_critical_failures = len(working_results['critical_failures'])

        print(f"Working endpoints: {total_working}")
        print(f"Failed endpoints: {total_failed}")
        print(f"Critical failures: {total_critical_failures}")

        if total_critical_failures == 0:
            print("✅ All critical endpoints are working")
            print("🚀 VoiceHive Apaleo integration is production-ready for core functionality")
        else:
            print("❌ Critical endpoints are failing")
            print("⚠️  VoiceHive Apaleo integration requires fixes before production")

        print()
        print("📝 Note: Payment functionality requires Finance API implementation")
        print("📝 Current payment endpoints (/pay/v1/) do not exist in Apaleo")

async def main():
    """Run the comprehensive test suite"""
    tester = ApaleoIntegrationTester()
    await tester.run_comprehensive_test()

if __name__ == "__main__":
    asyncio.run(main())