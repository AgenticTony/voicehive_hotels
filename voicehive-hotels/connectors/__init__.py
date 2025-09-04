"""
VoiceHive Hotels PMS Connector Package

This package provides a unified interface for integrating with various
Property Management Systems (PMS) through the 80/20 pattern:
- 80% common functionality in contracts and factory
- 20% vendor-specific adapters
"""

from .factory import (
    get_connector,
    list_available_connectors,
    get_connector_metadata,
    get_capability_matrix,
    find_connectors_with_capability,
    register_connector,
    ConnectorFactory,
    ConnectorRegistry,
    ConnectorStatus,
    ConnectorMetadata
)

from .contracts import (
    PMSConnector,
    BaseConnector,
    PMSError,
    AuthenticationError,
    RateLimitError,
    ValidationError,
    NotFoundError,
    Capabilities,
    # Domain models
    RoomType,
    AvailabilityGrid,
    RateQuote,
    GuestProfile,
    ReservationDraft,
    ReservationPatch,
    Reservation
)

__all__ = [
    # Factory functions
    "get_connector",
    "list_available_connectors",
    "get_connector_metadata",
    "get_capability_matrix",
    "find_connectors_with_capability",
    "register_connector",
    # Factory classes
    "ConnectorFactory",
    "ConnectorRegistry",
    "ConnectorStatus",
    "ConnectorMetadata",
    # Contracts
    "PMSConnector",
    "BaseConnector",
    # Errors
    "PMSError",
    "AuthenticationError",
    "RateLimitError",
    "ValidationError",
    "NotFoundError",
    # Enums
    "Capabilities",
    # Domain models
    "RoomType",
    "AvailabilityGrid",
    "RateQuote", 
    "GuestProfile",
    "ReservationDraft",
    "ReservationPatch",
    "Reservation",
]
