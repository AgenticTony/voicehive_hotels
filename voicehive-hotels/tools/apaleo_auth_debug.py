#!/usr/bin/env python3
"""
Complete Apaleo Authorization Code Flow
Following Apaleo's exact instructions step-by-step
"""

import asyncio
import httpx
import webbrowser
import urllib.parse
import secrets
import os

class ApaleoAuthorizationFlow:
    def __init__(self):
        self.client_id = "KNXY-AC-VOICEHIVE_HOTELS_2"
        self.client_secret = "RHjJOaLWrDjVbdC5ufk9f8rJY9SKYb"
        self.redirect_uri = ""  # Empty as per Apaleo instructions

        # All scopes from Apaleo's example
        self.scopes = [
            "offline_access",
            "distribution:reservations.manage",
            "distribution:subscriptions.manage",
            "account.manage",
            "account.suspend",
            "accounting.read",
            "authorizations.manage",
            "authorizations.read",
            "availability.manage",
            "availability.read",
            "captcha-protection",
            "charges.delete",
            "companies.manage",
            "companies.read",
            "depositItems.manage",
            "deposits.manage",
            "deposits.read",
            "folios.manage",
            "folios.payment-with-charges",
            "folios.read",
            "invoices.manage",
            "invoices.read",
            "logs.read",
            "maintenances.manage",
            "maintenances.read",
            "offer-index.read",
            "offers.read",
            "operations.change-room-state",
            "operations.trigger-night-audit",
            "payment-accounts.manage",
            "payment-accounts.read",
            "payments.manage",
            "payments.read",
            "prepayment-notices.read",
            "rateplans.read-corporate",
            "rateplans.read-negotiated",
            "rates.manage",
            "rates.read",
            "reports.read",
            "reservations.force-manage",
            "reservations.manage",
            "reservations.read",
            "routings.create",
            "routings.manage",
            "routings.read",
            "servicegroups.create",
            "servicegroups.manage",
            "servicegroups.read",
            "setup.manage",
            "setup.read"
        ]

    def step_1_authorization_url(self):
        """Step 1: Generate authorization URL following Apaleo's exact format"""
        print("🔑 STEP 1: Authorization URL")
        print("=" * 60)

        # Generate random state for security
        state = secrets.token_urlsafe(16)

        # Build authorization URL exactly as Apaleo specified
        auth_params = {
            'response_type': 'code',
            'scope': ' '.join(self.scopes),
            'client_id': self.client_id,
            'redirect_uri': self.redirect_uri,
            'state': state
        }

        base_url = "https://identity.apaleo.com/connect/authorize"
        auth_url = f"{base_url}?{urllib.parse.urlencode(auth_params)}"

        print(f"Client ID: {self.client_id}")
        print(f"Scopes requested: {len(self.scopes)} scopes")
        print(f"State: {state}")
        print()
        print("Authorization URL:")
        print(auth_url)
        print()
        print("🌐 Opening browser...")

        # Open browser
        webbrowser.open(auth_url)

        print()
        print("👤 INSTRUCTIONS:")
        print("1. Browser opened to Apaleo login page")
        print("2. Log in with your Apaleo credentials")
        print("3. Review and grant permissions to the application")
        print("4. After authorization, copy the 'code' parameter from the URL")
        print("5. The page may show an error - that's normal with empty redirect_uri")
        print("6. Look for '?code=XXXXXX' in the browser address bar")
        print()

        return state

    async def step_2_exchange_code(self, authorization_code, state):
        """Step 2: Exchange authorization code for access token"""
        print("🔄 STEP 2: Exchange Code for Token")
        print("=" * 60)

        print(f"Authorization code: {authorization_code[:20]}...")
        print(f"State: {state}")
        print()

        # Prepare token exchange request exactly as Apaleo specified
        token_data = {
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'grant_type': 'authorization_code',
            'code': authorization_code,
            'redirect_uri': self.redirect_uri
        }

        async with httpx.AsyncClient() as client:
            try:
                print("🔄 Exchanging authorization code for access token...")

                response = await client.post(
                    "https://identity.apaleo.com/connect/token",
                    headers={'Content-Type': 'application/x-www-form-urlencoded'},
                    data=token_data
                )

                if response.status_code == 200:
                    token_response = response.json()

                    print("✅ SUCCESS: Token exchange completed!")
                    print()
                    print("Token details:")
                    print(f"  Access token: {token_response['access_token'][:30]}...")
                    print(f"  Token type: {token_response.get('token_type', 'N/A')}")
                    print(f"  Expires in: {token_response.get('expires_in', 'N/A')} seconds")
                    print(f"  Refresh token: {token_response.get('refresh_token', 'Not provided')[:30] + '...' if token_response.get('refresh_token') else 'Not provided'}")
                    print(f"  Granted scopes: {token_response.get('scope', 'Not specified')}")
                    print()

                    return token_response['access_token']

                else:
                    print(f"❌ FAILED: {response.status_code}")
                    print(f"Error: {response.text}")
                    return None

            except Exception as e:
                print(f"❌ ERROR: {e}")
                return None

    async def step_3_test_api_access(self, access_token):
        """Step 3: Test API access with Bearer token"""
        print("🧪 STEP 3: Test API Access")
        print("=" * 60)

        async with httpx.AsyncClient() as client:
            headers = {
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json'
            }

            # Test 1: Get current account (as specified by Apaleo)
            print("Test 1: Getting current account details...")
            try:
                response = await client.get(
                    "https://app.apaleo.com/api/account/v1/accounts/current",
                    headers=headers
                )

                if response.status_code == 200:
                    account = response.json()
                    print("✅ SUCCESS: Account details retrieved")
                    print(f"  Account ID: {account.get('id', 'N/A')}")
                    print(f"  Account name: {account.get('name', 'N/A')}")
                    print(f"  Account type: {account.get('accountType', 'N/A')}")
                else:
                    print(f"❌ FAILED: {response.status_code} - {response.text}")
            except Exception as e:
                print(f"❌ ERROR: {e}")

            print()

            # Test 2: Get properties (relevant for VoiceHive)
            print("Test 2: Getting properties...")
            try:
                response = await client.get(
                    "https://api.apaleo.com/inventory/v1/properties",
                    headers=headers
                )

                if response.status_code == 200:
                    properties = response.json()
                    print("✅ SUCCESS: Properties retrieved")
                    if 'properties' in properties:
                        for prop in properties['properties'][:3]:  # Show first 3
                            print(f"  Property: {prop.get('id')} - {prop.get('name', {}).get('en', 'No name')}")
                    else:
                        print(f"  Properties data: {properties}")
                else:
                    print(f"❌ FAILED: {response.status_code} - {response.text}")
            except Exception as e:
                print(f"❌ ERROR: {e}")

            print()

            # Test 3: Test availability for property LND
            print("Test 3: Testing availability for property LND...")
            try:
                from datetime import date, timedelta
                start_date = date.today() + timedelta(days=1)
                end_date = start_date + timedelta(days=2)

                response = await client.get(
                    "https://api.apaleo.com/availability/v1/availability",
                    headers=headers,
                    params={
                        'propertyIds': 'LND',
                        'from': start_date.isoformat(),
                        'to': end_date.isoformat()
                    }
                )

                if response.status_code == 200:
                    availability = response.json()
                    print("✅ SUCCESS: Availability data retrieved for LND")
                    print(f"  Date range: {start_date} to {end_date}")
                    print(f"  Response keys: {list(availability.keys())}")
                else:
                    print(f"❌ FAILED: {response.status_code} - {response.text}")
            except Exception as e:
                print(f"❌ ERROR: {e}")

async def main():
    """Main flow following Apaleo's instructions"""
    print("🏨 VoiceHive Hotels - Apaleo Authorization Code Flow")
    print("=" * 70)
    print("Following Apaleo's exact step-by-step instructions")
    print("=" * 70)
    print()

    flow = ApaleoAuthorizationFlow()

    # Step 1: Get authorization URL
    state = flow.step_1_authorization_url()

    # Wait for user to complete authorization
    print("⏳ Waiting for authorization completion...")
    authorization_code = input("Enter the authorization code from the browser URL: ").strip()

    if not authorization_code:
        print("❌ No authorization code provided. Exiting.")
        return

    # Step 2: Exchange code for token
    access_token = await flow.step_2_exchange_code(authorization_code, state)

    if not access_token:
        print("❌ Failed to get access token. Exiting.")
        return

    # Step 3: Test API access
    await flow.step_3_test_api_access(access_token)

    print()
    print("🎯 CONCLUSION:")
    print("If the tests above succeeded, your Apaleo integration is working!")
    print("However, this manual process is NOT suitable for automated voice assistant.")
    print("For production VoiceHive, you still need a Simple Client (Client Credentials).")

if __name__ == "__main__":
    asyncio.run(main())