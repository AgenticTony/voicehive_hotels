"""
Apaleo PMS Connector
Quick win implementation - modern REST API with good documentation
"""

import os
from typing import Optional, List, Dict, Any, AsyncIterator
from datetime import date, datetime
from decimal import Decimal
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from ...contracts import (
    BaseConnector, PMSError, AuthenticationError, RateLimitError,
    ValidationError, NotFoundError, Capabilities,
    AvailabilityGrid, RoomType, RateQuote, GuestProfile,
    ReservationDraft, ReservationPatch, Reservation
)
from ...utils.logging import log_performance, sanitize_url

class ApaleoConnector(BaseConnector):
    """Apaleo PMS connector implementation"""
    
    vendor_name = "apaleo"
    
    # Full capabilities - Apaleo has excellent API coverage
    capabilities = {
        Capabilities.AVAILABILITY.value: True,
        Capabilities.RATES.value: True,
        Capabilities.RESERVATIONS.value: True,
        Capabilities.MODIFY_RESERVATION.value: True,
        Capabilities.CANCEL_RESERVATION.value: True,
        Capabilities.GUEST_PROFILES.value: True,
        Capabilities.WEBHOOKS.value: True,
        Capabilities.REAL_TIME_SYNC.value: True,
        Capabilities.MULTI_PROPERTY.value: True,
        Capabilities.PAYMENT_PROCESSING.value: False,
        Capabilities.HOUSEKEEPING.value: True,
        Capabilities.POS_INTEGRATION.value: False,
    }
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.base_url = config.get("base_url", "https://api.apaleo.com")
        self.client_id = config.get("client_id")
        self.client_secret = config.get("client_secret")
        self.property_id = config.get("property_id")  # Default property
        self._access_token = None
        self._token_expires_at = None
    
    async def connect(self):
        """Establish connection and get access token"""
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=30.0,
            headers={
                "User-Agent": "VoiceHive-Hotels/1.0",
                "Accept": "application/json",
            }
        )
        await self._authenticate()
    
    async def disconnect(self):
        """Clean up connection"""
        if self._client:
            await self._client.aclose()
    
    async def _authenticate(self):
        """Get OAuth2 access token"""
        auth_url = "https://identity.apaleo.com/connect/token"
        
        # Log authentication attempt without exposing credentials
        if hasattr(self.logger, 'info'):
            self.logger.info("Authenticating with Apaleo OAuth2", 
                           client_id_prefix=self.client_id[:4] + "..." if self.client_id else "None")
        
        try:
            response = await self._client.post(
                auth_url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "scope": "availability.read rates.read reservations.manage profiles.manage"
                }
            )
            response.raise_for_status()
            
            data = response.json()
            self._access_token = data["access_token"]
            self._token_expires_at = datetime.utcnow().timestamp() + data.get("expires_in", 3600)
            
            # Set auth header
            self._client.headers["Authorization"] = f"Bearer {self._access_token}"
            
            if hasattr(self.logger, 'info'):
                self.logger.info("Successfully authenticated with Apaleo",
                               expires_in=data.get("expires_in", 3600))
            
        except httpx.HTTPStatusError as e:
            if hasattr(self.logger, 'error'):
                self.logger.error(f"Authentication failed: {e.response.status_code}",
                                status_code=e.response.status_code)
            raise AuthenticationError(f"Failed to authenticate with Apaleo: {e}")
    
    async def _ensure_authenticated(self):
        """Ensure we have a valid token"""
        if not self._access_token or datetime.utcnow().timestamp() >= self._token_expires_at:
            await self._authenticate()
    
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
    async def _request(self, method: str, path: str, **kwargs):
        """Make authenticated request with retry logic"""
        await self._ensure_authenticated()
        
        # Log request details (URL is sanitized automatically)
        if hasattr(self.logger, 'log_api_call'):
            start_time = datetime.utcnow()
        
        try:
            response = await self._client.request(method, path, **kwargs)
            
            if response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", 60))
                if hasattr(self.logger, 'warning'):
                    self.logger.warning(f"Rate limit hit for {method} {path}", 
                                      retry_after=retry_after)
                raise RateLimitError(f"Rate limit exceeded, retry after {retry_after}s")
            
            response.raise_for_status()
            
            # Log successful request
            if hasattr(self.logger, 'log_api_call'):
                duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
                self.logger.log_api_call(
                    operation=f"{method} {path}",
                    status_code=response.status_code,
                    duration_ms=duration_ms
                )
            
            return response.json() if response.content else None
            
        except httpx.HTTPStatusError as e:
            # Log error
            if hasattr(self.logger, 'log_api_call'):
                duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
                self.logger.log_api_call(
                    operation=f"{method} {path}",
                    status_code=e.response.status_code,
                    duration_ms=duration_ms,
                    error=e
                )
            
            if e.response.status_code == 401:
                # Token might have expired, try re-authenticating
                await self._authenticate()
                raise AuthenticationError("Authentication failed")
            elif e.response.status_code == 404:
                raise NotFoundError(f"Resource not found: {path}")
            elif e.response.status_code == 422:
                raise ValidationError(f"Validation error: {e.response.text}")
            else:
                raise PMSError(f"API error: {e}")
    
    @log_performance("health_check")
    async def health_check(self) -> Dict[str, Any]:
        """Check Apaleo API health"""
        try:
            # Try to get property info as health check
            await self._request("GET", f"/properties/v1/properties/{self.property_id}")
            return {
                "status": "healthy",
                "vendor": "apaleo",
                "property_id": self.property_id,
                "timestamp": datetime.utcnow().isoformat()
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "vendor": "apaleo",
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }
    
    async def get_availability(
        self,
        hotel_id: str,
        start: date,
        end: date,
        room_type: Optional[str] = None
    ) -> AvailabilityGrid:
        """Get room availability"""
        property_id = hotel_id or self.property_id
        
        params = {
            "from": start.isoformat(),
            "to": end.isoformat(),
            "unitGroup": room_type  # Apaleo calls room types "unit groups"
        }
        
        # Get unit groups (room types)
        unit_groups = await self._request(
            "GET",
            f"/inventory/v1/unit-groups",
            params={"propertyId": property_id}
        )
        
        # Get availability
        availability_data = await self._request(
            "GET",
            f"/availability/v1/availability",
            params=params
        )
        
        # Map to our domain model
        room_types = []
        for ug in unit_groups.get("unitGroups", []):
            room_types.append(RoomType(
                code=ug["id"],
                name=ug["name"],
                description=ug.get("description"),
                max_occupancy=ug["maxPersons"],
                base_occupancy=ug.get("standardOccupancy", 2),
                amenities=[]  # Apaleo doesn't expose amenities in this endpoint
            ))
        
        # Parse availability grid
        availability_by_date = {}
        for avail in availability_data.get("availability", []):
            date_str = avail["date"]
            avail_date = self.normalize_date(date_str)
            
            if avail_date not in availability_by_date:
                availability_by_date[avail_date] = {}
            
            availability_by_date[avail_date][avail["unitGroupId"]] = avail["available"]
        
        return AvailabilityGrid(
            hotel_id=property_id,
            room_types=room_types,
            availability=availability_by_date,
            restrictions={}  # TODO: Parse restrictions
        )
    
    async def quote_rate(
        self,
        hotel_id: str,
        room_type: str,
        rate_code: str,
        arrival: date,
        departure: date,
        guest_count: int,
        currency: str = "EUR"
    ) -> RateQuote:
        """Get rate quote"""
        property_id = hotel_id or self.property_id
        
        params = {
            "from": arrival.isoformat(),
            "to": departure.isoformat(),
            "unitGroupId": room_type,
            "ratePlanId": rate_code,
            "adults": guest_count,
            "currency": currency
        }
        
        rates = await self._request(
            "GET",
            f"/rates/v1/rates",
            params=params
        )
        
        # Calculate total from daily rates
        total = Decimal("0.00")
        taxes = Decimal("0.00")
        breakdown = {}
        
        for rate in rates.get("rates", []):
            rate_date = self.normalize_date(rate["date"])
            amount = self.normalize_amount(rate["amount"]["grossAmount"], currency)
            tax = self.normalize_amount(rate["amount"]["taxes"]["amount"], currency)
            
            breakdown[rate_date] = amount
            total += amount
            taxes += tax
        
        return RateQuote(
            room_type=room_type,
            rate_code=rate_code,
            currency=currency,
            total_amount=total,
            breakdown=breakdown,
            taxes=taxes,
            fees=Decimal("0.00"),  # Apaleo includes fees in gross amount
            cancellation_policy="Free cancellation until 6 PM on arrival day"  # TODO: Get actual policy
        )
    
    async def create_reservation(self, payload: ReservationDraft) -> Reservation:
        """Create new reservation"""
        property_id = payload.hotel_id or self.property_id
        
        # Map to Apaleo's booking format
        booking_data = {
            "arrival": payload.arrival.isoformat(),
            "departure": payload.departure.isoformat(),
            "unitGroupId": payload.room_type,
            "ratePlanId": payload.rate_code,
            "adults": payload.guest_count,
            "primaryGuest": {
                "email": payload.guest.email,
                "phone": payload.guest.phone,
                "firstName": payload.guest.first_name,
                "lastName": payload.guest.last_name,
                "nationalityCountryCode": payload.guest.nationality
            },
            "comment": payload.special_requests,
            "propertyId": property_id
        }
        
        # Create the booking
        result = await self._request(
            "POST",
            "/booking/v1/bookings",
            json=booking_data
        )
        
        # Map response to our domain model
        return Reservation(
            id=result["id"],
            confirmation_number=result["bookingNumber"],
            status="confirmed",
            hotel_id=property_id,
            arrival=self.normalize_date(result["arrival"]),
            departure=self.normalize_date(result["departure"]),
            room_type=result["unitGroup"]["id"],
            rate_code=result["ratePlan"]["id"],
            total_amount=self.normalize_amount(
                result["totalGrossAmount"]["amount"],
                result["totalGrossAmount"]["currency"]
            ),
            guest=payload.guest,
            created_at=datetime.fromisoformat(result["created"].replace("Z", "+00:00")),
            modified_at=datetime.fromisoformat(result["modified"].replace("Z", "+00:00"))
        )
    
    async def get_reservation(
        self,
        reservation_id: str,
        by_confirmation: bool = False
    ) -> Reservation:
        """Get reservation details"""
        if by_confirmation:
            # Search by booking number
            bookings = await self._request(
                "GET",
                "/booking/v1/bookings",
                params={"bookingNumber": reservation_id}
            )
            if not bookings.get("bookings"):
                raise NotFoundError(f"No booking found with confirmation {reservation_id}")
            result = bookings["bookings"][0]
        else:
            # Get by ID
            result = await self._request(
                "GET",
                f"/booking/v1/bookings/{reservation_id}"
            )
        
        # Map guest from the reservation
        primary_guest = result.get("primaryGuest", {})
        guest = GuestProfile(
            id=None,  # Apaleo doesn't expose guest IDs
            email=primary_guest.get("email"),
            phone=primary_guest.get("phone"),
            first_name=primary_guest.get("firstName", ""),
            last_name=primary_guest.get("lastName", ""),
            nationality=primary_guest.get("nationalityCountryCode"),
            language=None,
            vip_status=None,
            preferences={},
            gdpr_consent=True,  # Assumed from booking
            marketing_consent=False
        )
        
        return Reservation(
            id=result["id"],
            confirmation_number=result["bookingNumber"],
            status=self._map_booking_status(result["status"]),
            hotel_id=result["property"]["id"],
            arrival=self.normalize_date(result["arrival"]),
            departure=self.normalize_date(result["departure"]),
            room_type=result["unitGroup"]["id"],
            rate_code=result["ratePlan"]["id"],
            total_amount=self.normalize_amount(
                result["totalGrossAmount"]["amount"],
                result["totalGrossAmount"]["currency"]
            ),
            guest=guest,
            created_at=datetime.fromisoformat(result["created"].replace("Z", "+00:00")),
            modified_at=datetime.fromisoformat(result["modified"].replace("Z", "+00:00"))
        )
    
    def _map_booking_status(self, apaleo_status: str) -> str:
        """Map Apaleo status to our standard status"""
        mapping = {
            "Tentative": "confirmed",
            "Confirmed": "confirmed", 
            "InHouse": "checked_in",
            "CheckedOut": "checked_out",
            "Canceled": "cancelled",
            "NoShow": "cancelled"
        }
        return mapping.get(apaleo_status, apaleo_status.lower())
    
    async def modify_reservation(
        self,
        reservation_id: str,
        changes: ReservationPatch
    ) -> Reservation:
        """Modify reservation"""
        # Build patch data
        patch_data = {}
        if changes.arrival:
            patch_data["arrival"] = changes.arrival.isoformat()
        if changes.departure:
            patch_data["departure"] = changes.departure.isoformat()
        if changes.room_type:
            patch_data["unitGroupId"] = changes.room_type
        if changes.guest_count:
            patch_data["adults"] = changes.guest_count
        if changes.special_requests:
            patch_data["comment"] = changes.special_requests
        
        # Apply modifications
        await self._request(
            "PATCH",
            f"/booking/v1/bookings/{reservation_id}",
            json=patch_data
        )
        
        # Return updated reservation
        return await self.get_reservation(reservation_id)
    
    async def cancel_reservation(
        self,
        reservation_id: str,
        reason: str
    ) -> None:
        """Cancel reservation"""
        await self._request(
            "PATCH",
            f"/booking/v1/bookings/{reservation_id}",
            json={
                "status": "Canceled",
                "cancellationReason": reason
            }
        )
    
    async def search_guest(
        self,
        email: Optional[str] = None,
        phone: Optional[str] = None,
        last_name: Optional[str] = None
    ) -> List[GuestProfile]:
        """Search for guest profiles"""
        # Apaleo doesn't have a dedicated guest API
        # We search through bookings instead
        params = {}
        if email:
            params["guestEmail"] = email
        if last_name:
            params["guestLastName"] = last_name
        
        bookings = await self._request(
            "GET",
            "/booking/v1/bookings",
            params=params
        )
        
        # Extract unique guests
        guests_map = {}
        for booking in bookings.get("bookings", []):
            guest = booking.get("primaryGuest", {})
            guest_key = (guest.get("email"), guest.get("phone"))
            
            if guest_key not in guests_map:
                guests_map[guest_key] = GuestProfile(
                    id=None,
                    email=guest.get("email"),
                    phone=guest.get("phone"),
                    first_name=guest.get("firstName", ""),
                    last_name=guest.get("lastName", ""),
                    nationality=guest.get("nationalityCountryCode"),
                    language=None,
                    vip_status=None,
                    preferences={},
                    gdpr_consent=True,
                    marketing_consent=False
                )
        
        return list(guests_map.values())
    
    async def get_guest_profile(self, guest_id: str) -> GuestProfile:
        """Get guest profile - not directly supported by Apaleo"""
        raise NotImplementedError("Apaleo doesn't expose individual guest profiles")
    
    async def upsert_guest_profile(self, profile: GuestProfile) -> GuestProfile:
        """Update guest profile - not directly supported by Apaleo"""
        # Guest data is only updated through bookings
        return profile
    
    async def stream_arrivals(
        self,
        hotel_id: str,
        arrival_date: date
    ) -> AsyncIterator[Reservation]:
        """Stream today's arrivals"""
        property_id = hotel_id or self.property_id
        
        # Get all arrivals for the date
        bookings = await self._request(
            "GET",
            "/booking/v1/bookings",
            params={
                "propertyId": property_id,
                "arrival": arrival_date.isoformat(),
                "status": "Confirmed,InHouse"
            }
        )
        
        # Convert to async generator
        for booking in bookings.get("bookings", []):
            yield await self.get_reservation(booking["id"])
    
    async def stream_in_house(
        self,
        hotel_id: str
    ) -> AsyncIterator[Reservation]:
        """Stream in-house guests"""
        property_id = hotel_id or self.property_id
        
        # Get all in-house bookings
        bookings = await self._request(
            "GET",
            "/booking/v1/bookings",
            params={
                "propertyId": property_id,
                "status": "InHouse"
            }
        )
        
        for booking in bookings.get("bookings", []):
            yield await self.get_reservation(booking["id"])
