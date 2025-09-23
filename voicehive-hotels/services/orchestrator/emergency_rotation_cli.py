#!/usr/bin/env python3
"""
Emergency Secret Rotation CLI Tool
Command-line interface for emergency secret rotation operations
"""

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any

import hvac
from tabulate import tabulate

# Add the orchestrator directory to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from secrets_manager import SecretsManager, SecretType, RotationStrategy
from secret_rotation_automation import SecretRotationOrchestrator, RotationStatus
from secret_lifecycle_manager import SecretLifecycleManager
from secret_audit_system import SecretAuditSystem
from logging_adapter import get_safe_logger
from audit_logging import AuditLogger

# Configure logging
logger = get_safe_logger("orchestrator.emergency_cli")
audit_logger = AuditLogger("emergency_rotation_cli")


class EmergencyRotationCLI:
    """Command-line interface for emergency secret rotation"""
    
    def __init__(self):
        self.vault_client = None
        self.secrets_manager = None
        self.rotation_orchestrator = None
        self.lifecycle_manager = None
        self.audit_system = None
    
    async def initialize(self, vault_url: str, vault_token: str):
        """Initialize the CLI with Vault connection"""
        
        try:
            # Initialize Vault client
            self.vault_client = hvac.Client(url=vault_url, token=vault_token)
            
            if not self.vault_client.is_authenticated():
                print("❌ Failed to authenticate with Vault")
                return False
            
            # Initialize secrets manager
            config = {
                'secrets_path': 'voicehive/secrets',
                'metadata_path': 'voicehive/metadata',
                'audit_path': 'voicehive/audit'
            }
            
            self.secrets_manager = SecretsManager(self.vault_client, config)
            if not await self.secrets_manager.initialize():
                print("❌ Failed to initialize secrets manager")
                return False
            
            # Initialize rotation orchestrator
            self.rotation_orchestrator = SecretRotationOrchestrator(
                self.secrets_manager, self.vault_client
            )
            await self.rotation_orchestrator.start()
            
            # Initialize lifecycle manager
            self.lifecycle_manager = SecretLifecycleManager(
                self.secrets_manager, self.vault_client, config
            )
            await self.lifecycle_manager.initialize()
            
            # Initialize audit system
            self.audit_system = SecretAuditSystem(
                self.secrets_manager, self.vault_client, config
            )
            await self.audit_system.initialize()
            
            print("✅ Emergency rotation CLI initialized successfully")
            return True
            
        except Exception as e:
            print(f"❌ Initialization failed: {str(e)}")
            return False
    
    async def list_secrets(self, secret_type: Optional[SecretType] = None, show_expired: bool = False):
        """List all secrets with their status"""
        
        try:
            # Get all secret metadata
            all_metadata = await self.secrets_manager._get_all_secret_metadata()
            
            # Filter by type if specified
            if secret_type:
                all_metadata = [m for m in all_metadata if m.secret_type == secret_type]
            
            # Filter expired if not requested
            if not show_expired:
                now = datetime.now(timezone.utc)
                all_metadata = [
                    m for m in all_metadata 
                    if not m.expires_at or m.expires_at > now
                ]
            
            if not all_metadata:
                print("No secrets found matching criteria")
                return
            
            # Prepare table data
            table_data = []
            for metadata in all_metadata:
                age_days = (datetime.now(timezone.utc) - metadata.created_at).days
                expires_in = None
                if metadata.expires_at:
                    expires_in = (metadata.expires_at - datetime.now(timezone.utc)).days
                
                table_data.append([
                    metadata.secret_id[:8] + "...",
                    metadata.secret_type.value,
                    metadata.status.value,
                    f"{age_days} days",
                    f"{expires_in} days" if expires_in is not None else "Never",
                    metadata.rotation_count,
                    metadata.last_rotated.strftime("%Y-%m-%d") if metadata.last_rotated else "Never"
                ])
            
            headers = ["Secret ID", "Type", "Status", "Age", "Expires In", "Rotations", "Last Rotated"]
            print(tabulate(table_data, headers=headers, tablefmt="grid"))
            
        except Exception as e:
            print(f"❌ Failed to list secrets: {str(e)}")
    
    async def rotate_secret(self, secret_id: str, strategy: RotationStrategy = RotationStrategy.EMERGENCY):
        """Rotate a specific secret"""
        
        try:
            print(f"🔄 Starting rotation for secret {secret_id}...")
            
            # Schedule rotation
            rotation_id = await self.rotation_orchestrator.schedule_rotation(
                secret_id, strategy, priority=10  # High priority for emergency
            )
            
            print(f"📋 Rotation scheduled with ID: {rotation_id}")
            
            # Monitor rotation progress
            await self._monitor_rotation(rotation_id)
            
        except Exception as e:
            print(f"❌ Failed to rotate secret: {str(e)}")
    
    async def rotate_all_secrets(self, secret_type: Optional[SecretType] = None, 
                               confirm: bool = False, parallel_limit: int = 3):
        """Rotate all secrets of a given type or all secrets"""
        
        if not confirm:
            type_str = secret_type.value if secret_type else "ALL"
            response = input(f"⚠️  Are you sure you want to rotate {type_str} secrets? (yes/no): ")
            if response.lower() != 'yes':
                print("Operation cancelled")
                return
        
        try:
            print("🔄 Starting emergency rotation of all secrets...")
            
            # Use the emergency rotation method
            results = await self.secrets_manager.emergency_rotate_all_secrets(secret_type)
            
            # Display results
            successful = sum(results.values())
            total = len(results)
            
            print(f"\n📊 Emergency Rotation Results:")
            print(f"   Total secrets: {total}")
            print(f"   Successful: {successful}")
            print(f"   Failed: {total - successful}")
            
            if total - successful > 0:
                print("\n❌ Failed rotations:")
                for secret_id, success in results.items():
                    if not success:
                        print(f"   - {secret_id}")
            
            # Record emergency event
            audit_logger.log_security_event(
                event_type="emergency_rotation_completed",
                details={
                    "total_secrets": total,
                    "successful_rotations": successful,
                    "failed_rotations": total - successful,
                    "secret_type": secret_type.value if secret_type else "all"
                },
                severity="high"
            )
            
        except Exception as e:
            print(f"❌ Emergency rotation failed: {str(e)}")
    
    async def check_secret_health(self):
        """Check the health of all secrets"""
        
        try:
            print("🔍 Checking secret health...")
            
            report = await self.secrets_manager.get_secrets_health_report()
            
            print(f"\n📊 Secret Health Report:")
            print(f"   Overall Health: {report['overall_health'].upper()}")
            print(f"   Vault Status: {report['vault_status']}")
            
            # Summary by type
            if report['secrets_by_type']:
                print("\n📋 Secrets by Type:")
                for secret_type, stats in report['secrets_by_type'].items():
                    print(f"   {secret_type}:")
                    print(f"     Total: {stats['total']}")
                    print(f"     Active: {stats['active']}")
                    if stats.get('expired', 0) > 0:
                        print(f"     Expired: {stats['expired']} ⚠️")
            
            # Expiring soon
            if report['expiring_soon']:
                print(f"\n⏰ Secrets Expiring Soon ({len(report['expiring_soon'])}):")
                for secret in report['expiring_soon']:
                    print(f"   - {secret['secret_id'][:8]}... ({secret['secret_type']}) - {secret['days_to_expiry']} days")
            
            # Expired secrets
            if report['expired']:
                print(f"\n💀 Expired Secrets ({len(report['expired'])}):")
                for secret in report['expired']:
                    print(f"   - {secret['secret_id'][:8]}... ({secret['secret_type']}) - expired {secret['expired_days_ago']} days ago")
            
            # High usage
            if report['high_usage']:
                print(f"\n📈 High Usage Secrets ({len(report['high_usage'])}):")
                for secret in report['high_usage']:
                    print(f"   - {secret['secret_id'][:8]}... ({secret['secret_type']}) - {secret['usage_percentage']:.1f}% usage")
            
            # Rotation needed
            if report['rotation_needed']:
                print(f"\n🔄 Rotation Needed ({len(report['rotation_needed'])}):")
                for secret in report['rotation_needed']:
                    print(f"   - {secret['secret_id'][:8]}... ({secret['secret_type']}) - {secret['days_since_rotation']} days since rotation")
            
        except Exception as e:
            print(f"❌ Health check failed: {str(e)}")
    
    async def generate_audit_report(self, hours: int = 24, output_file: Optional[str] = None):
        """Generate audit report for recent activity"""
        
        try:
            print(f"📋 Generating audit report for last {hours} hours...")
            
            end_time = datetime.now(timezone.utc)
            start_time = end_time - timedelta(hours=hours)
            
            report = await self.audit_system.generate_audit_report(
                start_time, end_time, include_anomalies=True
            )
            
            # Display summary
            print(f"\n📊 Audit Report Summary:")
            print(f"   Period: {start_time.strftime('%Y-%m-%d %H:%M')} - {end_time.strftime('%Y-%m-%d %H:%M')} UTC")
            print(f"   Total Access Events: {report['summary']['total_access_events']}")
            print(f"   Successful Accesses: {report['summary']['successful_accesses']}")
            print(f"   Failed Accesses: {report['summary']['failed_accesses']}")
            print(f"   Unique Accessors: {report['summary']['unique_accessors']}")
            print(f"   Anomalies Detected: {report['summary']['anomalies_detected']}")
            
            # Top accessors
            if report['top_accessors']:
                print(f"\n👥 Top Accessors:")
                for accessor in report['top_accessors'][:5]:
                    print(f"   - {accessor['accessor_id']}: {accessor['access_count']} accesses")
            
            # Anomalies
            if report['anomalies']:
                print(f"\n🚨 Anomalies Detected:")
                for anomaly in report['anomalies']:
                    print(f"   - {anomaly['anomaly_type']} ({anomaly['severity']}) - {anomaly['description']}")
            
            # Recommendations
            if report['recommendations']:
                print(f"\n💡 Recommendations:")
                for rec in report['recommendations']:
                    print(f"   - {rec}")
            
            # Save to file if requested
            if output_file:
                with open(output_file, 'w') as f:
                    json.dump(report, f, indent=2, default=str)
                print(f"\n💾 Full report saved to: {output_file}")
            
        except Exception as e:
            print(f"❌ Audit report generation failed: {str(e)}")
    
    async def _monitor_rotation(self, rotation_id: str, timeout_minutes: int = 30):
        """Monitor rotation progress"""
        
        import time
        start_time = time.time()
        
        while time.time() - start_time < timeout_minutes * 60:
            try:
                context = await self.rotation_orchestrator.get_rotation_status(rotation_id)
                
                if not context:
                    print("❌ Rotation not found")
                    return
                
                print(f"📊 Status: {context.status.value} - Phase: {context.current_phase.value}")
                
                if context.status == RotationStatus.COMPLETED:
                    print("✅ Rotation completed successfully")
                    return
                elif context.status == RotationStatus.FAILED:
                    print(f"❌ Rotation failed: {context.error_message}")
                    return
                elif context.status == RotationStatus.ROLLED_BACK:
                    print("🔄 Rotation was rolled back")
                    return
                
                await asyncio.sleep(5)  # Check every 5 seconds
                
            except Exception as e:
                print(f"❌ Error monitoring rotation: {str(e)}")
                return
        
        print("⏰ Rotation monitoring timed out")
    
    async def shutdown(self):
        """Shutdown the CLI"""
        
        if self.rotation_orchestrator:
            await self.rotation_orchestrator.stop()
        
        if self.lifecycle_manager:
            await self.lifecycle_manager.shutdown()
        
        if self.audit_system:
            await self.audit_system.shutdown()


async def main():
    """Main CLI entry point"""
    
    parser = argparse.ArgumentParser(
        description="VoiceHive Emergency Secret Rotation CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # List all secrets
  python emergency_rotation_cli.py list

  # Check secret health
  python emergency_rotation_cli.py health

  # Rotate a specific secret
  python emergency_rotation_cli.py rotate --secret-id abc123def456

  # Emergency rotate all database passwords
  python emergency_rotation_cli.py rotate-all --type database_password --confirm

  # Generate audit report
  python emergency_rotation_cli.py audit --hours 24 --output report.json
        """
    )
    
    # Global options
    parser.add_argument("--vault-url", default=os.getenv("VAULT_ADDR", "http://localhost:8200"),
                       help="Vault server URL")
    parser.add_argument("--vault-token", default=os.getenv("VAULT_TOKEN"),
                       help="Vault authentication token")
    parser.add_argument("--incident-id", help="Incident ID for tracking")
    
    # Subcommands
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # List command
    list_parser = subparsers.add_parser("list", help="List secrets")
    list_parser.add_argument("--type", type=SecretType, choices=list(SecretType),
                           help="Filter by secret type")
    list_parser.add_argument("--show-expired", action="store_true",
                           help="Include expired secrets")
    
    # Health command
    health_parser = subparsers.add_parser("health", help="Check secret health")
    
    # Rotate command
    rotate_parser = subparsers.add_parser("rotate", help="Rotate a specific secret")
    rotate_parser.add_argument("--secret-id", required=True, help="Secret ID to rotate")
    rotate_parser.add_argument("--strategy", type=RotationStrategy, 
                             choices=list(RotationStrategy),
                             default=RotationStrategy.EMERGENCY,
                             help="Rotation strategy")
    
    # Rotate all command
    rotate_all_parser = subparsers.add_parser("rotate-all", help="Rotate all secrets")
    rotate_all_parser.add_argument("--type", type=SecretType, choices=list(SecretType),
                                 help="Secret type to rotate (all if not specified)")
    rotate_all_parser.add_argument("--confirm", action="store_true",
                                 help="Skip confirmation prompt")
    rotate_all_parser.add_argument("--parallel-limit", type=int, default=3,
                                 help="Maximum parallel rotations")
    
    # Audit command
    audit_parser = subparsers.add_parser("audit", help="Generate audit report")
    audit_parser.add_argument("--hours", type=int, default=24,
                            help="Hours of history to include")
    audit_parser.add_argument("--output", help="Output file for full report")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 1
    
    if not args.vault_token:
        print("❌ Vault token required (use --vault-token or VAULT_TOKEN env var)")
        return 1
    
    # Initialize CLI
    cli = EmergencyRotationCLI()
    
    if not await cli.initialize(args.vault_url, args.vault_token):
        return 1
    
    try:
        # Execute command
        if args.command == "list":
            await cli.list_secrets(args.type, args.show_expired)
        
        elif args.command == "health":
            await cli.check_secret_health()
        
        elif args.command == "rotate":
            await cli.rotate_secret(args.secret_id, args.strategy)
        
        elif args.command == "rotate-all":
            await cli.rotate_all_secrets(args.type, args.confirm, args.parallel_limit)
        
        elif args.command == "audit":
            await cli.generate_audit_report(args.hours, args.output)
        
        else:
            print(f"❌ Unknown command: {args.command}")
            return 1
        
        return 0
        
    except KeyboardInterrupt:
        print("\n⚠️  Operation cancelled by user")
        return 1
    
    except Exception as e:
        print(f"❌ Unexpected error: {str(e)}")
        return 1
    
    finally:
        await cli.shutdown()


if __name__ == "__main__":
    import sys
    from datetime import timedelta
    
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except Exception as e:
        print(f"❌ Fatal error: {str(e)}")
        sys.exit(1)