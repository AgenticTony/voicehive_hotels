"""
VoiceHive Hotels Alerting Package
Comprehensive email alerting capabilities for the monitoring system
"""

from .email_service import (
    EmailNotificationChannel,
    EmailConfig,
    EmailTemplate,
    create_email_notification_channel
)

__all__ = [
    'EmailNotificationChannel',
    'EmailConfig',
    'EmailTemplate',
    'create_email_notification_channel'
]

__version__ = "1.0.0"