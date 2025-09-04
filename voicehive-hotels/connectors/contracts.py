"""
VoiceHive Hotels PMS Connector Contracts
Universal interface that all PMS adapters must implement
"""

from typing import Protocol, Optional, List, Dict, Any, AsyncIterator
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from dataclasses import dataclass
from abc import ABC, abstractmethod
import logging


# Domain Models (vendor-agnostic)
@dataclass
class RoomType:
    code: str
    name: str
    description: Optional[str]
    max_occupancy: int
    base_occupancy: int
    amenities: List[str]


@dataclass
class AvailabilityGrid:
    hotel_id: str
    room_types: List[RoomType]
    availability: Dict[date, Dict[str, int]]  # date -> room_type_code -> count
    restrictions: Dict[date, Dict[str, Any]]  # min_stay, closed_arrival, etc


@dataclass
class RateQuote:
    room_type: str
    rate_code: str
    currency: str
    total_amount: Decimal
    breakdown: Dict[date, Decimal]
    taxes: Decimal
    fees: Decimal
    cancellation_policy: str


@dataclass
class GuestProfile:
    id: Optional[str]
    email: Optional[str]
    phone: Optional[str]
    first_name: str
    last_name: str
    nationality: Optional[str]
    language: Optional[str]
    vip_status: Optional[str]
    preferences: Dict[str, Any]
    gdpr_consent: bool
    marketing_consent: bool


@dataclass
class ReservationDraft:
    hotel_id: str
    arrival: date
    departure: date
    room_type: str
    rate_code: str
    guest_count: int
    guest: GuestProfile
    special_requests: Optional[str]
    payment_method: Optional[str]


@dataclass
class ReservationPatch:
    arrival: Optional[date] = None
    departure: Optional[date] = None
    room_type: Optional[str] = None
    guest_count: Optional[int] = None
    special_requests: Optional[str] = None


@dataclass
class Reservation:
    id: str
    confirmation_number: str
    status: str  # confirmed, cancelled, checked_in, checked_out
    hotel_id: str
    arrival: date
    departure: date
    room_type: str
    rate_code: str
    total_amount: Decimal
    guest: GuestProfile
    created_at: datetime
    modified_at: datetime


# Error types
class PMSError(Exception):
    """Base exception for PMS operations"""

    pass


class AuthenticationError(PMSError):
    """Failed to authenticate with PMS"""

    pass


class RateLimitError(PMSError):
    """Rate limit exceeded"""

    retry_after: Optional[int] = None


class ValidationError(PMSError):
    """Invalid data provided to PMS"""

    field: Optional[str] = None


class NotFoundError(PMSError):
    """Resource not found in PMS"""

    pass


# Main Protocol
class PMSConnector(Protocol):
    """
    Universal PMS connector interface.
    All methods should be async for consistency.
    """

    @property
    def vendor_name(self) -> str:
        """Return the PMS vendor name (e.g., 'opera', 'mews', 'apaleo')"""
        ...

    @property
    def capabilities(self) -> Dict[str, bool]:
        """Return capability matrix for this connector"""
        ...

    async def health_check(self) -> Dict[str, Any]:
        """Check if PMS connection is healthy"""
        ...

    # Availability Operations
    async def get_availability(
        self, hotel_id: str, start: date, end: date, room_type: Optional[str] = None
    ) -> AvailabilityGrid:
        """Get room availability for date range"""
        ...

    # Rate Operations
    async def quote_rate(
        self,
        hotel_id: str,
        room_type: str,
        rate_code: str,
        arrival: date,
        departure: date,
        guest_count: int,
        currency: str = "EUR",
    ) -> RateQuote:
        """Get rate quote for specific stay"""
        ...

    # Reservation Operations
    async def create_reservation(self, payload: ReservationDraft) -> Reservation:
        """Create new reservation"""
        ...

    async def get_reservation(
        self, reservation_id: str, by_confirmation: bool = False
    ) -> Reservation:
        """Retrieve reservation by ID or confirmation number"""
        ...

    async def modify_reservation(
        self, reservation_id: str, changes: ReservationPatch
    ) -> Reservation:
        """Modify existing reservation"""
        ...

    async def cancel_reservation(self, reservation_id: str, reason: str) -> None:
        """Cancel reservation with reason"""
        ...

    # Guest Operations
    async def search_guest(
        self,
        email: Optional[str] = None,
        phone: Optional[str] = None,
        last_name: Optional[str] = None,
    ) -> List[GuestProfile]:
        """Search for guest profiles"""
        ...

    async def get_guest_profile(self, guest_id: str) -> GuestProfile:
        """Get specific guest profile"""
        ...

    async def upsert_guest_profile(self, profile: GuestProfile) -> GuestProfile:
        """Create or update guest profile"""
        ...

    # Streaming operations (for large datasets)
    async def stream_arrivals(
        self, hotel_id: str, date: date
    ) -> AsyncIterator[Reservation]:
        """Stream today's arrivals"""
        ...

    async def stream_in_house(self, hotel_id: str) -> AsyncIterator[Reservation]:
        """Stream current in-house guests"""
        ...


# Base implementation with common functionality
class BaseConnector(ABC):
    """Base class with common functionality for all connectors"""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self._client = None
        self._rate_limiter = None

        # Set up secure logging with PII redaction
        try:
            from connectors.utils.logging import ConnectorLogger

            self.logger = ConnectorLogger(
                name=f"{self.__class__.__module__}.{self.__class__.__name__}",
                vendor=getattr(self, "vendor_name", "unknown"),
                hotel_id=config.get("hotel_id"),
            )
        except ImportError:
            # Fallback to standard logging with basic PII protection
            self.logger = logging.getLogger(
                f"{self.__class__.__module__}.{self.__class__.__name__}"
            )
            try:
                from connectors.utils import setup_logging_redaction

                setup_logging_redaction(self.logger)
            except ImportError:
                self.logger.warning(
                    "PII redaction not available. Install presidio for GDPR compliance."
                )

        # Generate correlation ID for this instance
        self._correlation_id = None

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()

    @abstractmethod
    async def connect(self):
        """Establish connection to PMS"""
        pass

    @abstractmethod
    async def disconnect(self):
        """Clean up connections"""
        pass

    async def with_retry(self, func, *args, max_retries=3, **kwargs):
        """Common retry logic with exponential backoff"""
        import asyncio
        from random import uniform

        for attempt in range(max_retries):
            try:
                return await func(*args, **kwargs)
            except RateLimitError as e:
                if attempt == max_retries - 1:
                    raise
                wait_time = e.retry_after or (2**attempt + uniform(0, 1))
                await asyncio.sleep(wait_time)
            except (AuthenticationError, ValidationError):
                raise  # Don't retry these
            except Exception:
                if attempt == max_retries - 1:
                    raise
                await asyncio.sleep(2**attempt)

    def normalize_date(self, date_input) -> date:
        """Normalize various date formats to Python date"""
        if isinstance(date_input, date):
            return date_input
        if isinstance(date_input, datetime):
            return date_input.date()
        # String parsing
        from dateutil import parser

        return parser.parse(date_input).date()

    def normalize_amount(self, amount: Any, currency: str) -> Decimal:
        """Normalize monetary amounts to Decimal"""
        if isinstance(amount, str):
            amount = amount.replace(",", "")
        return Decimal(str(amount)).quantize(Decimal("0.01"))


# Capability definitions
class Capabilities(Enum):
    """Standard capability flags"""

    AVAILABILITY = "availability"
    RATES = "rates"
    RESERVATIONS = "reservations"
    MODIFY_RESERVATION = "modify_reservation"
    CANCEL_RESERVATION = "cancel_reservation"
    GUEST_PROFILES = "guest_profiles"
    WEBHOOKS = "webhooks"
    REAL_TIME_SYNC = "real_time_sync"
    MULTI_PROPERTY = "multi_property"
    PAYMENT_PROCESSING = "payment_processing"
    HOUSEKEEPING = "housekeeping"
    POS_INTEGRATION = "pos_integration"


# Testing utilities
class MockConnector(BaseConnector):
    """Mock connector for testing"""

    vendor_name = "mock"
    capabilities = {cap.value: True for cap in Capabilities}

    async def connect(self):
        pass

    async def disconnect(self):
        pass

    async def health_check(self) -> Dict[str, Any]:
        return {"status": "healthy", "version": "mock-1.0"}

    async def get_availability(self, *args, **kwargs) -> AvailabilityGrid:
        # Return mock data
        return AvailabilityGrid(
            hotel_id="MOCK01",
            room_types=[
                RoomType("STD", "Standard Room", "Cozy room", 2, 2, ["wifi", "tv"]),
                RoomType(
                    "DLX",
                    "Deluxe Room",
                    "Spacious room",
                    3,
                    2,
                    ["wifi", "tv", "minibar"],
                ),
            ],
            availability={},
            restrictions={},
        )

    # Implement other methods with mock data...
