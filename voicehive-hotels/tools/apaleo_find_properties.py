#!/usr/bin/env python3
"""
Find Available Properties in Apaleo Account
"""

import asyncio
import httpx
import base64
import os

async def find_properties():
    """Find all properties in the Apaleo account"""

    client_id = os.getenv('APALEO_CLIENT_ID', 'KNXY-SP-VOICEHIVE')
    client_secret = os.getenv('APALEO_CLIENT_SECRET', 'a5sJ4cJ2JeJwhuAsI4MJD2GPBun4mE')

    print("🔍 Finding Available Properties in Apaleo Account")
    print("=" * 60)
    print(f"Client ID: {client_id}")
    print()

    # Get access token
    credentials = f"{client_id}:{client_secret}"
    encoded_credentials = base64.b64encode(credentials.encode()).decode()

    async with httpx.AsyncClient() as client:
        # Step 1: Get access token
        print("🔑 Getting access token...")

        token_response = await client.post(
            "https://identity.apaleo.com/connect/token",
            headers={
                "Authorization": f"Basic {encoded_credentials}",
                "Content-Type": "application/x-www-form-urlencoded"
            },
            data={"grant_type": "client_credentials"}
        )

        if token_response.status_code != 200:
            print(f"❌ Failed to get token: {token_response.status_code}")
            return

        token = token_response.json()["access_token"]
        print("✅ Access token obtained")
        print()

        # Step 2: Get all properties
        print("🏨 Fetching all properties...")

        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json'
        }

        # Try different property endpoints
        endpoints = [
            "/inventory/v1/properties",
            "/properties/v1/properties",
            "/setup/v1/properties"
        ]

        for endpoint in endpoints:
            try:
                print(f"   Trying: {endpoint}")

                response = await client.get(
                    f"https://api.apaleo.com{endpoint}",
                    headers=headers
                )

                if response.status_code == 200:
                    properties = response.json()
                    print(f"   ✅ SUCCESS: {endpoint}")

                    if 'properties' in properties:
                        property_list = properties['properties']
                    else:
                        property_list = properties if isinstance(properties, list) else [properties]

                    print(f"   Found {len(property_list)} properties:")
                    print()

                    for i, prop in enumerate(property_list):
                        print(f"   🏨 Property {i+1}:")
                        # Handle both string and dict property formats
                        if isinstance(prop, str):
                            print(f"      ID: {prop}")
                            print(f"      Code: {prop}")
                            prop_id = prop
                        else:
                            prop_id = prop.get('id', 'N/A')
                            print(f"      ID: {prop_id}")
                            print(f"      Code: {prop.get('code', 'N/A')}")

                            # Handle name field
                            name = prop.get('name', 'N/A')
                            if isinstance(name, dict):
                                name = name.get('en', 'N/A')
                            print(f"      Name: {name}")

                            # Handle description
                            desc = prop.get('description', '')
                            if isinstance(desc, dict):
                                desc = desc.get('en', '')
                            if desc:
                                print(f"      Description: {desc[:100]}")

                            print(f"      Country: {prop.get('countryCode', 'N/A')}")
                            print(f"      Time Zone: {prop.get('timeZone', 'N/A')}")
                        print()

                    # Return the first property for testing
                    if property_list:
                        first_property = property_list[0]
                        property_id = first_property.get('id') or first_property.get('code')

                        print("🎯 RECOMMENDED ACTION:")
                        print(f"Update your .env file:")
                        print(f"APALEO_PROPERTY_ID={property_id}")
                        print()

                        return property_id

                    break

                else:
                    print(f"   ❌ {response.status_code}: {endpoint}")

            except Exception as e:
                print(f"   ❌ Error: {e}")

        # Step 3: Check account info if no properties found
        print("📋 Checking account information...")

        try:
            account_response = await client.get(
                "https://app.apaleo.com/api/account/v1/accounts/current",
                headers=headers
            )

            if account_response.status_code == 200:
                account = account_response.json()
                print("✅ Account details:")
                print(f"   Account ID: {account.get('id', 'N/A')}")
                print(f"   Account Name: {account.get('name', 'N/A')}")
                print(f"   Account Type: {account.get('accountType', 'N/A')}")
                print(f"   Account Code: {account.get('code', 'N/A')}")

                # Try using account code as property ID
                account_code = account.get('code')
                if account_code:
                    print()
                    print("🎯 TRY THIS:")
                    print(f"Use account code as property ID: {account_code}")
                    print(f"APALEO_PROPERTY_ID={account_code}")
                    return account_code

            else:
                print(f"❌ Account check failed: {account_response.status_code}")

        except Exception as e:
            print(f"❌ Account error: {e}")

if __name__ == "__main__":
    asyncio.run(find_properties())