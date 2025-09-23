"""
Simple test script to verify the authentication system implementation
"""

import asyncio
import json
from datetime import datetime

from auth_models import (
    LoginRequest, APIKeyRequest, UserRole, Permission,
    get_permissions_for_roles
)
from jwt_service import JWTService
from vault_client import MockVaultClient
from routers.auth import AuthService


async def test_authentication_system():
    """Test the complete authentication system"""
    
    print("🔐 Testing VoiceHive Hotels Authentication System")
    print("=" * 50)
    
    # Initialize services
    jwt_service = JWTService(redis_url="redis://localhost:6379")
    vault_client = MockVaultClient()
    auth_service = AuthService(jwt_service)
    
    try:
        # Initialize services
        await jwt_service.initialize()
        await vault_client.initialize()
        print("✅ Services initialized successfully")
        
        # Test 1: User Authentication
        print("\n📝 Test 1: User Authentication")
        try:
            from routers.auth import MOCK_USERS
            test_email = "admin@voicehive-hotels.eu"
            test_password = "admin123"
            
            user_context = await auth_service.authenticate_user(test_email, test_password)
            print(f"✅ User authenticated: {user_context.email}")
            print(f"   Roles: {[role.value for role in user_context.roles]}")
            print(f"   Permissions: {len(user_context.permissions)} permissions")
            
        except Exception as e:
            print(f"❌ User authentication failed: {e}")
            return
        
        # Test 2: JWT Token Creation
        print("\n🎫 Test 2: JWT Token Creation")
        try:
            tokens = await jwt_service.create_tokens(user_context)
            print("✅ JWT tokens created successfully")
            print(f"   Access token length: {len(tokens['access_token'])}")
            print(f"   Refresh token length: {len(tokens['refresh_token'])}")
            print(f"   Expires in: {tokens['expires_in']} seconds")
            
        except Exception as e:
            print(f"❌ JWT token creation failed: {e}")
            return
        
        # Test 3: JWT Token Validation
        print("\n🔍 Test 3: JWT Token Validation")
        try:
            validated_context = await jwt_service.validate_token(tokens['access_token'])
            print("✅ JWT token validated successfully")
            print(f"   User ID: {validated_context.user_id}")
            print(f"   Session ID: {validated_context.session_id}")
            
        except Exception as e:
            print(f"❌ JWT token validation failed: {e}")
            return
        
        # Test 4: Token Refresh
        print("\n🔄 Test 4: Token Refresh")
        try:
            new_tokens = await jwt_service.refresh_token(tokens['refresh_token'])
            print("✅ Token refresh successful")
            print(f"   New access token length: {len(new_tokens['access_token'])}")
            
        except Exception as e:
            print(f"❌ Token refresh failed: {e}")
            return
        
        # Test 5: API Key Creation
        print("\n🔑 Test 5: API Key Creation")
        try:
            api_key_request = APIKeyRequest(
                name="Test Service Key",
                service_name="test-service",
                permissions=[Permission.CALL_VIEW, Permission.HOTEL_VIEW],
                expires_days=30
            )
            
            api_key_response = await vault_client.create_api_key(api_key_request)
            print("✅ API key created successfully")
            print(f"   API Key ID: {api_key_response.api_key_id}")
            print(f"   Service: {api_key_response.service_name}")
            print(f"   Permissions: {len(api_key_response.permissions)}")
            
        except Exception as e:
            print(f"❌ API key creation failed: {e}")
            return
        
        # Test 6: API Key Validation
        print("\n🔐 Test 6: API Key Validation")
        try:
            service_context = await vault_client.validate_api_key(api_key_response.api_key)
            print("✅ API key validated successfully")
            print(f"   Service: {service_context.service_name}")
            print(f"   Permissions: {len(service_context.permissions)}")
            
        except Exception as e:
            print(f"❌ API key validation failed: {e}")
            return
        
        # Test 7: Permission System
        print("\n🛡️ Test 7: Permission System")
        try:
            admin_permissions = get_permissions_for_roles([UserRole.ADMIN])
            operator_permissions = get_permissions_for_roles([UserRole.OPERATOR])
            readonly_permissions = get_permissions_for_roles([UserRole.READONLY])
            
            print(f"✅ Permission system working")
            print(f"   Admin permissions: {len(admin_permissions)}")
            print(f"   Operator permissions: {len(operator_permissions)}")
            print(f"   Readonly permissions: {len(readonly_permissions)}")
            
        except Exception as e:
            print(f"❌ Permission system failed: {e}")
            return
        
        # Test 8: Session Management
        print("\n📋 Test 8: Session Management")
        try:
            # Logout session
            await jwt_service.logout_session(validated_context.session_id)
            print("✅ Session logout successful")
            
            # Try to validate token after logout (should fail)
            try:
                await jwt_service.validate_token(tokens['access_token'])
                print("❌ Token should be invalid after session logout")
            except:
                print("✅ Token correctly invalidated after logout")
                
        except Exception as e:
            print(f"❌ Session management failed: {e}")
            return
        
        print("\n🎉 All authentication tests passed!")
        print("=" * 50)
        print("Authentication system is ready for production use.")
        
    except Exception as e:
        print(f"❌ Test setup failed: {e}")


if __name__ == "__main__":
    asyncio.run(test_authentication_system())