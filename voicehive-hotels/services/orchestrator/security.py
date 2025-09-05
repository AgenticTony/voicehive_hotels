"""
Security utilities for VoiceHive Hotels Orchestrator
"""

from cryptography.fernet import Fernet

# Optional circuit breaker: provide no-op fallback if not installed
try:
    from circuitbreaker import circuit
except ImportError:
    def circuit(*args, **kwargs):
        def decorator(func):
            return func
        return decorator


# Encryption helper
class EncryptionService:
    def __init__(self):
        # In production, fetch from Vault
        self.key = Fernet.generate_key()
        self.fernet = Fernet(self.key)
    
    def encrypt(self, data: str) -> bytes:
        return self.fernet.encrypt(data.encode())
    
    def decrypt(self, encrypted_data: bytes) -> str:
        return self.fernet.decrypt(encrypted_data).decode()
