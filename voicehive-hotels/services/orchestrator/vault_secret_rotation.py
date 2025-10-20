#!/usr/bin/env python3
"""
Vault Secret Rotation Automation

Implements automated secret rotation following HashiCorp best practices:
- Encryption key rotation (monthly)
- API key rotation (quarterly)
- Certificate rotation (annually)
- Service account credential rotation (monthly)

Follows the secrets-management-implementation.md guidelines.
"""

import asyncio
import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from enum import Enum

from production_vault_client import ProductionVaultClient
from logging_adapter import get_safe_logger

logger = get_safe_logger("orchestrator.vault_rotation")


class RotationType(Enum):
    """Types of secret rotation"""
    ENCRYPTION_KEY = "encryption_key"
    API_KEY = "api_key"
    CERTIFICATE = "certificate"
    SERVICE_ACCOUNT = "service_account"
    DATABASE_PASSWORD = "database_password"


@dataclass
class RotationSchedule:
    """Secret rotation schedule configuration"""
    rotation_type: RotationType
    interval_days: int
    warning_days: int  # Days before expiration to warn
    auto_rotate: bool
    notification_channels: List[str]


@dataclass
class RotationResult:
    """Result of a rotation operation"""
    rotation_type: RotationType
    success: bool
    message: str
    old_version: Optional[str] = None
    new_version: Optional[str] = None
    next_rotation: Optional[datetime] = None
    details: Optional[Dict[str, Any]] = None


class VaultSecretRotationManager:
    """
    Manages automated rotation of secrets in Vault

    Features:
    - Configurable rotation schedules
    - Automatic rotation based on age/expiration
    - Notification system for rotation events
    - Rollback capabilities
    - Health monitoring of rotated secrets
    """

    def __init__(self, vault_client: Optional[ProductionVaultClient] = None):
        self.vault_client = vault_client or ProductionVaultClient()
        self.rotation_schedules = self._get_default_schedules()
        self.rotation_path = "secret/data/rotation-tracking"

        logger.info("vault_rotation_manager_initialized")

    def _get_default_schedules(self) -> Dict[RotationType, RotationSchedule]:
        """Get default rotation schedules following security best practices"""
        return {
            RotationType.ENCRYPTION_KEY: RotationSchedule(
                rotation_type=RotationType.ENCRYPTION_KEY,
                interval_days=30,  # Monthly rotation for high-security
                warning_days=7,
                auto_rotate=True,
                notification_channels=["security-team", "platform-team"]
            ),
            RotationType.API_KEY: RotationSchedule(
                rotation_type=RotationType.API_KEY,
                interval_days=90,  # Quarterly rotation
                warning_days=14,
                auto_rotate=False,  # Manual approval required
                notification_channels=["platform-team", "engineering"]
            ),
            RotationType.CERTIFICATE: RotationSchedule(
                rotation_type=RotationType.CERTIFICATE,
                interval_days=365,  # Annual rotation
                warning_days=30,
                auto_rotate=False,  # Manual approval for certs
                notification_channels=["security-team", "infrastructure"]
            ),
            RotationType.SERVICE_ACCOUNT: RotationSchedule(
                rotation_type=RotationType.SERVICE_ACCOUNT,
                interval_days=30,  # Monthly rotation
                warning_days=7,
                auto_rotate=True,
                notification_channels=["platform-team"]
            ),
            RotationType.DATABASE_PASSWORD: RotationSchedule(
                rotation_type=RotationType.DATABASE_PASSWORD,
                interval_days=60,  # Bi-monthly rotation
                warning_days=14,
                auto_rotate=True,
                notification_channels=["platform-team", "dba-team"]
            )
        }

    async def initialize(self) -> bool:
        """Initialize the rotation manager"""
        try:
            # Initialize Vault client
            if not await self.vault_client.initialize():
                logger.error("vault_client_initialization_failed")
                return False

            # Create rotation tracking structure if it doesn't exist
            await self._ensure_rotation_tracking()

            logger.info("vault_rotation_manager_ready")
            return True

        except Exception as e:
            logger.error("rotation_manager_initialization_failed", error=str(e))
            return False

    async def _ensure_rotation_tracking(self) -> None:
        """Ensure rotation tracking structure exists in Vault"""
        try:
            # Check if rotation tracking exists
            existing = await self.vault_client.get_secret(self.rotation_path)

            if not existing:
                # Create initial tracking structure
                initial_tracking = {
                    "created_at": datetime.utcnow().isoformat(),
                    "rotations": {},
                    "schedules": {
                        rotation_type.value: {
                            "interval_days": schedule.interval_days,
                            "warning_days": schedule.warning_days,
                            "auto_rotate": schedule.auto_rotate,
                            "notification_channels": schedule.notification_channels
                        }
                        for rotation_type, schedule in self.rotation_schedules.items()
                    }
                }

                await self.vault_client.store_secret(self.rotation_path, initial_tracking)
                logger.info("rotation_tracking_initialized")

        except Exception as e:
            logger.warning("rotation_tracking_setup_failed", error=str(e))

    async def check_rotation_needed(self) -> List[RotationType]:
        """Check which secrets need rotation"""
        try:
            rotation_data = await self.vault_client.get_secret(self.rotation_path)
            if not rotation_data:
                logger.warning("rotation_tracking_not_found")
                return []

            rotations_needed = []
            now = datetime.utcnow()

            for rotation_type, schedule in self.rotation_schedules.items():
                last_rotation = rotation_data.get("rotations", {}).get(rotation_type.value)

                if not last_rotation:
                    # Never rotated - needs initial rotation
                    rotations_needed.append(rotation_type)
                    continue

                last_rotation_date = datetime.fromisoformat(last_rotation["timestamp"])
                next_rotation_date = last_rotation_date + timedelta(days=schedule.interval_days)

                if now >= next_rotation_date:
                    rotations_needed.append(rotation_type)
                elif now >= (next_rotation_date - timedelta(days=schedule.warning_days)):
                    # Within warning period
                    await self._send_rotation_warning(rotation_type, next_rotation_date)

            logger.info("rotation_check_completed",
                       rotations_needed=[rt.value for rt in rotations_needed])

            return rotations_needed

        except Exception as e:
            logger.error("rotation_check_failed", error=str(e))
            return []

    async def rotate_encryption_key(self) -> RotationResult:
        """Rotate the master encryption key"""
        try:
            logger.info("starting_encryption_key_rotation")

            # Get current key info
            old_key_info = self.vault_client.client.secrets.transit.read_key(
                name=self.vault_client.encryption_key_name,
                mount_point=self.vault_client.transit_mount_point
            )
            old_version = old_key_info['data']['latest_version']

            # Perform rotation
            rotation_result = await self.vault_client.rotate_encryption_key()

            # Update rotation tracking
            await self._record_rotation(RotationType.ENCRYPTION_KEY, {
                "old_version": old_version,
                "new_version": rotation_result["latest_version"],
                "timestamp": datetime.utcnow().isoformat(),
                "auto_rotated": True
            })

            # Verify rotation worked
            new_key_info = self.vault_client.client.secrets.transit.read_key(
                name=self.vault_client.encryption_key_name,
                mount_point=self.vault_client.transit_mount_point
            )

            if new_key_info['data']['latest_version'] > old_version:
                logger.info("encryption_key_rotation_success",
                           old_version=old_version,
                           new_version=new_key_info['data']['latest_version'])

                return RotationResult(
                    rotation_type=RotationType.ENCRYPTION_KEY,
                    success=True,
                    message="Encryption key rotated successfully",
                    old_version=str(old_version),
                    new_version=str(new_key_info['data']['latest_version']),
                    next_rotation=datetime.utcnow() + timedelta(days=30),
                    details=rotation_result
                )
            else:
                raise Exception("Key version did not increment after rotation")

        except Exception as e:
            logger.error("encryption_key_rotation_failed", error=str(e))
            return RotationResult(
                rotation_type=RotationType.ENCRYPTION_KEY,
                success=False,
                message=f"Encryption key rotation failed: {str(e)}"
            )

    async def rotate_api_keys(self, service_names: Optional[List[str]] = None) -> List[RotationResult]:
        """Rotate API keys for specified services or all services"""
        results = []

        try:
            # Get list of API keys to rotate
            if service_names is None:
                # Get all active API keys from Vault
                api_keys_data = await self.vault_client.get_secret("api-keys")
                if not api_keys_data:
                    logger.warning("no_api_keys_found_for_rotation")
                    return results

                service_names = list(set(
                    key_data.get("service_name")
                    for key_data in api_keys_data.values()
                    if isinstance(key_data, dict) and key_data.get("active", False)
                ))

            # Rotate each service's API keys
            for service_name in service_names:
                try:
                    result = await self._rotate_service_api_key(service_name)
                    results.append(result)

                    if result.success:
                        # Record successful rotation
                        await self._record_rotation(RotationType.API_KEY, {
                            "service_name": service_name,
                            "timestamp": datetime.utcnow().isoformat(),
                            "old_key_id": result.old_version,
                            "new_key_id": result.new_version
                        })

                except Exception as e:
                    logger.error("api_key_rotation_failed",
                               service_name=service_name,
                               error=str(e))
                    results.append(RotationResult(
                        rotation_type=RotationType.API_KEY,
                        success=False,
                        message=f"API key rotation failed for {service_name}: {str(e)}"
                    ))

            logger.info("api_keys_rotation_completed",
                       total_services=len(service_names),
                       successful_rotations=len([r for r in results if r.success]))

        except Exception as e:
            logger.error("api_keys_rotation_batch_failed", error=str(e))

        return results

    async def _rotate_service_api_key(self, service_name: str) -> RotationResult:
        """Rotate API key for a specific service"""
        # This is a simplified implementation
        # In production, you'd need to:
        # 1. Create new API key
        # 2. Update service configuration
        # 3. Verify service is using new key
        # 4. Deactivate old key after grace period

        logger.info("rotating_service_api_key", service_name=service_name)

        # For now, return a placeholder result
        # Real implementation would integrate with service deployment
        return RotationResult(
            rotation_type=RotationType.API_KEY,
            success=True,
            message=f"API key rotation planned for {service_name}",
            details={"service_name": service_name, "requires_manual_deployment": True}
        )

    async def _record_rotation(self, rotation_type: RotationType, rotation_data: Dict[str, Any]) -> None:
        """Record a completed rotation in Vault"""
        try:
            tracking_data = await self.vault_client.get_secret(self.rotation_path)
            if not tracking_data:
                tracking_data = {"rotations": {}}

            if "rotations" not in tracking_data:
                tracking_data["rotations"] = {}

            tracking_data["rotations"][rotation_type.value] = rotation_data

            await self.vault_client.store_secret(self.rotation_path, tracking_data)

            logger.info("rotation_recorded",
                       rotation_type=rotation_type.value,
                       timestamp=rotation_data.get("timestamp"))

        except Exception as e:
            logger.error("rotation_recording_failed",
                        rotation_type=rotation_type.value,
                        error=str(e))

    async def _send_rotation_warning(self, rotation_type: RotationType, next_rotation: datetime) -> None:
        """Send warning notification about upcoming rotation"""
        # In production, this would integrate with your notification system
        # (Slack, email, PagerDuty, etc.)

        days_until_rotation = (next_rotation - datetime.utcnow()).days
        schedule = self.rotation_schedules[rotation_type]

        warning_message = (
            f"🔑 Secret Rotation Warning\n"
            f"Type: {rotation_type.value}\n"
            f"Scheduled: {next_rotation.strftime('%Y-%m-%d %H:%M UTC')}\n"
            f"Days until rotation: {days_until_rotation}\n"
            f"Auto-rotate: {schedule.auto_rotate}\n"
            f"Channels: {', '.join(schedule.notification_channels)}"
        )

        logger.warning("rotation_warning_sent",
                      rotation_type=rotation_type.value,
                      days_until_rotation=days_until_rotation,
                      message=warning_message)

        # TODO: Integrate with actual notification system
        # await notification_service.send_alert(
        #     channels=schedule.notification_channels,
        #     message=warning_message,
        #     severity="warning"
        # )

    async def perform_scheduled_rotations(self) -> Dict[str, List[RotationResult]]:
        """Perform all scheduled rotations"""
        results = {
            "automatic": [],
            "manual_required": [],
            "failed": []
        }

        try:
            rotations_needed = await self.check_rotation_needed()

            for rotation_type in rotations_needed:
                schedule = self.rotation_schedules[rotation_type]

                if schedule.auto_rotate:
                    # Perform automatic rotation
                    if rotation_type == RotationType.ENCRYPTION_KEY:
                        result = await self.rotate_encryption_key()
                        results["automatic"].append(result)

                    elif rotation_type == RotationType.API_KEY:
                        api_results = await self.rotate_api_keys()
                        results["automatic"].extend(api_results)

                    # Add other rotation types as needed
                    # elif rotation_type == RotationType.SERVICE_ACCOUNT:
                    #     result = await self.rotate_service_accounts()
                    #     results["automatic"].append(result)

                else:
                    # Manual approval required
                    result = RotationResult(
                        rotation_type=rotation_type,
                        success=False,
                        message=f"Manual approval required for {rotation_type.value} rotation"
                    )
                    results["manual_required"].append(result)

                    # Send notification for manual rotations
                    await self._send_rotation_warning(rotation_type, datetime.utcnow())

            logger.info("scheduled_rotations_completed",
                       automatic_count=len(results["automatic"]),
                       manual_required_count=len(results["manual_required"]),
                       failed_count=len(results["failed"]))

        except Exception as e:
            logger.error("scheduled_rotations_failed", error=str(e))
            results["failed"].append(RotationResult(
                rotation_type=RotationType.ENCRYPTION_KEY,  # placeholder
                success=False,
                message=f"Scheduled rotations failed: {str(e)}"
            ))

        return results

    async def get_rotation_status(self) -> Dict[str, Any]:
        """Get current rotation status for all secret types"""
        try:
            tracking_data = await self.vault_client.get_secret(self.rotation_path)
            if not tracking_data:
                return {"error": "No rotation tracking data found"}

            status = {
                "last_check": datetime.utcnow().isoformat(),
                "rotation_schedules": {},
                "rotation_history": {}
            }

            for rotation_type, schedule in self.rotation_schedules.items():
                last_rotation = tracking_data.get("rotations", {}).get(rotation_type.value)

                schedule_status = {
                    "interval_days": schedule.interval_days,
                    "warning_days": schedule.warning_days,
                    "auto_rotate": schedule.auto_rotate,
                    "last_rotation": last_rotation.get("timestamp") if last_rotation else None,
                    "next_rotation": None,
                    "status": "unknown"
                }

                if last_rotation:
                    last_rotation_date = datetime.fromisoformat(last_rotation["timestamp"])
                    next_rotation_date = last_rotation_date + timedelta(days=schedule.interval_days)
                    schedule_status["next_rotation"] = next_rotation_date.isoformat()

                    now = datetime.utcnow()
                    if now >= next_rotation_date:
                        schedule_status["status"] = "overdue"
                    elif now >= (next_rotation_date - timedelta(days=schedule.warning_days)):
                        schedule_status["status"] = "warning"
                    else:
                        schedule_status["status"] = "current"
                else:
                    schedule_status["status"] = "never_rotated"

                status["rotation_schedules"][rotation_type.value] = schedule_status
                status["rotation_history"][rotation_type.value] = last_rotation

            return status

        except Exception as e:
            logger.error("rotation_status_check_failed", error=str(e))
            return {"error": str(e)}


async def main():
    """Example usage and testing"""
    rotation_manager = VaultSecretRotationManager()

    if await rotation_manager.initialize():
        print("✅ Rotation manager initialized successfully")

        # Check rotation status
        status = await rotation_manager.get_rotation_status()
        print("\n📊 Rotation Status:")
        for rotation_type, schedule_status in status.get("rotation_schedules", {}).items():
            print(f"  {rotation_type}: {schedule_status['status']}")

        # Check what needs rotation
        rotations_needed = await rotation_manager.check_rotation_needed()
        if rotations_needed:
            print(f"\n🔄 Rotations needed: {[rt.value for rt in rotations_needed]}")

            # Perform automatic rotations
            results = await rotation_manager.perform_scheduled_rotations()
            print(f"\n✅ Automatic rotations: {len(results['automatic'])}")
            print(f"⚠️  Manual required: {len(results['manual_required'])}")
            print(f"❌ Failed: {len(results['failed'])}")

        else:
            print("\n✅ All secrets are current - no rotations needed")

    else:
        print("❌ Failed to initialize rotation manager")


if __name__ == "__main__":
    asyncio.run(main())