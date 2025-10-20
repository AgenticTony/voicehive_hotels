"""
Apaleo PMS Connector
Quick win implementation - modern REST API with good documentation
"""

from typing import Optional, List, Dict, Any, AsyncIterator
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential
import redis.asyncio as aioredis

from ...contracts import (
    BaseConnector,
    PMSError,
    AuthenticationError,
    RateLimitError,
    ValidationError,
    NotFoundError,
    Capabilities,
    AvailabilityGrid,
    RoomType,
    RateQuote,
    GuestProfile,
    ReservationDraft,
    ReservationPatch,
    Reservation,
)
from ...utils.logging import log_performance

# Import circuit breaker from resilience infrastructure
try:
    import sys
    import os
    # Add orchestrator path to import circuit breaker
    sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'services', 'orchestrator'))
    from resilience.circuit_breaker import CircuitBreaker, CircuitBreakerConfig, CircuitBreakerOpenError, CircuitBreakerTimeoutError
except ImportError:
    # Fallback - circuit breaker not available
    CircuitBreaker = None
    CircuitBreakerConfig = None
    CircuitBreakerOpenError = Exception
    CircuitBreakerTimeoutError = Exception


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
        Capabilities.PAYMENT_PROCESSING.value: True,
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

        # Initialize circuit breakers if available
        self._circuit_breakers = {}
        if CircuitBreaker is not None:
            # Get Redis client from config (optional)
            redis_client = None
            if "redis_url" in config:
                try:
                    redis_client = aioredis.from_url(config["redis_url"])
                except Exception as e:
                    if hasattr(self.logger, "warning"):
                        self.logger.warning(f"Failed to connect to Redis for circuit breaker: {e}")

            # Circuit breaker for authentication
            auth_config = CircuitBreakerConfig(
                name="apaleo_auth",
                failure_threshold=3,  # Fail fast for auth issues
                recovery_timeout=120,  # 2 minutes recovery for auth
                timeout=15.0,  # Auth should be fast
                expected_exception=(httpx.HTTPStatusError, httpx.RequestError, AuthenticationError)
            )
            self._circuit_breakers["auth"] = CircuitBreaker(auth_config, redis_client)

            # Circuit breaker for API calls
            api_config = CircuitBreakerConfig(
                name="apaleo_api",
                failure_threshold=5,  # More tolerant for API calls
                recovery_timeout=60,  # 1 minute recovery for API
                timeout=30.0,  # API calls can take longer
                expected_exception=(httpx.HTTPStatusError, httpx.RequestError, PMSError, RateLimitError)
            )
            self._circuit_breakers["api"] = CircuitBreaker(api_config, redis_client)

            if hasattr(self.logger, "info"):
                self.logger.info("Apaleo circuit breakers initialized",
                               auth_threshold=auth_config.failure_threshold,
                               api_threshold=api_config.failure_threshold)

    async def connect(self):
        """Establish connection and get access token with optimized connection pooling"""
        # Configure connection limits based on official httpx documentation
        # Optimized for PMS API usage patterns - moderate concurrency with keepalive
        connection_limits = httpx.Limits(
            max_keepalive_connections=10,  # Keep 10 connections alive for reuse
            max_connections=25,            # Maximum total connections for PMS operations
            keepalive_expiry=30.0         # Keep connections alive for 30 seconds
        )

        # Create timeout configuration for different operation types
        timeout_config = httpx.Timeout(
            connect=10.0,    # Connection establishment timeout
            read=30.0,       # Read timeout for API responses
            write=10.0,      # Write timeout for API requests
            pool=5.0         # Pool acquisition timeout
        )

        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout_config,
            limits=connection_limits,
            headers={
                "User-Agent": "VoiceHive-Hotels/1.0",
                "Accept": "application/json",
                "Connection": "keep-alive",  # Enable connection reuse
            },
            # Enable HTTP/2 if supported by the PMS
            http2=True,
        )

        if hasattr(self.logger, "info"):
            self.logger.info(
                "apaleo_connection_pool_configured",
                max_keepalive=connection_limits.max_keepalive_connections,
                max_connections=connection_limits.max_connections,
                keepalive_expiry=connection_limits.keepalive_expiry,
                http2_enabled=True
            )

        await self._authenticate()

    async def disconnect(self):
        """Clean up connection"""
        if self._client:
            await self._client.aclose()

    async def _authenticate(self):
        """Get OAuth2 access token with circuit breaker protection"""
        import base64

        auth_url = "https://identity.apaleo.com/connect/token"

        # Log authentication attempt without exposing credentials
        if hasattr(self.logger, "info"):
            self.logger.info(
                "Authenticating with Apaleo OAuth2",
                client_id_prefix=self.client_id[:4] + "..."
                if self.client_id
                else "None",
            )

        async def _do_auth():
            """Inner authentication function for circuit breaker"""
            # Prepare Basic Authentication header as required by Apaleo
            credentials = f"{self.client_id}:{self.client_secret}"
            encoded_credentials = base64.b64encode(credentials.encode()).decode()

            response = await self._client.post(
                auth_url,
                headers={
                    "Authorization": f"Basic {encoded_credentials}",
                    "Content-Type": "application/x-www-form-urlencoded"
                },
                data={
                    "grant_type": "client_credentials",
                },
            )
            response.raise_for_status()

            data = response.json()
            self._access_token = data["access_token"]
            self._token_expires_at = datetime.now(timezone.utc).timestamp() + data.get(
                "expires_in", 3600
            )

            # Set auth header
            self._client.headers["Authorization"] = f"Bearer {self._access_token}"

            if hasattr(self.logger, "info"):
                self.logger.info(
                    "Successfully authenticated with Apaleo",
                    expires_in=data.get("expires_in", 3600),
                )

            return data

        try:
            # Use circuit breaker if available
            if "auth" in self._circuit_breakers:
                await self._circuit_breakers["auth"].call(_do_auth)
            else:
                await _do_auth()

        except CircuitBreakerOpenError as e:
            if hasattr(self.logger, "error"):
                self.logger.error("Authentication circuit breaker is open",
                                circuit_name=e.circuit_name,
                                next_attempt=e.next_attempt_time)
            raise AuthenticationError(f"Authentication service unavailable: {e}")

        except CircuitBreakerTimeoutError as e:
            if hasattr(self.logger, "error"):
                self.logger.error("Authentication timed out", error=str(e))
            raise AuthenticationError(f"Authentication timeout: {e}")

        except httpx.HTTPStatusError as e:
            if hasattr(self.logger, "error"):
                self.logger.error(
                    f"Authentication failed: {e.response.status_code}",
                    status_code=e.response.status_code,
                )
            raise AuthenticationError(f"Failed to authenticate with Apaleo: {e}")

        except Exception as e:
            if hasattr(self.logger, "error"):
                self.logger.error("Unexpected authentication error", error=str(e))
            raise AuthenticationError(f"Authentication error: {e}")

    async def _ensure_authenticated(self):
        """Ensure we have a valid token"""
        if (
            not self._access_token
            or datetime.now(timezone.utc).timestamp() >= self._token_expires_at
        ):
            await self._authenticate()

    @retry(
        stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10)
    )
    async def _request(self, method: str, path: str, **kwargs):
        """Make authenticated request with circuit breaker and retry logic"""
        await self._ensure_authenticated()

        async def _do_request():
            """Inner request function for circuit breaker"""
            # Log request details (URL is sanitized automatically)
            start_time = datetime.now(timezone.utc)

            try:
                response = await self._client.request(method, path, **kwargs)

                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", 60))
                    if hasattr(self.logger, "warning"):
                        self.logger.warning(
                            f"Rate limit hit for {method} {path}", retry_after=retry_after
                        )
                    e = RateLimitError(f"Rate limit exceeded, retry after {retry_after}s")
                    setattr(e, "retry_after", retry_after)
                    raise e

                response.raise_for_status()

                # Log successful request
                if hasattr(self.logger, "log_api_call"):
                    duration_ms = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
                    self.logger.log_api_call(
                        operation=f"{method} {path}",
                        status_code=response.status_code,
                        duration_ms=duration_ms,
                    )

                return response.json() if response.content else None

            except httpx.HTTPStatusError as e:
                # Log error
                if hasattr(self.logger, "log_api_call"):
                    duration_ms = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
                    self.logger.log_api_call(
                        operation=f"{method} {path}",
                        status_code=e.response.status_code,
                        duration_ms=duration_ms,
                        error=e,
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

        try:
            # Use circuit breaker if available, otherwise fallback to direct call
            if "api" in self._circuit_breakers:
                return await self._circuit_breakers["api"].call(_do_request)
            else:
                return await _do_request()

        except CircuitBreakerOpenError as e:
            if hasattr(self.logger, "error"):
                self.logger.error("Apaleo API circuit breaker is open",
                                circuit_name=e.circuit_name,
                                next_attempt=e.next_attempt_time,
                                operation=f"{method} {path}")
            raise PMSError(f"Apaleo API unavailable: {e}")

        except CircuitBreakerTimeoutError as e:
            if hasattr(self.logger, "error"):
                self.logger.error("Apaleo API request timed out",
                                error=str(e),
                                operation=f"{method} {path}")
            raise PMSError(f"Apaleo API timeout: {e}")

    async def get_circuit_breaker_stats(self) -> Dict[str, Any]:
        """Get circuit breaker statistics"""
        stats = {}
        if self._circuit_breakers:
            for name, breaker in self._circuit_breakers.items():
                try:
                    breaker_stats = await breaker.get_stats()
                    stats[name] = {
                        "state": breaker_stats.state.value,
                        "failure_count": breaker_stats.failure_count,
                        "success_count": breaker_stats.success_count,
                        "total_requests": breaker_stats.total_requests,
                        "total_failures": breaker_stats.total_failures,
                        "total_successes": breaker_stats.total_successes,
                        "last_failure_time": breaker_stats.last_failure_time.isoformat() if breaker_stats.last_failure_time else None,
                        "last_success_time": breaker_stats.last_success_time.isoformat() if breaker_stats.last_success_time else None,
                        "next_attempt_time": breaker_stats.next_attempt_time.isoformat() if breaker_stats.next_attempt_time else None,
                    }
                except Exception as e:
                    stats[name] = {"error": f"Failed to get stats: {e}"}
        return stats

    @log_performance("health_check")
    async def health_check(self) -> Dict[str, Any]:
        """Check Apaleo API health with circuit breaker information"""
        token_valid = bool(self._access_token) and (
            self._token_expires_at is not None
            and datetime.now(timezone.utc).timestamp() < self._token_expires_at
        )

        # Get circuit breaker statistics
        circuit_breaker_stats = await self.get_circuit_breaker_stats()

        try:
            # Try to get property info as health check using correct Inventory API endpoint
            await self._request("GET", f"/inventory/v1/properties/{self.property_id}")
            return {
                "status": "healthy",
                "vendor": "apaleo",
                "property_id": self.property_id,
                "property_accessible": True,
                "token_valid": token_valid,
                "circuit_breakers": circuit_breaker_stats,
                "circuit_breaker_enabled": len(self._circuit_breakers) > 0,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        except CircuitBreakerOpenError as e:
            return {
                "status": "degraded",
                "vendor": "apaleo",
                "error": f"Circuit breaker open: {e}",
                "property_accessible": False,
                "token_valid": token_valid,
                "circuit_breakers": circuit_breaker_stats,
                "circuit_breaker_enabled": len(self._circuit_breakers) > 0,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "vendor": "apaleo",
                "error": str(e),
                "property_accessible": False,
                "token_valid": token_valid,
                "circuit_breakers": circuit_breaker_stats,
                "circuit_breaker_enabled": len(self._circuit_breakers) > 0,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

    async def get_availability(
        self, hotel_id: str, start: date, end: date, room_type: Optional[str] = None
    ) -> AvailabilityGrid:
        """Get room availability using correct Apaleo availability endpoints"""
        property_id = hotel_id or self.property_id

        # Get unit groups (room types) using inventory endpoint for static data
        unit_groups = await self._request(
            "GET", "/inventory/v1/unit-groups", params={"propertyIds": property_id}
        )

        # Map to our domain model first
        room_types = []
        for ug in unit_groups.get("unitGroups", []):
            room_types.append(
                RoomType(
                    code=ug["id"],
                    name=ug["name"],
                    description=ug.get("description"),
                    max_occupancy=ug["maxPersons"],
                    base_occupancy=ug.get("standardOccupancy", 2),
                    amenities=[],  # Apaleo doesn't expose amenities in this endpoint
                )
            )

        # Use correct availability endpoint: /availability/v1/unit-groups
        # This endpoint uses date format, not datetime
        unit_groups_availability_params = {
            "propertyId": property_id,
            "from": start.isoformat(),
            "to": end.isoformat()
        }
        if room_type:
            unit_groups_availability_params["unitGroupIds"] = room_type

        try:
            # Get availability using correct endpoint
            availability_data = await self._request(
                "GET", "/availability/v1/unit-groups", params=unit_groups_availability_params
            )
        except (NotFoundError, PMSError) as e:
            # If availability endpoint fails, log warning and return empty availability
            if hasattr(self.logger, "warning"):
                self.logger.warning(
                    f"Availability endpoint failed, returning empty availability: {e}",
                    property_id=property_id
                )
            availability_data = {"timeSlices": []}

        # Parse availability grid from timeSlices format
        availability_by_date = {}

        # Process timeSlices data from /availability/v1/unit-groups
        for time_slice in availability_data.get("timeSlices", []):
            slice_from = time_slice.get("from")
            slice_to = time_slice.get("to")

            if not slice_from or not slice_to:
                continue

            # Parse dates from the time slice
            slice_start = self.normalize_date(slice_from)
            slice_end = self.normalize_date(slice_to)

            # Initialize dates in range if not already present
            current = slice_start
            while current <= slice_end and current <= end:
                if current >= start and current not in availability_by_date:
                    availability_by_date[current] = {}
                current = current + timedelta(days=1)

            # Process unit groups in this time slice
            for unit_group in time_slice.get("unitGroups", []):
                unit_group_id = unit_group.get("id")
                available_count = unit_group.get("available", 0)

                if unit_group_id:
                    # Apply availability to all dates in this time slice
                    current = slice_start
                    while current <= slice_end and current <= end:
                        if current >= start:
                            if current not in availability_by_date:
                                availability_by_date[current] = {}
                            availability_by_date[current][unit_group_id] = available_count
                        current = current + timedelta(days=1)

        # Ensure all dates in range have entries, even if empty
        current = start
        while current <= end:
            if current not in availability_by_date:
                availability_by_date[current] = {}
                # Set 0 availability for all room types if no data
                for room_type_obj in room_types:
                    availability_by_date[current][room_type_obj.code] = 0
            current = current + timedelta(days=1)

        # Log successful availability retrieval
        if hasattr(self.logger, "info"):
            total_slices = len(availability_data.get("timeSlices", []))
            date_count = len(availability_by_date)
            self.logger.info(
                "Retrieved availability using production endpoint",
                property_id=property_id,
                time_slices=total_slices,
                date_range_days=date_count,
                endpoint="/availability/v1/unit-groups"
            )

        # Get restrictions for the date range
        restrictions = await self._get_restrictions(property_id, start, end)

        return AvailabilityGrid(
            hotel_id=property_id,
            room_types=room_types,
            availability=availability_by_date,
            restrictions=restrictions,
        )

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
        """Get rate quote using official Apaleo endpoints"""
        property_id = hotel_id or self.property_id

        # Use official rate plan rates endpoint with correct parameters
        params = {
            "from": arrival.isoformat(),
            "to": departure.isoformat(),
            "propertyIds": property_id,
            "unitGroupIds": room_type,
            "adults": guest_count,
        }

        # Get rates from the official rate plan endpoint
        rates = await self._request(
            "GET",
            f"/rateplan/v1/rate-plans/{rate_code}/rates",
            params=params
        )

        # Calculate total from daily rates using official response format
        total = Decimal("0.00")
        taxes = Decimal("0.00")
        breakdown = {}

        # Process rates based on official API response structure
        if rates and "rates" in rates:
            for rate_entry in rates["rates"]:
                # Handle date range in rate entry
                rate_from = self.normalize_date(rate_entry.get("from", arrival.isoformat()))
                rate_to = self.normalize_date(rate_entry.get("to", departure.isoformat()))

                # Get the rate values - official API structure
                rate_values = rate_entry.get("values", [])
                if rate_values:
                    rate_value = rate_values[0]  # Take first rate value

                    # Extract amounts using official field names
                    total_amount = rate_value.get("totalGrossAmount", {})
                    base_amount = rate_value.get("baseAmount", {})
                    included_taxes = rate_value.get("includedTaxes", {})

                    # Calculate amounts
                    if total_amount:
                        amount = self.normalize_amount(
                            total_amount.get("amount", 0),
                            total_amount.get("currency", currency)
                        )
                    elif base_amount:
                        amount = self.normalize_amount(
                            base_amount.get("amount", 0),
                            base_amount.get("currency", currency)
                        )
                    else:
                        # Fallback for older format
                        amount = self.normalize_amount(
                            rate_entry.get("grossAmount", 0),
                            currency
                        )

                    # Calculate taxes
                    if included_taxes:
                        tax_amount = self.normalize_amount(
                            included_taxes.get("amount", 0),
                            included_taxes.get("currency", currency)
                        )
                    else:
                        # Fallback calculation
                        tax_amount = amount * Decimal("0.1")  # Estimate 10% tax

                    # Distribute amount across date range
                    current_date = rate_from
                    days_in_range = (rate_to - rate_from).days
                    if days_in_range <= 0:
                        days_in_range = 1

                    daily_amount = amount / days_in_range
                    daily_tax = tax_amount / days_in_range

                    while current_date < rate_to and current_date < departure:
                        if current_date >= arrival:
                            breakdown[current_date] = daily_amount
                            total += daily_amount
                            taxes += daily_tax
                        current_date += timedelta(days=1)

        return RateQuote(
            room_type=room_type,
            rate_code=rate_code,
            currency=currency,
            total_amount=total,
            breakdown=breakdown,
            taxes=taxes,
            fees=Decimal("0.00"),  # Apaleo includes fees in gross amount
            cancellation_policy=await self._get_cancellation_policy(property_id, rate_code, arrival, departure),
        )

    async def create_reservation(self, payload: ReservationDraft) -> Reservation:
        """Create new reservation"""
        property_id = payload.hotel_id or self.property_id

        # Map to Apaleo's booking format using official API structure
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
                "nationalityCountryCode": payload.guest.nationality,
            },
            "comment": payload.special_requests,
            "propertyId": property_id,  # Note: booking creation uses propertyId, not propertyIds
        }

        # Create the booking
        result = await self._request("POST", "/booking/v1/bookings", json=booking_data)

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
                result["totalGrossAmount"]["currency"],
            ),
            guest=payload.guest,
            created_at=datetime.fromisoformat(result["created"].replace("Z", "+00:00")),
            modified_at=datetime.fromisoformat(
                result["modified"].replace("Z", "+00:00")
            ),
        )

    async def get_reservation(
        self, reservation_id: str, by_confirmation: bool = False
    ) -> Reservation:
        """Get reservation details"""
        if by_confirmation:
            # Search by booking number
            bookings = await self._request(
                "GET", "/booking/v1/bookings", params={"bookingNumber": reservation_id}
            )
            if not bookings.get("bookings"):
                raise NotFoundError(
                    f"No booking found with confirmation {reservation_id}"
                )
            result = bookings["bookings"][0]
        else:
            # Get by ID
            result = await self._request(
                "GET", f"/booking/v1/bookings/{reservation_id}"
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
            marketing_consent=False,
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
                result["totalGrossAmount"]["currency"],
            ),
            guest=guest,
            created_at=datetime.fromisoformat(result["created"].replace("Z", "+00:00")),
            modified_at=datetime.fromisoformat(
                result["modified"].replace("Z", "+00:00")
            ),
        )

    def _map_booking_status(self, apaleo_status: str) -> str:
        """Map Apaleo status to our standard status"""
        mapping = {
            "Tentative": "confirmed",
            "Confirmed": "confirmed",
            "InHouse": "checked_in",
            "CheckedOut": "checked_out",
            "Canceled": "cancelled",
            "NoShow": "cancelled",
        }
        return mapping.get(apaleo_status, apaleo_status.lower())

    async def modify_reservation(
        self, reservation_id: str, changes: ReservationPatch
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
            "PATCH", f"/booking/v1/bookings/{reservation_id}", json=patch_data
        )

        # Return updated reservation
        return await self.get_reservation(reservation_id)

    async def cancel_reservation(self, reservation_id: str, reason: str) -> None:
        """Cancel reservation"""
        await self._request(
            "PATCH",
            f"/booking/v1/bookings/{reservation_id}",
            json={"status": "Canceled", "cancellationReason": reason},
        )

    async def search_guest(
        self,
        email: Optional[str] = None,
        phone: Optional[str] = None,
        last_name: Optional[str] = None,
    ) -> List[GuestProfile]:
        """Search for guest profiles"""
        # Apaleo doesn't have a dedicated guest API
        # We search through bookings instead
        params = {}
        if email:
            params["guestEmail"] = email
        if last_name:
            params["guestLastName"] = last_name

        bookings = await self._request("GET", "/booking/v1/bookings", params=params)

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
                    marketing_consent=False,
                )

        return list(guests_map.values())

    async def get_guest_profile(self, guest_id: str) -> GuestProfile:
        """Get guest profile - implemented via booking history search"""
        # Since Apaleo doesn't expose individual guest profiles,
        # we attempt to construct a profile from booking history
        try:
            # If guest_id is actually an email, search by email
            if "@" in guest_id:
                guests = await self.search_guest(email=guest_id)
                if guests:
                    return guests[0]

            # If guest_id is a phone number, search by phone
            if guest_id.startswith("+") or guest_id.replace("-", "").replace(" ", "").isdigit():
                guests = await self.search_guest(phone=guest_id)
                if guests:
                    return guests[0]

            # If guest_id looks like a name, search by last name
            if " " in guest_id:
                parts = guest_id.split()
                last_name = parts[-1]
                guests = await self.search_guest(last_name=last_name)
                # Find best match by comparing full names
                for guest in guests:
                    guest_full_name = f"{guest.first_name} {guest.last_name}".strip()
                    if guest_full_name.lower() == guest_id.lower():
                        return guest

            # Try searching by last name only
            guests = await self.search_guest(last_name=guest_id)
            if guests:
                return guests[0]

            # No guest found, raise NotFoundError instead of NotImplementedError
            raise NotFoundError(f"Guest profile not found for identifier: {guest_id}")

        except NotFoundError:
            raise
        except Exception as e:
            # Log the error but still raise NotFoundError for consistency
            if hasattr(self.logger, "warning"):
                self.logger.warning(
                    f"Error searching for guest profile: {e}",
                    guest_id=guest_id
                )
            raise NotFoundError(f"Could not retrieve guest profile for: {guest_id}")

    async def upsert_guest_profile(self, profile: GuestProfile) -> GuestProfile:
        """Update guest profile - not directly supported by Apaleo"""
        # Guest data is only updated through bookings
        return profile

    async def stream_arrivals(
        self, hotel_id: str, arrival_date: date
    ) -> AsyncIterator[Reservation]:
        """Stream today's arrivals"""
        property_id = hotel_id or self.property_id

        # Get all arrivals for the date using official API query parameters
        bookings = await self._request(
            "GET",
            "/booking/v1/bookings",
            params={
                "propertyIds": property_id,
                "arrival": arrival_date.isoformat(),
                "status": "Confirmed,InHouse",
            },
        )

        # Convert to async generator
        for booking in bookings.get("bookings", []):
            yield await self.get_reservation(booking["id"])

    async def stream_in_house(self, hotel_id: str) -> AsyncIterator[Reservation]:
        """Stream in-house guests"""
        property_id = hotel_id or self.property_id

        # Get all in-house bookings using official API query parameters
        bookings = await self._request(
            "GET",
            "/booking/v1/bookings",
            params={"propertyIds": property_id, "status": "InHouse"},
        )

        for booking in bookings.get("bookings", []):
            yield await self.get_reservation(booking["id"])

    async def _get_restrictions(self, property_id: str, start: date, end: date) -> Dict[str, Any]:
        """Get booking restrictions for the date range using official Apaleo endpoints"""
        try:
            # Get rate plan details first to identify available rate plans
            rate_plans = await self._request(
                "GET",
                f"/rateplan/v1/rate-plans",
                params={"propertyIds": property_id}
            )

            restrictions = {}
            current_date = start

            # Initialize restrictions for each date
            while current_date <= end:
                restrictions[current_date] = {
                    "min_stay": 1,
                    "max_stay": None,
                    "closed_to_arrival": False,
                    "closed_to_departure": False,
                    "stop_sell": False
                }
                current_date = current_date + timedelta(days=1)

            # Get restrictions for each rate plan
            if rate_plans and "ratePlans" in rate_plans:
                for rate_plan in rate_plans["ratePlans"]:
                    rate_plan_id = rate_plan.get("id")
                    if not rate_plan_id:
                        continue

                    try:
                        # Get rates with restrictions for this rate plan
                        rates_data = await self._request(
                            "GET",
                            f"/rateplan/v1/rate-plans/{rate_plan_id}/rates",
                            params={
                                "from": start.isoformat(),
                                "to": end.isoformat(),
                                "propertyIds": property_id
                            }
                        )

                        # Process rate data to extract restrictions
                        if rates_data and "rates" in rates_data:
                            for rate_entry in rates_data["rates"]:
                                rate_date_str = rate_entry.get("from")
                                if rate_date_str:
                                    rate_date = self.normalize_date(rate_date_str)

                                    # Check if date is in our range
                                    if start <= rate_date <= end and rate_date in restrictions:
                                        # Extract restrictions from rate data
                                        restrictions_data = rate_entry.get("restrictions", {})

                                        # Update restrictions based on official API response format
                                        if "minAdvanceBooking" in restrictions_data:
                                            restrictions[rate_date]["min_advance_booking"] = restrictions_data["minAdvanceBooking"]
                                        if "maxAdvanceBooking" in restrictions_data:
                                            restrictions[rate_date]["max_advance_booking"] = restrictions_data["maxAdvanceBooking"]
                                        if "closedOnArrival" in restrictions_data:
                                            restrictions[rate_date]["closed_to_arrival"] = restrictions_data["closedOnArrival"]
                                        if "closedOnDeparture" in restrictions_data:
                                            restrictions[rate_date]["closed_to_departure"] = restrictions_data["closedOnDeparture"]
                                        if "minLos" in restrictions_data:
                                            restrictions[rate_date]["min_stay"] = restrictions_data["minLos"]
                                        if "maxLos" in restrictions_data:
                                            restrictions[rate_date]["max_stay"] = restrictions_data["maxLos"]

                    except Exception as rate_plan_error:
                        # Log but continue with other rate plans
                        if hasattr(self.logger, "debug"):
                            self.logger.debug(
                                f"Could not fetch restrictions for rate plan {rate_plan_id}: {rate_plan_error}"
                            )
                        continue

            # Also check unit group availability for stop-sell status
            try:
                inventory_data = await self._request(
                    "GET",
                    "/availability/v1/unit-groups",
                    params={
                        "propertyId": property_id,
                        "from": start.isoformat(),
                        "to": end.isoformat()
                    }
                )

                # Process availability data for stop-sell indicators
                if inventory_data and "timeSlices" in inventory_data:
                    for time_slice in inventory_data["timeSlices"]:
                        slice_from = time_slice.get("from")
                        slice_to = time_slice.get("to")

                        if slice_from and slice_to:
                            slice_start = self.normalize_date(slice_from)
                            slice_end = self.normalize_date(slice_to)

                            # Check each date in this time slice
                            current_date = slice_start
                            while current_date <= slice_end and current_date <= end:
                                if current_date >= start and current_date in restrictions:
                                    # If total available across all unit groups is 0, consider it stop-sell
                                    total_available = sum(
                                        unit_group.get("available", 0)
                                        for unit_group in time_slice.get("unitGroups", [])
                                    )
                                    if total_available == 0:
                                        restrictions[current_date]["stop_sell"] = True
                                current_date += timedelta(days=1)

            except Exception as availability_error:
                # Log but continue - availability check is supplementary
                if hasattr(self.logger, "debug"):
                    self.logger.debug(f"Could not fetch availability for stop-sell check: {availability_error}")

            return restrictions

        except Exception as e:
            # If restrictions endpoint is not available or fails, return empty restrictions
            if hasattr(self.logger, "warning"):
                self.logger.warning(
                    f"Could not fetch restrictions: {e}",
                    property_id=property_id
                )
            return {}

    async def _get_cancellation_policy(self, property_id: str, rate_code: str, arrival: date, departure: date) -> str:
        """Get cancellation policy for a specific rate and dates using official Apaleo endpoints"""
        try:
            # Get rate plan details including cancellation policy
            rate_plan = await self._request(
                "GET",
                f"/rateplan/v1/rate-plans/{rate_code}",
                params={"propertyIds": property_id}
            )

            # Extract cancellation policy from rate plan using official API structure
            if rate_plan and "cancellationPolicy" in rate_plan:
                policy = rate_plan["cancellationPolicy"]

                # Parse Apaleo cancellation policy format based on official API
                if policy.get("isRefundable") is False:
                    return "Non-refundable - no cancellation allowed"
                elif policy.get("isRefundable") is True:
                    # Check for cancellation fee structure
                    fees = policy.get("fees", [])
                    if fees:
                        # Process cancellation fees in chronological order
                        fee_descriptions = []
                        for fee in fees:
                            fee_type = fee.get("feeType")
                            value = fee.get("value", {})
                            deadline = fee.get("dueDateTime")

                            if fee_type == "Percentage":
                                percentage = value.get("amount", 0)
                                if deadline:
                                    fee_descriptions.append(f"{percentage}% fee applies from {deadline}")
                                else:
                                    fee_descriptions.append(f"{percentage}% cancellation fee")
                            elif fee_type == "FixedAmount":
                                amount = value.get("amount", 0)
                                currency = value.get("currency", "EUR")
                                if deadline:
                                    fee_descriptions.append(f"{amount} {currency} fee applies from {deadline}")
                                else:
                                    fee_descriptions.append(f"{amount} {currency} cancellation fee")
                            elif fee_type == "NightsRevenue":
                                nights = value.get("amount", 1)
                                if deadline:
                                    fee_descriptions.append(f"{nights} night(s) revenue fee applies from {deadline}")
                                else:
                                    fee_descriptions.append(f"{nights} night(s) revenue cancellation fee")

                        if fee_descriptions:
                            return "Cancellation policy: " + "; ".join(fee_descriptions)
                        else:
                            return "Free cancellation with potential fees - see terms and conditions"
                    else:
                        # Check for free cancellation deadline
                        deadline = policy.get("deadline")
                        if deadline:
                            # Handle different deadline formats
                            if isinstance(deadline, dict):
                                hours_before = deadline.get("hoursBeforeArrival", 24)
                                time_of_day = deadline.get("timeOfDay", "18:00")
                                if hours_before == 0:
                                    return f"Free cancellation until {time_of_day} on arrival day"
                                elif hours_before == 24:
                                    return f"Free cancellation until {time_of_day} one day before arrival"
                                else:
                                    return f"Free cancellation until {hours_before} hours before arrival"
                            elif isinstance(deadline, str):
                                return f"Free cancellation until {deadline}"
                        return "Free cancellation up to arrival"

            # NOTE: /booking/v1/rate-plans/{id}/booking-conditions endpoint does not exist in Apaleo API
            # Removed non-existent booking conditions lookup - using rate plan data only

            # Final fallback based on typical hotel policies
            return "Free cancellation until 6 PM on arrival day"

        except Exception as e:
            # If cancellation policy endpoint fails, return generic policy
            if hasattr(self.logger, "warning"):
                self.logger.warning(
                    f"Could not fetch cancellation policy: {e}",
                    property_id=property_id,
                    rate_code=rate_code
                )
            return "Free cancellation until 6 PM on arrival day"

    # Apaleo Finance API Integration Methods (Fixed from non-existent /pay/v1/ endpoints)
    async def get_folio_from_reservation(self, reservation_id: str) -> Dict[str, Any]:
        """Get folio details from reservation using Finance API"""
        try:
            # First get the reservation to extract folio information
            reservation = await self._request("GET", f"/booking/v1/bookings/{reservation_id}")

            # Get property ID from reservation
            property_id = reservation.get("property", {}).get("id") or self.property_id

            # Get all folios for the property and filter by reservation
            folios = await self._request(
                "GET",
                "/finance/v1/folios",
                params={"propertyIds": property_id}
            )

            # Find folio that matches this reservation
            for folio in folios.get("folios", []):
                if folio.get("reservationId") == reservation_id:
                    if hasattr(self.logger, "info"):
                        self.logger.info(
                            "folio_found_for_reservation",
                            reservation_id=reservation_id,
                            folio_id=folio.get("id")
                        )
                    return folio

            # If no folio found, this might be a new reservation without charges yet
            if hasattr(self.logger, "warning"):
                self.logger.warning(
                    "no_folio_found_for_reservation",
                    reservation_id=reservation_id
                )
            raise NotFoundError(f"No folio found for reservation {reservation_id}")

        except Exception as e:
            if hasattr(self.logger, "error"):
                self.logger.error("folio_lookup_error", reservation_id=reservation_id, error=str(e))
            raise PMSError(f"Failed to get folio for reservation: {e}")

    async def authorize_payment(self, reservation_id: str, amount: Decimal, currency: str = "EUR") -> Dict[str, Any]:
        """Create payment authorization on folio using Finance API"""
        try:
            # Get folio for this reservation
            folio = await self.get_folio_from_reservation(reservation_id)
            folio_id = folio.get("id")

            if not folio_id:
                raise PMSError(f"No folio ID found for reservation {reservation_id}")

            # Create payment authorization on folio using Finance API
            payment_data = {
                "amount": {
                    "amount": float(amount),
                    "currency": currency
                },
                "method": "CreditCard",
                "description": f"Authorization for reservation {reservation_id}",
                "paymentProcessedAtUtc": datetime.now(timezone.utc).isoformat()
            }

            result = await self._request(
                "POST",
                f"/finance/v1/folios/{folio_id}/payments/by-authorization",
                json=payment_data
            )

            if hasattr(self.logger, "info"):
                self.logger.info(
                    "apaleo_payment_authorized_finance_api",
                    reservation_id=reservation_id,
                    folio_id=folio_id,
                    amount=amount,
                    currency=currency,
                    payment_id=result.get("id")
                )

            return result

        except Exception as e:
            if hasattr(self.logger, "error"):
                self.logger.error("apaleo_payment_authorization_error",
                            reservation_id=reservation_id, error=str(e))
            raise PMSError(f"Failed to authorize payment: {e}")

    async def capture_payment(self, reservation_id: str, amount: Decimal, currency: str = "EUR") -> Dict[str, Any]:
        """Create payment capture on folio using Finance API"""
        try:
            # Get folio for this reservation
            folio = await self.get_folio_from_reservation(reservation_id)
            folio_id = folio.get("id")

            if not folio_id:
                raise PMSError(f"No folio ID found for reservation {reservation_id}")

            # Create payment on folio using Finance API
            payment_data = {
                "amount": {
                    "amount": float(amount),
                    "currency": currency
                },
                "method": "CreditCard",
                "description": f"Payment capture for reservation {reservation_id}",
                "paymentProcessedAtUtc": datetime.now(timezone.utc).isoformat()
            }

            result = await self._request(
                "POST",
                f"/finance/v1/folios/{folio_id}/payments",
                json=payment_data
            )

            if hasattr(self.logger, "info"):
                self.logger.info(
                    "apaleo_payment_captured_finance_api",
                    reservation_id=reservation_id,
                    folio_id=folio_id,
                    captured_amount=amount,
                    currency=currency,
                    payment_id=result.get("id")
                )

            return result

        except Exception as e:
            if hasattr(self.logger, "error"):
                self.logger.error("apaleo_payment_capture_error",
                            reservation_id=reservation_id, error=str(e))
            raise PMSError(f"Failed to capture payment: {e}")

    async def refund_payment(self, reservation_id: str, amount: Decimal, reason: str = "Guest request", currency: str = "EUR") -> Dict[str, Any]:
        """Process refund on folio using Finance API"""
        try:
            # Get folio for this reservation
            folio = await self.get_folio_from_reservation(reservation_id)
            folio_id = folio.get("id")

            if not folio_id:
                raise PMSError(f"No folio ID found for reservation {reservation_id}")

            # Create refund on folio using Finance API
            refund_data = {
                "amount": {
                    "amount": float(amount),
                    "currency": currency
                },
                "reason": reason,
                "refundProcessedAtUtc": datetime.now(timezone.utc).isoformat()
            }

            result = await self._request(
                "POST",
                f"/finance/v1/folios/{folio_id}/refunds",
                json=refund_data
            )

            if hasattr(self.logger, "info"):
                self.logger.info(
                    "apaleo_payment_refunded_finance_api",
                    reservation_id=reservation_id,
                    folio_id=folio_id,
                    refund_amount=amount,
                    currency=currency,
                    reason=reason,
                    refund_id=result.get("id")
                )

            return result

        except Exception as e:
            if hasattr(self.logger, "error"):
                self.logger.error("apaleo_payment_refund_error",
                            reservation_id=reservation_id, error=str(e))
            raise PMSError(f"Failed to process refund: {e}")

    async def get_payment_status(self, reservation_id: str) -> Dict[str, Any]:
        """Get payment status for reservation using Finance API"""
        try:
            # Get folio for this reservation
            folio = await self.get_folio_from_reservation(reservation_id)

            if hasattr(self.logger, "info"):
                self.logger.info(
                    "apaleo_payment_status_retrieved_finance_api",
                    reservation_id=reservation_id,
                    folio_id=folio.get("id"),
                    balance=folio.get("balance", {})
                )

            return {
                "folio_id": folio.get("id"),
                "reservation_id": reservation_id,
                "balance": folio.get("balance", {}),
                "charges": folio.get("charges", []),
                "payments": folio.get("payments", []),
                "allowances": folio.get("allowances", []),
                "status": folio.get("status", "open")
            }

        except Exception as e:
            if hasattr(self.logger, "error"):
                self.logger.error("apaleo_payment_status_error",
                            reservation_id=reservation_id, error=str(e))
            raise PMSError(f"Failed to get payment status: {e}")

    async def list_payment_transactions(self, reservation_id: Optional[str] = None,
                                      property_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """List payment transactions using Finance API"""
        try:
            property_filter = property_id or self.property_id

            if reservation_id:
                # Get specific folio for this reservation
                folio = await self.get_folio_from_reservation(reservation_id)
                return folio.get("payments", [])
            else:
                # Get all folios for the property and extract payments
                folios = await self._request(
                    "GET",
                    "/finance/v1/folios",
                    params={"propertyIds": property_filter}
                )

                all_payments = []
                for folio in folios.get("folios", []):
                    payments = folio.get("payments", [])
                    # Add folio context to each payment
                    for payment in payments:
                        payment["folio_id"] = folio.get("id")
                        payment["reservation_id"] = folio.get("reservationId")
                    all_payments.extend(payments)

                if hasattr(self.logger, "info"):
                    self.logger.info(
                        "apaleo_payment_list_retrieved_finance_api",
                        property_id=property_filter,
                        total_payments=len(all_payments)
                    )

                return all_payments

        except Exception as e:
            if hasattr(self.logger, "error"):
                self.logger.error("apaleo_payment_list_error", error=str(e))
            raise PMSError(f"Failed to list payment transactions: {e}")

    async def create_booking_with_payment(self, payload: ReservationDraft,
                                        payment_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create booking and process payment using working Finance API"""
        try:
            # Step 1: Create the reservation using the working booking endpoint
            reservation = await self.create_reservation(payload)
            reservation_id = reservation.id

            if hasattr(self.logger, "info"):
                self.logger.info(
                    "booking_created_for_payment",
                    reservation_id=reservation_id,
                    confirmation_number=reservation.confirmation_number
                )

            # Step 2: Process payment if required
            payment_amount = payment_data.get("payment_amount")
            if payment_amount:
                try:
                    payment_result = await self.capture_payment(
                        reservation_id=reservation_id,
                        amount=Decimal(str(payment_amount)),
                        currency=payment_data.get("currency", "EUR")
                    )

                    if hasattr(self.logger, "info"):
                        self.logger.info(
                            "apaleo_booking_with_payment_completed_finance_api",
                            reservation_id=reservation_id,
                            payment_id=payment_result.get("id"),
                            payment_amount=payment_amount
                        )

                    return {
                        "reservation": {
                            "id": reservation.id,
                            "confirmation_number": reservation.confirmation_number,
                            "status": reservation.status,
                            "total_amount": float(reservation.total_amount)
                        },
                        "payment": payment_result,
                        "status": "completed"
                    }

                except Exception as payment_error:
                    # Log payment failure but don't cancel the reservation
                    if hasattr(self.logger, "error"):
                        self.logger.error(
                            "payment_failed_reservation_created",
                            reservation_id=reservation_id,
                            error=str(payment_error)
                        )

                    return {
                        "reservation": {
                            "id": reservation.id,
                            "confirmation_number": reservation.confirmation_number,
                            "status": reservation.status,
                            "total_amount": float(reservation.total_amount)
                        },
                        "payment_error": str(payment_error),
                        "status": "reservation_created_payment_failed"
                    }
            else:
                # No payment required
                return {
                    "reservation": {
                        "id": reservation.id,
                        "confirmation_number": reservation.confirmation_number,
                        "status": reservation.status,
                        "total_amount": float(reservation.total_amount)
                    },
                    "status": "reservation_created_no_payment"
                }

        except Exception as e:
            if hasattr(self.logger, "error"):
                self.logger.error("apaleo_booking_with_payment_error", error=str(e))
            raise PMSError(f"Failed to create booking with payment: {e}")

    # NOTE: Apaleo Payment webhooks are not available via /pay/v1/ API (removed non-existent endpoints)
    # Finance API webhooks would need to be implemented separately if required
    # For now, payment status should be checked via get_payment_status() method
