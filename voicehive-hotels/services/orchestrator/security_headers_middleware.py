"""
Security Headers Middleware for VoiceHive Hotels
Implements comprehensive security headers for web application security
"""

from typing import Dict, List, Optional, Union
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response as StarletteResponse
from pydantic import BaseModel, Field

from logging_adapter import get_safe_logger

logger = get_safe_logger("orchestrator.security_headers")


class SecurityHeadersConfig(BaseModel):
    """Configuration for security headers"""
    
    # Content Security Policy
    csp_default_src: List[str] = Field(default=["'self'"])
    csp_script_src: List[str] = Field(default=["'self'", "'unsafe-inline'"])
    csp_style_src: List[str] = Field(default=["'self'", "'unsafe-inline'"])
    csp_img_src: List[str] = Field(default=["'self'", "data:", "https:"])
    csp_font_src: List[str] = Field(default=["'self'", "https:"])
    csp_connect_src: List[str] = Field(default=["'self'"])
    csp_media_src: List[str] = Field(default=["'self'"])
    csp_object_src: List[str] = Field(default=["'none'"])
    csp_frame_src: List[str] = Field(default=["'none'"])
    csp_base_uri: List[str] = Field(default=["'self'"])
    csp_form_action: List[str] = Field(default=["'self'"])
    csp_frame_ancestors: List[str] = Field(default=["'none'"])
    csp_report_uri: Optional[str] = None
    csp_report_to: Optional[str] = None
    
    # HTTP Strict Transport Security
    hsts_max_age: int = Field(default=31536000)  # 1 year
    hsts_include_subdomains: bool = Field(default=True)
    hsts_preload: bool = Field(default=True)
    
    # X-Frame-Options
    x_frame_options: str = Field(default="DENY")  # DENY, SAMEORIGIN, or ALLOW-FROM
    
    # X-Content-Type-Options
    x_content_type_options: str = Field(default="nosniff")
    
    # Referrer Policy
    referrer_policy: str = Field(default="strict-origin-when-cross-origin")
    
    # Permissions Policy (formerly Feature Policy)
    permissions_policy: Dict[str, List[str]] = Field(default_factory=lambda: {
        "geolocation": ["'none'"],
        "microphone": ["'self'"],
        "camera": ["'none'"],
        "payment": ["'none'"],
        "usb": ["'none'"],
        "magnetometer": ["'none'"],
        "gyroscope": ["'none'"],
        "accelerometer": ["'none'"]
    })
    
    # Cross-Origin Embedder Policy
    cross_origin_embedder_policy: str = Field(default="require-corp")
    
    # Cross-Origin Opener Policy
    cross_origin_opener_policy: str = Field(default="same-origin")
    
    # Cross-Origin Resource Policy
    cross_origin_resource_policy: str = Field(default="same-origin")
    
    # X-XSS-Protection (legacy, but still useful for older browsers)
    x_xss_protection: str = Field(default="1; mode=block")
    
    # Custom headers
    custom_headers: Dict[str, str] = Field(default_factory=dict)
    
    # Environment-specific overrides
    development_overrides: Dict[str, Union[str, List[str], Dict]] = Field(default_factory=dict)
    
    # Paths to exclude from certain headers
    exclude_paths: Dict[str, List[str]] = Field(default_factory=lambda: {
        "csp": ["/docs", "/redoc", "/openapi.json"],  # Swagger UI needs relaxed CSP
        "frame_options": ["/embed/*"],  # Allow embedding for specific paths
    })


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Middleware to add comprehensive security headers"""
    
    def __init__(self, app, config: Optional[SecurityHeadersConfig] = None, environment: str = "production"):
        super().__init__(app)
        self.config = config or SecurityHeadersConfig()
        self.environment = environment
        
        # Apply development overrides if in development
        if environment == "development" and self.config.development_overrides:
            self._apply_development_overrides()
    
    async def dispatch(self, request: Request, call_next) -> Response:
        """Add security headers to response"""
        
        # Process request
        response = await call_next(request)
        
        # Add security headers
        self._add_security_headers(request, response)
        
        return response
    
    def _add_security_headers(self, request: Request, response: Response):
        """Add all configured security headers to response"""
        
        path = request.url.path
        
        # Content Security Policy
        if not self._is_path_excluded("csp", path):
            csp_header = self._build_csp_header()
            if csp_header:
                response.headers["Content-Security-Policy"] = csp_header
        
        # HTTP Strict Transport Security (only for HTTPS)
        if request.url.scheme == "https" or self.environment == "production":
            hsts_header = self._build_hsts_header()
            response.headers["Strict-Transport-Security"] = hsts_header
        
        # X-Frame-Options
        if not self._is_path_excluded("frame_options", path):
            response.headers["X-Frame-Options"] = self.config.x_frame_options
        
        # X-Content-Type-Options
        response.headers["X-Content-Type-Options"] = self.config.x_content_type_options
        
        # Referrer Policy
        response.headers["Referrer-Policy"] = self.config.referrer_policy
        
        # Permissions Policy
        permissions_header = self._build_permissions_policy_header()
        if permissions_header:
            response.headers["Permissions-Policy"] = permissions_header
        
        # Cross-Origin Policies
        response.headers["Cross-Origin-Embedder-Policy"] = self.config.cross_origin_embedder_policy
        response.headers["Cross-Origin-Opener-Policy"] = self.config.cross_origin_opener_policy
        response.headers["Cross-Origin-Resource-Policy"] = self.config.cross_origin_resource_policy
        
        # X-XSS-Protection (legacy support)
        response.headers["X-XSS-Protection"] = self.config.x_xss_protection
        
        # Custom headers
        for header_name, header_value in self.config.custom_headers.items():
            response.headers[header_name] = header_value
        
        # Security-related headers for API responses
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        
        # Log security headers application
        logger.debug(
            "security_headers_applied",
            path=path,
            headers_count=len([h for h in response.headers.keys() if self._is_security_header(h)])
        )
    
    def _build_csp_header(self) -> str:
        """Build Content Security Policy header"""
        
        directives = []
        
        # Default source
        if self.config.csp_default_src:
            directives.append(f"default-src {' '.join(self.config.csp_default_src)}")
        
        # Script source
        if self.config.csp_script_src:
            directives.append(f"script-src {' '.join(self.config.csp_script_src)}")
        
        # Style source
        if self.config.csp_style_src:
            directives.append(f"style-src {' '.join(self.config.csp_style_src)}")
        
        # Image source
        if self.config.csp_img_src:
            directives.append(f"img-src {' '.join(self.config.csp_img_src)}")
        
        # Font source
        if self.config.csp_font_src:
            directives.append(f"font-src {' '.join(self.config.csp_font_src)}")
        
        # Connect source
        if self.config.csp_connect_src:
            directives.append(f"connect-src {' '.join(self.config.csp_connect_src)}")
        
        # Media source
        if self.config.csp_media_src:
            directives.append(f"media-src {' '.join(self.config.csp_media_src)}")
        
        # Object source
        if self.config.csp_object_src:
            directives.append(f"object-src {' '.join(self.config.csp_object_src)}")
        
        # Frame source
        if self.config.csp_frame_src:
            directives.append(f"frame-src {' '.join(self.config.csp_frame_src)}")
        
        # Base URI
        if self.config.csp_base_uri:
            directives.append(f"base-uri {' '.join(self.config.csp_base_uri)}")
        
        # Form action
        if self.config.csp_form_action:
            directives.append(f"form-action {' '.join(self.config.csp_form_action)}")
        
        # Frame ancestors
        if self.config.csp_frame_ancestors:
            directives.append(f"frame-ancestors {' '.join(self.config.csp_frame_ancestors)}")
        
        # Reporting
        if self.config.csp_report_uri:
            directives.append(f"report-uri {self.config.csp_report_uri}")
        
        if self.config.csp_report_to:
            directives.append(f"report-to {self.config.csp_report_to}")
        
        return "; ".join(directives)
    
    def _build_hsts_header(self) -> str:
        """Build HTTP Strict Transport Security header"""
        
        hsts_parts = [f"max-age={self.config.hsts_max_age}"]
        
        if self.config.hsts_include_subdomains:
            hsts_parts.append("includeSubDomains")
        
        if self.config.hsts_preload:
            hsts_parts.append("preload")
        
        return "; ".join(hsts_parts)
    
    def _build_permissions_policy_header(self) -> str:
        """Build Permissions Policy header"""
        
        if not self.config.permissions_policy:
            return ""
        
        policies = []
        for feature, allowlist in self.config.permissions_policy.items():
            if allowlist:
                allowlist_str = " ".join(allowlist)
                policies.append(f"{feature}=({allowlist_str})")
            else:
                policies.append(f"{feature}=()")
        
        return ", ".join(policies)
    
    def _is_path_excluded(self, header_type: str, path: str) -> bool:
        """Check if path is excluded from specific header type"""
        
        excluded_paths = self.config.exclude_paths.get(header_type, [])
        
        for excluded_path in excluded_paths:
            if excluded_path.endswith("*"):
                # Wildcard matching
                prefix = excluded_path[:-1]
                if path.startswith(prefix):
                    return True
            else:
                # Exact matching
                if path == excluded_path:
                    return True
        
        return False
    
    def _is_security_header(self, header_name: str) -> bool:
        """Check if header is a security-related header"""
        
        security_headers = {
            "content-security-policy",
            "strict-transport-security",
            "x-frame-options",
            "x-content-type-options",
            "referrer-policy",
            "permissions-policy",
            "cross-origin-embedder-policy",
            "cross-origin-opener-policy",
            "cross-origin-resource-policy",
            "x-xss-protection"
        }
        
        return header_name.lower() in security_headers
    
    def _apply_development_overrides(self):
        """Apply development environment overrides"""
        
        for key, value in self.config.development_overrides.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)
                logger.info(f"Applied development override for {key}")


# Predefined configurations for different environments
def get_production_security_config() -> SecurityHeadersConfig:
    """Get production-ready security headers configuration"""
    
    return SecurityHeadersConfig(
        # Strict CSP for production
        csp_default_src=["'self'"],
        csp_script_src=["'self'"],
        csp_style_src=["'self'"],
        csp_img_src=["'self'", "data:", "https://cdn.voicehive-hotels.eu"],
        csp_font_src=["'self'", "https://fonts.googleapis.com", "https://fonts.gstatic.com"],
        csp_connect_src=["'self'", "https://api.voicehive-hotels.eu"],
        csp_media_src=["'self'"],
        csp_object_src=["'none'"],
        csp_frame_src=["'none'"],
        csp_base_uri=["'self'"],
        csp_form_action=["'self'"],
        csp_frame_ancestors=["'none'"],
        
        # Strong HSTS
        hsts_max_age=31536000,  # 1 year
        hsts_include_subdomains=True,
        hsts_preload=True,
        
        # Strict frame options
        x_frame_options="DENY",
        
        # Strict referrer policy
        referrer_policy="strict-origin-when-cross-origin",
        
        # Restrictive permissions policy
        permissions_policy={
            "geolocation": ["'none'"],
            "microphone": ["'self'"],  # Needed for voice calls
            "camera": ["'none'"],
            "payment": ["'none'"],
            "usb": ["'none'"],
            "magnetometer": ["'none'"],
            "gyroscope": ["'none'"],
            "accelerometer": ["'none'"],
            "autoplay": ["'none'"],
            "encrypted-media": ["'none'"],
            "fullscreen": ["'none'"],
            "picture-in-picture": ["'none'"]
        },
        
        # Cross-origin policies
        cross_origin_embedder_policy="require-corp",
        cross_origin_opener_policy="same-origin",
        cross_origin_resource_policy="same-origin",
        
        # Custom security headers
        custom_headers={
            "X-Robots-Tag": "noindex, nofollow",  # Prevent search engine indexing
            "X-Permitted-Cross-Domain-Policies": "none",
            "X-Download-Options": "noopen",
            "Server": "VoiceHive-Hotels"  # Custom server header
        }
    )


def get_development_security_config() -> SecurityHeadersConfig:
    """Get development-friendly security headers configuration"""
    
    config = get_production_security_config()
    
    # Relax some restrictions for development
    config.development_overrides = {
        "csp_script_src": ["'self'", "'unsafe-inline'", "'unsafe-eval'"],  # Allow eval for dev tools
        "csp_style_src": ["'self'", "'unsafe-inline'"],  # Allow inline styles
        "csp_connect_src": ["'self'", "ws:", "wss:", "http://localhost:*", "https://localhost:*"],  # Allow local connections
        "hsts_max_age": 0,  # Disable HSTS in development
        "cross_origin_embedder_policy": "unsafe-none",  # Relax for dev tools
    }
    
    return config


def get_api_security_config() -> SecurityHeadersConfig:
    """Get security headers configuration optimized for API endpoints"""
    
    return SecurityHeadersConfig(
        # Minimal CSP for API
        csp_default_src=["'none'"],
        csp_frame_ancestors=["'none'"],
        
        # API-specific headers
        x_frame_options="DENY",
        x_content_type_options="nosniff",
        referrer_policy="no-referrer",
        
        # No permissions policy needed for API
        permissions_policy={},
        
        # Cross-origin policies for API
        cross_origin_embedder_policy="require-corp",
        cross_origin_opener_policy="same-origin",
        cross_origin_resource_policy="cross-origin",  # Allow cross-origin for API
        
        # Custom API headers
        custom_headers={
            "X-API-Version": "1.0",
            "X-Rate-Limit-Policy": "100/minute",
            "Cache-Control": "no-store, no-cache, must-revalidate, private"
        }
    )


# Example usage and testing
if __name__ == "__main__":
    # Test configurations
    prod_config = get_production_security_config()
    dev_config = get_development_security_config()
    api_config = get_api_security_config()
    
    print("Production CSP:", prod_config.csp_default_src)
    print("Development overrides:", dev_config.development_overrides)
    print("API permissions policy:", api_config.permissions_policy)
    
    # Test CSP header building
    middleware = SecurityHeadersMiddleware(None, prod_config)
    csp_header = middleware._build_csp_header()
    print("CSP Header:", csp_header[:100] + "..." if len(csp_header) > 100 else csp_header)