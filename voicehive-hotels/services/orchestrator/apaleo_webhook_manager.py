"""
Apaleo Webhook Subscription Manager
Manages webhook subscriptions with Apaleo API for real-time updates
"""

import os
import asyncio
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone

import httpx
from pydantic import BaseModel, Field

from .logging_adapter import get_safe_logger

logger = get_safe_logger("orchestrator.apaleo_webhook_manager")


class WebhookSubscription(BaseModel):
    """Apaleo webhook subscription model"""
    id: Optional[str] = Field(None, description="Subscription ID")
    endpointUrl: str = Field(..., description="Webhook endpoint URL")
    events: List[str] = Field(..., description="List of event patterns to subscribe to")
    propertyIds: Optional[List[str]] = Field(None, description="Property IDs to filter events")
    isActive: Optional[bool] = Field(None, description="Whether subscription is active")
    createdAt: Optional[str] = Field(None, description="Creation timestamp")
    updatedAt: Optional[str] = Field(None, description="Last update timestamp")


class ApaleoWebhookManager:
    """Manages Apaleo webhook subscriptions with optimized connection pooling"""

    def __init__(self):
        self.base_url = "https://webhook.apaleo.com/v1"
        self.client_id = os.getenv("APALEO_CLIENT_ID")
        self.client_secret = os.getenv("APALEO_CLIENT_SECRET")
        self.webhook_endpoint_base = os.getenv("WEBHOOK_ENDPOINT_BASE", "https://api.voicehive.com")
        self.webhook_secret = os.getenv("APALEO_WEBHOOK_SECRET")

        if not self.client_id or not self.client_secret:
            logger.error("apaleo_credentials_missing",
                        client_id_present=bool(self.client_id),
                        client_secret_present=bool(self.client_secret))
            raise ValueError("APALEO_CLIENT_ID and APALEO_CLIENT_SECRET must be set")

        if not self.webhook_secret:
            logger.warning("apaleo_webhook_secret_missing")

        # Initialize persistent HTTP client with optimized connection pooling
        # Webhook operations are infrequent but benefit from connection reuse
        webhook_connection_limits = httpx.Limits(
            max_keepalive_connections=3,   # Small pool for webhook operations
            max_connections=10,            # Limited connections for webhook management
            keepalive_expiry=45.0          # Keep connections alive for webhook clusters
        )

        webhook_timeout_config = httpx.Timeout(
            connect=10.0,    # Connection timeout for webhook endpoints
            read=30.0,       # Read timeout for webhook operations
            write=15.0,      # Write timeout for webhook creation/updates
            pool=3.0         # Quick pool acquisition for webhook management
        )

        self._client = httpx.AsyncClient(
            timeout=webhook_timeout_config,
            limits=webhook_connection_limits,
            headers={
                "User-Agent": "VoiceHive-Webhook-Manager/1.0",
                "Accept": "application/json",
                "Connection": "keep-alive"
            },
            http2=True
        )

        logger.info(
            "apaleo_webhook_manager_initialized",
            max_keepalive=webhook_connection_limits.max_keepalive_connections,
            max_connections=webhook_connection_limits.max_connections,
            keepalive_expiry=webhook_connection_limits.keepalive_expiry
        )

    async def _get_access_token(self) -> str:
        """Get OAuth access token for Apaleo API using persistent client"""
        try:
            response = await self._client.post(
                "https://identity.apaleo.com/connect/token",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "scope": "webhook:manage"  # Webhook management scope
                }
            )
            response.raise_for_status()
            token_data = response.json()
            return token_data["access_token"]

        except Exception as e:
            logger.error("apaleo_token_error", error=str(e))
            raise

    async def close(self):
        """Close the HTTP client and clean up resources"""
        if self._client:
            await self._client.aclose()
            logger.info("apaleo_webhook_manager_client_closed")

    async def __aenter__(self):
        """Async context manager entry"""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.close()

    async def create_webhook_subscription(
        self,
        property_ids: Optional[List[str]] = None,
        events: Optional[List[str]] = None
    ) -> WebhookSubscription:
        """
        Create a new webhook subscription with Apaleo

        Args:
            property_ids: List of property IDs to filter events (None for all properties)
            events: List of event patterns to subscribe to

        Returns:
            Created webhook subscription
        """
        if events is None:
            events = [
                "reservation/created",
                "reservation/changed",
                "reservation/canceled",
                "system/healthcheck"
            ]

        try:
            access_token = await self._get_access_token()

            subscription_data = {
                "endpointUrl": f"{self.webhook_endpoint_base}/v1/apaleo/webhook",
                "events": events
            }

            # Add property filter if specified
            if property_ids:
                subscription_data["propertyIds"] = property_ids

            response = await self._client.post(
                f"{self.base_url}/subscriptions",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json"
                },
                json=subscription_data
            )

            response.raise_for_status()
            subscription_response = response.json()

            subscription = WebhookSubscription(**subscription_response)

            logger.info(
                    "apaleo_webhook_subscription_created",
                    subscription_id=subscription.id,
                    endpoint_url=subscription.endpointUrl,
                    events=subscription.events,
                    property_ids=property_ids
                )

            return subscription

        except Exception as e:
            logger.error("apaleo_webhook_subscription_error", error=str(e))
            raise

    async def get_webhook_subscriptions(self) -> List[WebhookSubscription]:
        """Get all existing webhook subscriptions"""
        try:
            access_token = await self._get_access_token()

            response = await self._client.get(
                f"{self.base_url}/subscriptions",
                headers={"Authorization": f"Bearer {access_token}"}
            )

            response.raise_for_status()
            subscriptions_data = response.json()

            subscriptions = [
                WebhookSubscription(**sub)
                for sub in subscriptions_data.get("subscriptions", [])
                ]

            logger.info(
                "apaleo_webhook_subscriptions_retrieved",
                count=len(subscriptions)
            )

            return subscriptions

        except Exception as e:
            logger.error("apaleo_webhook_subscriptions_get_error", error=str(e))
            raise

    async def update_webhook_subscription(
        self,
        subscription_id: str,
        property_ids: Optional[List[str]] = None,
        events: Optional[List[str]] = None
    ) -> WebhookSubscription:
        """Update an existing webhook subscription"""
        if events is None:
            events = [
                "reservation/created",
                "reservation/changed",
                "reservation/canceled",
                "system/healthcheck"
            ]

        try:
            access_token = await self._get_access_token()

            subscription_data = {
                "endpointUrl": f"{self.webhook_endpoint_base}/v1/apaleo/webhook",
                "events": events
            }

            if property_ids:
                subscription_data["propertyIds"] = property_ids

            # Use persistent client with connection pooling
            response = await self._client.put(
                    f"{self.base_url}/subscriptions/{subscription_id}",
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json"
                    },
                    json=subscription_data,
                    timeout=30.0
                )

                response.raise_for_status()
                subscription_response = response.json()

                subscription = WebhookSubscription(**subscription_response)

                logger.info(
                    "apaleo_webhook_subscription_updated",
                    subscription_id=subscription_id,
                    events=subscription.events,
                    property_ids=property_ids
                )

                return subscription

        except Exception as e:
            logger.error("apaleo_webhook_subscription_update_error",
                        subscription_id=subscription_id, error=str(e))
            raise

    async def delete_webhook_subscription(self, subscription_id: str):
        """Delete a webhook subscription"""
        try:
            access_token = await self._get_access_token()

            # Use persistent client with connection pooling
            response = await self._client.delete(
                    f"{self.base_url}/subscriptions/{subscription_id}",
                    headers={"Authorization": f"Bearer {access_token}"},
                    timeout=30.0
                )

                response.raise_for_status()

                logger.info(
                    "apaleo_webhook_subscription_deleted",
                    subscription_id=subscription_id
                )

        except Exception as e:
            logger.error("apaleo_webhook_subscription_delete_error",
                        subscription_id=subscription_id, error=str(e))
            raise

    async def ensure_webhook_subscription(
        self,
        property_ids: Optional[List[str]] = None
    ) -> WebhookSubscription:
        """
        Ensure webhook subscription exists, creating one if needed

        Args:
            property_ids: Property IDs to filter events (None for all properties)

        Returns:
            Existing or newly created webhook subscription
        """
        try:
            # Get existing subscriptions
            existing_subscriptions = await self.get_webhook_subscriptions()

            # Look for subscription with our endpoint
            our_endpoint = f"{self.webhook_endpoint_base}/v1/apaleo/webhook"

            for subscription in existing_subscriptions:
                if subscription.endpointUrl == our_endpoint:
                    logger.info(
                        "apaleo_webhook_subscription_exists",
                        subscription_id=subscription.id,
                        endpoint_url=subscription.endpointUrl
                    )
                    return subscription

            # Create new subscription if none exists
            logger.info(
                "apaleo_webhook_subscription_creating",
                endpoint_url=our_endpoint,
                property_ids=property_ids
            )

            return await self.create_webhook_subscription(property_ids)

        except Exception as e:
            logger.error("apaleo_webhook_subscription_ensure_error", error=str(e))
            raise

    async def test_webhook_endpoint(self) -> bool:
        """Test that our webhook endpoint is accessible"""
        try:
            # Use persistent client with connection pooling
                # Test with a health check-like request
            response = await self._client.post(
                    f"{self.webhook_endpoint_base}/v1/apaleo/webhook",
                    json={
                        "id": "test-event",
                        "topic": "system",
                        "type": "healthcheck",
                        "accountId": "TEST",
                        "timestamp": int(datetime.now(timezone.utc).timestamp() * 1000)
                    },
                    headers={
                        "Content-Type": "application/json",
                        "User-Agent": "Apaleo-Webhook/1.0"
                    },
                    timeout=10.0
                )

                # Accept any 2xx response
                if 200 <= response.status_code < 300:
                    logger.info("apaleo_webhook_endpoint_accessible",
                              status_code=response.status_code)
                    return True
                else:
                    logger.warning("apaleo_webhook_endpoint_error",
                                 status_code=response.status_code)
                    return False

        except Exception as e:
            logger.error("apaleo_webhook_endpoint_test_error", error=str(e))
            return False


# Factory function for dependency injection
def get_apaleo_webhook_manager() -> ApaleoWebhookManager:
    """Get Apaleo webhook manager instance"""
    return ApaleoWebhookManager()


# CLI utility functions for webhook management
async def setup_apaleo_webhooks(property_ids: Optional[List[str]] = None):
    """CLI utility to set up Apaleo webhooks"""
    manager = ApaleoWebhookManager()

    try:
        # Test endpoint accessibility
        logger.info("testing_webhook_endpoint_accessibility")
        endpoint_accessible = await manager.test_webhook_endpoint()

        if not endpoint_accessible:
            logger.error("webhook_endpoint_not_accessible")
            return False

        # Ensure webhook subscription exists
        logger.info("ensuring_webhook_subscription", property_ids=property_ids)
        subscription = await manager.ensure_webhook_subscription(property_ids)

        logger.info(
            "apaleo_webhooks_setup_complete",
            subscription_id=subscription.id,
            endpoint_url=subscription.endpointUrl,
            events=subscription.events,
            property_ids=property_ids
        )

        return True

    except Exception as e:
        logger.error("apaleo_webhooks_setup_failed", error=str(e))
        return False


if __name__ == "__main__":
    # Example usage
    async def main():
        await setup_apaleo_webhooks()

    asyncio.run(main())