"""
Comprehensive Input Validation Middleware for VoiceHive Hotels
Provides security-focused input validation using Pydantic with configurable rules
"""

import re
import json
from typing import Any, Dict, List, Optional, Union, Set
from datetime import datetime
from pydantic import BaseModel, Field, validator, ValidationError
from fastapi import Request, HTTPException, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from logging_adapter import get_safe_logger

logger = get_safe_logger("orchestrator.input_validation")


class ValidationConfig(BaseModel):
    """Configuration for input validation rules"""
    
    # String validation
    max_string_length: int = Field(default=10000, ge=1, le=100000)
    min_string_length: int = Field(default=0, ge=0)
    
    # Numeric validation
    max_integer: int = Field(default=2147483647)
    min_integer: int = Field(default=-2147483648)
    max_float: float = Field(default=1e10)
    min_float: float = Field(default=-1e10)
    
    # Collection validation
    max_array_length: int = Field(default=1000, ge=1, le=10000)
    max_object_depth: int = Field(default=10, ge=1, le=20)
    max_object_keys: int = Field(default=100, ge=1, le=1000)
    
    # Content validation
    allowed_content_types: List[str] = Field(default=[
        "application/json",
        "application/x-www-form-urlencoded",
        "multipart/form-data",
        "text/plain"
    ])
    
    # Security patterns (blocked patterns)
    blocked_patterns: List[str] = Field(default=[
        r"<script[^>]*>.*?</script>",  # XSS
        r"javascript:",  # JavaScript URLs
        r"on\w+\s*=",  # Event handlers
        r"eval\s*\(",  # Code evaluation
        r"exec\s*\(",  # Code execution
        r"system\s*\(",  # System calls
        r"\.\.\/",  # Path traversal
        r"union\s+select",  # SQL injection
        r"drop\s+table",  # SQL injection
        r"insert\s+into",  # SQL injection
        r"delete\s+from",  # SQL injection
    ])
    
    # File upload validation
    max_file_size: int = Field(default=10485760)  # 10MB
    allowed_file_extensions: List[str] = Field(default=[
        ".txt", ".json", ".csv", ".pdf", ".png", ".jpg", ".jpeg"
    ])
    
    # Rate limiting for validation
    max_requests_per_minute: int = Field(default=1000)
    
    # Endpoint-specific overrides
    endpoint_overrides: Dict[str, Dict[str, Any]] = Field(default_factory=dict)


class SecurityValidator:
    """Security-focused input validator"""
    
    def __init__(self, config: ValidationConfig):
        self.config = config
        self.compiled_patterns = [
            re.compile(pattern, re.IGNORECASE | re.DOTALL)
            for pattern in config.blocked_patterns
        ]
    
    def validate_string(self, value: str, field_name: str = "field") -> str:
        """Validate string input for security issues"""
        if not isinstance(value, str):
            raise ValueError(f"{field_name} must be a string")
        
        # Length validation
        if len(value) > self.config.max_string_length:
            raise ValueError(f"{field_name} exceeds maximum length of {self.config.max_string_length}")
        
        if len(value) < self.config.min_string_length:
            raise ValueError(f"{field_name} below minimum length of {self.config.min_string_length}")
        
        # Security pattern validation
        for pattern in self.compiled_patterns:
            if pattern.search(value):
                logger.warning(
                    "security_pattern_detected",
                    field=field_name,
                    pattern=pattern.pattern,
                    value_preview=value[:100]
                )
                raise ValueError(f"{field_name} contains potentially malicious content")
        
        return value
    
    def validate_number(self, value: Union[int, float], field_name: str = "field") -> Union[int, float]:
        """Validate numeric input"""
        if isinstance(value, int):
            if value > self.config.max_integer or value < self.config.min_integer:
                raise ValueError(f"{field_name} outside allowed integer range")
        elif isinstance(value, float):
            if value > self.config.max_float or value < self.config.min_float:
                raise ValueError(f"{field_name} outside allowed float range")
        else:
            raise ValueError(f"{field_name} must be a number")
        
        return value
    
    def validate_array(self, value: List[Any], field_name: str = "field") -> List[Any]:
        """Validate array input"""
        if not isinstance(value, list):
            raise ValueError(f"{field_name} must be an array")
        
        if len(value) > self.config.max_array_length:
            raise ValueError(f"{field_name} exceeds maximum array length of {self.config.max_array_length}")
        
        # Recursively validate array elements
        validated = []
        for i, item in enumerate(value):
            validated.append(self.validate_value(item, f"{field_name}[{i}]"))
        
        return validated
    
    def validate_object(self, value: Dict[str, Any], field_name: str = "field", depth: int = 0) -> Dict[str, Any]:
        """Validate object input with depth checking"""
        if not isinstance(value, dict):
            raise ValueError(f"{field_name} must be an object")
        
        if depth > self.config.max_object_depth:
            raise ValueError(f"{field_name} exceeds maximum nesting depth of {self.config.max_object_depth}")
        
        if len(value) > self.config.max_object_keys:
            raise ValueError(f"{field_name} exceeds maximum keys limit of {self.config.max_object_keys}")
        
        # Validate keys and values
        validated = {}
        for key, val in value.items():
            # Validate key
            validated_key = self.validate_string(str(key), f"{field_name}.{key}")
            # Validate value
            validated_value = self.validate_value(val, f"{field_name}.{key}", depth + 1)
            validated[validated_key] = validated_value
        
        return validated
    
    def validate_value(self, value: Any, field_name: str = "field", depth: int = 0) -> Any:
        """Validate any value recursively"""
        if value is None:
            return value
        elif isinstance(value, str):
            return self.validate_string(value, field_name)
        elif isinstance(value, (int, float)):
            return self.validate_number(value, field_name)
        elif isinstance(value, list):
            return self.validate_array(value, field_name)
        elif isinstance(value, dict):
            return self.validate_object(value, field_name, depth)
        elif isinstance(value, bool):
            return value
        else:
            # Convert other types to string and validate
            return self.validate_string(str(value), field_name)


class InputValidationMiddleware(BaseHTTPMiddleware):
    """FastAPI middleware for comprehensive input validation"""
    
    def __init__(self, app, config: Optional[ValidationConfig] = None):
        super().__init__(app)
        self.config = config or ValidationConfig()
        self.validator = SecurityValidator(self.config)
        
        # Paths to skip validation (health checks, metrics, etc.)
        self.skip_paths = {
            "/healthz",
            "/health",
            "/metrics",
            "/docs",
            "/openapi.json",
            "/redoc"
        }
    
    async def dispatch(self, request: Request, call_next) -> Response:
        """Process request through validation middleware"""
        
        # Skip validation for certain paths
        if request.url.path in self.skip_paths:
            return await call_next(request)
        
        # Skip validation for GET requests (query params handled separately)
        if request.method == "GET":
            return await self._validate_query_params(request, call_next)
        
        try:
            # Validate content type
            content_type = request.headers.get("content-type", "").split(";")[0]
            if content_type and content_type not in self.config.allowed_content_types:
                logger.warning(
                    "invalid_content_type",
                    content_type=content_type,
                    path=request.url.path,
                    method=request.method
                )
                return JSONResponse(
                    status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                    content={
                        "error": {
                            "code": "INVALID_CONTENT_TYPE",
                            "message": f"Content type '{content_type}' not allowed",
                            "allowed_types": self.config.allowed_content_types
                        }
                    }
                )
            
            # Validate request body for POST/PUT/PATCH
            if request.method in ["POST", "PUT", "PATCH"]:
                await self._validate_request_body(request)
            
            # Continue to next middleware/handler
            response = await call_next(request)
            return response
            
        except ValidationError as e:
            logger.warning(
                "input_validation_failed",
                path=request.url.path,
                method=request.method,
                errors=str(e)
            )
            return JSONResponse(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                content={
                    "error": {
                        "code": "VALIDATION_ERROR",
                        "message": "Input validation failed",
                        "details": e.errors() if hasattr(e, 'errors') else str(e)
                    }
                }
            )
        except ValueError as e:
            logger.warning(
                "input_security_violation",
                path=request.url.path,
                method=request.method,
                error=str(e)
            )
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={
                    "error": {
                        "code": "SECURITY_VIOLATION",
                        "message": str(e)
                    }
                }
            )
        except Exception as e:
            logger.error(
                "input_validation_error",
                path=request.url.path,
                method=request.method,
                error=str(e)
            )
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={
                    "error": {
                        "code": "VALIDATION_ERROR",
                        "message": "Input validation failed"
                    }
                }
            )
    
    async def _validate_query_params(self, request: Request, call_next) -> Response:
        """Validate query parameters for GET requests"""
        try:
            for key, value in request.query_params.items():
                self.validator.validate_string(key, f"query_param_key_{key}")
                if isinstance(value, str):
                    self.validator.validate_string(value, f"query_param_{key}")
            
            return await call_next(request)
            
        except ValueError as e:
            logger.warning(
                "query_param_validation_failed",
                path=request.url.path,
                error=str(e)
            )
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={
                    "error": {
                        "code": "INVALID_QUERY_PARAMS",
                        "message": str(e)
                    }
                }
            )
    
    async def _validate_request_body(self, request: Request):
        """Validate request body content"""
        try:
            # Read body
            body = await request.body()
            
            # Skip empty bodies
            if not body:
                return
            
            # Check body size
            if len(body) > self.config.max_file_size:
                raise ValueError(f"Request body exceeds maximum size of {self.config.max_file_size} bytes")
            
            # Parse and validate JSON bodies
            content_type = request.headers.get("content-type", "").split(";")[0]
            if content_type == "application/json":
                try:
                    json_data = json.loads(body)
                    self.validator.validate_value(json_data, "request_body")
                except json.JSONDecodeError as e:
                    raise ValueError(f"Invalid JSON format: {str(e)}")
            
            # For form data, validation happens in FastAPI's dependency injection
            
        except Exception as e:
            # Re-raise as ValueError for consistent handling
            if isinstance(e, ValueError):
                raise
            else:
                raise ValueError(f"Request body validation failed: {str(e)}")


# Pydantic models for common validation scenarios
class SecureBaseModel(BaseModel):
    """Base model with security validations"""
    
    class Config:
        # Prevent extra fields
        extra = "forbid"
        # Validate assignment
        validate_assignment = True
        # Use enum values
        use_enum_values = True
    
    @validator('*', pre=True)
    def validate_strings(cls, v):
        """Apply string validation to all string fields"""
        if isinstance(v, str):
            validator = SecurityValidator(ValidationConfig())
            return validator.validate_string(v)
        return v


class SecureStringField(str):
    """String field with security validation"""
    
    @classmethod
    def __get_validators__(cls):
        yield cls.validate
    
    @classmethod
    def validate(cls, v):
        if not isinstance(v, str):
            raise TypeError('string required')
        
        validator = SecurityValidator(ValidationConfig())
        return validator.validate_string(v)


# Configuration loader
def load_validation_config(config_path: Optional[str] = None) -> ValidationConfig:
    """Load validation configuration from file or environment"""
    
    if config_path:
        try:
            import yaml
            with open(config_path, 'r') as f:
                config_data = yaml.safe_load(f)
            return ValidationConfig(**config_data.get('input_validation', {}))
        except Exception as e:
            logger.warning(f"Failed to load validation config from {config_path}: {e}")
    
    # Load from environment variables
    config_data = {}
    
    # String validation
    if max_len := os.getenv('VALIDATION_MAX_STRING_LENGTH'):
        config_data['max_string_length'] = int(max_len)
    
    # Array validation  
    if max_array := os.getenv('VALIDATION_MAX_ARRAY_LENGTH'):
        config_data['max_array_length'] = int(max_array)
    
    # Object validation
    if max_depth := os.getenv('VALIDATION_MAX_OBJECT_DEPTH'):
        config_data['max_object_depth'] = int(max_depth)
    
    return ValidationConfig(**config_data)


# Example usage and testing
if __name__ == "__main__":
    # Test the validator
    config = ValidationConfig()
    validator = SecurityValidator(config)
    
    # Test cases
    test_cases = [
        ("normal string", "Hello World"),
        ("xss attempt", "<script>alert('xss')</script>"),
        ("sql injection", "'; DROP TABLE users; --"),
        ("path traversal", "../../../etc/passwd"),
        ("javascript url", "javascript:alert('xss')"),
        ("large string", "x" * 20000),
        ("normal object", {"name": "John", "age": 30}),
        ("nested object", {"user": {"profile": {"settings": {"theme": "dark"}}}}),
        ("large array", list(range(2000))),
    ]
    
    for test_name, test_value in test_cases:
        try:
            result = validator.validate_value(test_value)
            print(f"✓ {test_name}: PASSED")
        except ValueError as e:
            print(f"✗ {test_name}: BLOCKED - {e}")
        except Exception as e:
            print(f"? {test_name}: ERROR - {e}")