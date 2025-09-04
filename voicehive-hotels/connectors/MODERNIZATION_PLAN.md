# Connector Framework Modernization Plan

Based on the latest FastAPI and Pydantic v2 best practices, here's a plan to modernize the connector framework.

## 1. Migrate to Pydantic BaseModel (Priority: HIGH)

### Current State
- Using `@dataclass` for domain models
- No validation beyond type hints
- No secret handling

### Target State
```python
from pydantic import BaseModel, Field, SecretStr, field_validator, ConfigDict
from typing import Annotated

class GuestProfile(BaseModel):
    model_config = ConfigDict(
        validate_assignment=True,
        str_strip_whitespace=True,
        use_enum_values=True
    )
    
    id: Optional[str] = None
    email: EmailStr
    phone: Annotated[str, Field(pattern=r'^\+?[1-9]\d{1,14}$')]
    first_name: Annotated[str, Field(min_length=1, max_length=50)]
    last_name: Annotated[str, Field(min_length=1, max_length=50)]
    
    @field_validator('email')
    @classmethod
    def validate_email(cls, v: str) -> str:
        # Additional validation/normalization
        return v.lower()
```

### Benefits
- Automatic validation on assignment
- Built-in serialization/deserialization
- Better error messages
- Field-level constraints

## 2. Use SecretStr for Sensitive Fields (Priority: HIGH)

### Current State
```python
config = {
    "client_secret": "plain-text-secret"  # Visible in logs!
}
```

### Target State
```python
from pydantic import BaseModel, SecretStr

class ConnectorConfig(BaseModel):
    hotel_id: str
    client_id: str
    client_secret: SecretStr
    api_key: Optional[SecretStr] = None
    
    model_config = ConfigDict(
        validate_assignment=True,
        extra='forbid'  # Reject unknown fields
    )

# Usage
config = ConnectorConfig(
    hotel_id="HOTEL01",
    client_id="client",
    client_secret="secret123"  # Automatically wrapped
)
print(config.client_secret)  # Shows: SecretStr('**********')
print(config.client_secret.get_secret_value())  # Actual value
```

## 3. FastAPI Dependency Injection Pattern (Priority: MEDIUM)

### Current State
```python
def get_connector(vendor: str, config: dict):
    factory = ConnectorFactory()
    return factory.create(vendor, config)
```

### Target State
```python
from fastapi import Depends
from typing import Annotated

# Dependency providers
async def get_vault_client() -> VaultClient:
    return get_vault_client()

async def get_connector_factory(
    vault: Annotated[VaultClient, Depends(get_vault_client)]
) -> ConnectorFactory:
    return ConnectorFactory(vault_client=vault)

# Type aliases for cleaner code
FactoryDep = Annotated[ConnectorFactory, Depends(get_connector_factory)]
VaultDep = Annotated[VaultClient, Depends(get_vault_client)]

# In API routes
@app.post("/reservations")
async def create_reservation(
    vendor: str,
    payload: ReservationDraft,
    factory: FactoryDep  # Injected automatically
):
    connector = factory.create(vendor, {"hotel_id": payload.hotel_id})
    return await connector.create_reservation(payload)
```

## 4. Add Model Validators (Priority: HIGH)

### Current State
- No cross-field validation
- Basic type checking only

### Target State
```python
from pydantic import model_validator

class ReservationDraft(BaseModel):
    arrival: date
    departure: date
    guest_count: int = Field(ge=1, le=10)
    room_type: str
    
    @model_validator(mode='after')
    def validate_dates(self) -> 'ReservationDraft':
        if self.departure <= self.arrival:
            raise ValueError('Departure must be after arrival')
        if self.arrival < date.today():
            raise ValueError('Cannot book past dates')
        if (self.departure - self.arrival).days > 365:
            raise ValueError('Reservation too long')
        return self
```

## 5. Settings Management with Pydantic (Priority: MEDIUM)

### Current State
- Configuration scattered across files
- No validation of environment variables

### Target State
```python
from pydantic_settings import BaseSettings, SettingsConfigDict

class ConnectorSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file='.env',
        env_prefix='VOICEHIVE_',
        case_sensitive=False
    )
    
    # Vault settings
    vault_addr: str = "http://vault:8200"
    vault_token: Optional[SecretStr] = None
    vault_mount_path: str = "voicehive"
    
    # Connector defaults
    default_timeout: int = Field(default=30, ge=5, le=300)
    max_retries: int = Field(default=3, ge=0, le=10)
    cache_ttl: int = Field(default=300, ge=0)
    
    # Feature flags
    use_vault: bool = True
    enable_pii_redaction: bool = True
    
    @field_validator('vault_addr')
    @classmethod
    def validate_vault_addr(cls, v: str) -> str:
        if not v.startswith(('http://', 'https://')):
            raise ValueError('Vault address must start with http:// or https://')
        return v.rstrip('/')

# Global settings instance
settings = ConnectorSettings()
```

## 6. Response Models with Proper Serialization (Priority: MEDIUM)

### Current State
- Manual dict conversion
- No automatic camelCase conversion

### Target State
```python
from pydantic import BaseModel, Field
from pydantic.alias_generators import to_camel

class APIResponse(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        use_enum_values=True,
        json_encoders={
            datetime: lambda v: v.isoformat(),
            Decimal: lambda v: float(v),
            SecretStr: lambda v: "***"  # Never serialize secrets
        }
    )

class AvailabilityResponse(APIResponse):
    hotel_id: str
    room_types: List[RoomType]
    availability_grid: Dict[date, Dict[str, int]] = Field(alias="availabilityGrid")
```

## 7. Async Context Managers (Priority: LOW)

### Current State
```python
connector = factory.create(vendor, config)
await connector.connect()
try:
    result = await connector.get_availability(...)
finally:
    await connector.disconnect()
```

### Target State
```python
# Already implemented but can be improved
async with factory.create(vendor, config) as connector:
    result = await connector.get_availability(...)
    # Auto cleanup
```

## Implementation Plan

### Phase 1 (Week 1)
1. Create Pydantic models for all domain objects
2. Add SecretStr to configuration
3. Implement model validators

### Phase 2 (Week 2)
1. Create ConnectorSettings with pydantic-settings
2. Update factory to use new models
3. Add comprehensive validation

### Phase 3 (Week 3)
1. Implement FastAPI dependency injection patterns
2. Create response models with proper serialization
3. Update documentation

### Testing Strategy
1. Ensure backward compatibility
2. Add validation tests for each model
3. Test serialization/deserialization
4. Performance benchmarks (Pydantic v2 is faster)

### Migration Checklist
- [ ] Convert all dataclasses to Pydantic BaseModel
- [ ] Add SecretStr for all sensitive fields
- [ ] Implement model_validators for business logic
- [ ] Create settings management with pydantic-settings
- [ ] Add FastAPI Dependencies for cleaner code
- [ ] Update tests to use new validation
- [ ] Update documentation

## Breaking Changes
- Models will require valid data (no more invalid emails)
- Configuration must pass validation
- Some field names might change (snake_case → camelCase in API)

## Benefits After Migration
1. **Better Security**: Secrets never logged
2. **Data Quality**: Invalid data rejected at boundaries
3. **Developer Experience**: Better error messages
4. **Performance**: Pydantic v2 is 5-50x faster
5. **Type Safety**: Full IDE support with Annotated
6. **API Consistency**: Automatic serialization
