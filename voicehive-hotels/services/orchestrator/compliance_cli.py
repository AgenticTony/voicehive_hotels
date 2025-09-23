#!/usr/bin/env python3
"""
Compliance Management CLI Tool for VoiceHive Hotels
Command-line interface for managing GDPR compliance, data retention, and audit operations
"""

import asyncio
import click
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

# Import compliance components
from compliance_integration import ComplianceIntegrationManager
from gdpr_compliance_manager import GDPRLawfulBasis, DataSubjectRight
from data_retention_enforcer import RetentionAction, DataCategory
from compliance_evidence_collector import ComplianceFramework
from compliance_monitoring_system import ViolationSeverity
from audit_trail_verifier import AuditIntegrityStatus

# Database setup (simplified for CLI)
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker


class ComplianceCLI:
    """Compliance management CLI"""
    
    def __init__(self, database_url: str):
        self.database_url = database_url
        self.engine = None
        self.session_factory = None
        self.compliance_manager = None
    
    async def initialize(self):
        """Initialize database connection and compliance manager"""
        self.engine = create_async_engine(self.database_url)
        self.session_factory = sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )
        
        async with self.session_factory() as session:
            self.compliance_manager = ComplianceIntegrationManager(session)
    
    async def cleanup(self):
        """Cleanup database connections"""
        if self.engine:
            await self.engine.dispose()


# Global CLI instance
cli_instance = None


@click.group()
@click.option('--database-url', 
              default='postgresql+asyncpg://localhost/voicehive',
              help='Database connection URL')
@click.pass_context
def cli(ctx, database_url):
    """VoiceHive Hotels Compliance Management CLI"""
    global cli_instance
    cli_instance = ComplianceCLI(database_url)
    ctx.ensure_object(dict)
    ctx.obj['cli'] = cli_instance


@cli.group()
def gdpr():
    """GDPR compliance management commands"""
    pass


@gdpr.command('register-subject')
@click.option('--subject-id', required=True, help='Data subject ID')
@click.option('--email', help='Email address')
@click.option('--name', help='Full name')
@click.option('--phone', help='Phone number')
@click.option('--hotel-guest-id', help='Hotel guest ID')
def register_data_subject(subject_id, email, name, phone, hotel_guest_id):
    """Register a new data subject"""
    
    async def _register():
        await cli_instance.initialize()
        try:
            data_subject = await cli_instance.compliance_manager.gdpr_manager.register_data_subject(
                subject_id=subject_id,
                email=email,
                name=name,
                phone=phone,
                hotel_guest_id=hotel_guest_id
            )
            
            click.echo(f"✓ Data subject registered: {data_subject.subject_id}")
            click.echo(f"  Created at: {data_subject.created_at}")
            
        finally:
            await cli_instance.cleanup()
    
    asyncio.run(_register())


@gdpr.command('submit-erasure')
@click.option('--subject-id', required=True, help='Data subject ID')
@click.option('--requested-by', required=True, help='Who requested the erasure')
@click.option('--reason', required=True, help='Reason for erasure')
@click.option('--scope', multiple=True, required=True, help='Data categories to erase')
@click.option('--no-verification', is_flag=True, help='Skip verification token')
def submit_erasure_request(subject_id, requested_by, reason, scope, no_verification):
    """Submit a GDPR Article 17 right to erasure request"""
    
    async def _submit():
        await cli_instance.initialize()
        try:
            request = await cli_instance.compliance_manager.gdpr_manager.submit_erasure_request(
                data_subject_id=subject_id,
                requested_by=requested_by,
                reason=reason,
                scope=list(scope),
                verification_required=not no_verification
            )
            
            click.echo(f"✓ Erasure request submitted: {request.request_id}")
            click.echo(f"  Status: {request.status}")
            if request.verification_token:
                click.echo(f"  Verification token: {request.verification_token}")
                click.echo(f"  Token expires: {request.verification_expires}")
            
        finally:
            await cli_instance.cleanup()
    
    asyncio.run(_submit())


@gdpr.command('execute-erasure')
@click.option('--request-id', required=True, help='Erasure request ID')
@click.option('--verification-token', help='Verification token (if required)')
def execute_erasure_request(request_id, verification_token):
    """Execute a verified erasure request"""
    
    async def _execute():
        await cli_instance.initialize()
        try:
            # Verify if token provided
            if verification_token:
                verified = await cli_instance.compliance_manager.gdpr_manager.verify_erasure_request(
                    request_id, verification_token
                )
                if not verified:
                    click.echo("✗ Invalid verification token")
                    return
            
            # Execute erasure
            results = await cli_instance.compliance_manager.gdpr_manager.execute_erasure_request(request_id)
            
            click.echo(f"✓ Erasure request executed: {request_id}")
            click.echo(f"  Status: {results['status']}")
            click.echo(f"  Started: {results['started_at']}")
            click.echo(f"  Completed: {results.get('completed_at', 'N/A')}")
            
            # Show results by category
            for category, result in results.get('results', {}).items():
                click.echo(f"  {category}:")
                click.echo(f"    Records affected: {result.get('records_affected', 0)}")
                click.echo(f"    Files deleted: {len(result.get('files_deleted', []))}")
            
        finally:
            await cli_instance.cleanup()
    
    asyncio.run(_execute())


@gdpr.command('compliance-report')
@click.option('--output', '-o', help='Output file path')
@click.option('--format', 'output_format', default='json', type=click.Choice(['json', 'text']))
def generate_gdpr_report(output, output_format):
    """Generate GDPR compliance report"""
    
    async def _report():
        await cli_instance.initialize()
        try:
            report = await cli_instance.compliance_manager.gdpr_manager.generate_compliance_report()
            
            if output_format == 'json':
                report_json = json.dumps(report, indent=2, default=str)
                if output:
                    Path(output).write_text(report_json)
                    click.echo(f"✓ GDPR compliance report saved to: {output}")
                else:
                    click.echo(report_json)
            else:
                # Text format
                click.echo("GDPR Compliance Report")
                click.echo("=" * 50)
                click.echo(f"Generated: {report['generated_at']}")
                click.echo(f"Status: {report['compliance_status']}")
                click.echo(f"Data subjects: {report['summary']['total_data_subjects']}")
                click.echo(f"Active processing records: {report['summary']['active_processing_records']}")
                click.echo(f"Pending erasure requests: {report['summary']['pending_erasure_requests']}")
                click.echo(f"Compliance violations: {report['summary']['compliance_violations']}")
            
        finally:
            await cli_instance.cleanup()
    
    asyncio.run(_report())


@cli.group()
def retention():
    """Data retention management commands"""
    pass


@retention.command('enforce')
@click.option('--policy-ids', help='Comma-separated policy IDs (all if not specified)')
@click.option('--dry-run', is_flag=True, help='Show what would be done without executing')
def enforce_retention_policies(policy_ids, dry_run):
    """Enforce data retention policies"""
    
    async def _enforce():
        await cli_instance.initialize()
        try:
            policy_list = policy_ids.split(',') if policy_ids else None
            
            results = await cli_instance.compliance_manager.retention_enforcer.enforce_retention_policies(
                policy_ids=policy_list,
                dry_run=dry_run
            )
            
            click.echo(f"✓ Retention enforcement {'(dry run) ' if dry_run else ''}completed")
            click.echo(f"  Policies processed: {results['policies_processed']}")
            click.echo(f"  Records processed: {results['records_processed']}")
            click.echo(f"  Actions taken:")
            for action, count in results['actions_taken'].items():
                if count > 0:
                    click.echo(f"    {action}: {count}")
            
            if results['errors']:
                click.echo(f"  Errors: {len(results['errors'])}")
                for error in results['errors'][:5]:  # Show first 5 errors
                    click.echo(f"    - {error}")
            
        finally:
            await cli_instance.cleanup()
    
    asyncio.run(_enforce())


@retention.command('check-expiring')
@click.option('--days-ahead', default=7, help='Days ahead to check for expiring data')
def check_expiring_data(days_ahead):
    """Check for data that will expire soon"""
    
    async def _check():
        await cli_instance.initialize()
        try:
            results = await cli_instance.compliance_manager.retention_enforcer.check_expiring_data(days_ahead)
            
            click.echo(f"Data Expiring in {days_ahead} Days")
            click.echo("=" * 40)
            click.echo(f"Total expiring records: {results['total_expiring']}")
            click.echo(f"Notifications sent: {results['notifications_sent']}")
            
            # Group by policy
            for policy_id, records in results['by_policy'].items():
                click.echo(f"\nPolicy {policy_id}: {len(records)} records")
                for record in records[:3]:  # Show first 3 records per policy
                    click.echo(f"  - {record['record_id']} (expires: {record['expires_at']})")
                if len(records) > 3:
                    click.echo(f"  ... and {len(records) - 3} more")
            
        finally:
            await cli_instance.cleanup()
    
    asyncio.run(_check())


@retention.command('statistics')
def retention_statistics():
    """Show data retention statistics"""
    
    async def _stats():
        await cli_instance.initialize()
        try:
            stats = await cli_instance.compliance_manager.retention_enforcer.get_retention_statistics()
            
            click.echo("Data Retention Statistics")
            click.echo("=" * 40)
            click.echo(f"Total policies: {stats['total_policies']}")
            click.echo(f"Total records: {stats['total_records']}")
            click.echo(f"Expired records: {stats['expired_records']}")
            click.echo(f"Expiring soon: {stats['expiring_soon']}")
            
            click.echo("\nBy Status:")
            for status, count in stats['by_status'].items():
                click.echo(f"  {status}: {count}")
            
            click.echo("\nBy Category:")
            for category, count in stats['by_category'].items():
                click.echo(f"  {category}: {count}")
            
        finally:
            await cli_instance.cleanup()
    
    asyncio.run(_stats())


@cli.group()
def monitoring():
    """Compliance monitoring commands"""
    pass


@monitoring.command('dashboard')
def monitoring_dashboard():
    """Show compliance monitoring dashboard"""
    
    async def _dashboard():
        await cli_instance.initialize()
        try:
            dashboard = await cli_instance.compliance_manager.monitoring_system.generate_monitoring_dashboard()
            
            click.echo("Compliance Monitoring Dashboard")
            click.echo("=" * 50)
            click.echo(f"Generated: {dashboard.generated_at}")
            click.echo(f"Total rules: {dashboard.total_rules}")
            click.echo(f"Active rules: {dashboard.active_rules}")
            click.echo(f"Total violations: {dashboard.total_violations}")
            click.echo(f"Open violations: {dashboard.open_violations}")
            
            click.echo("\nViolations by Severity:")
            click.echo(f"  Critical: {dashboard.critical_violations}")
            click.echo(f"  High: {dashboard.high_violations}")
            click.echo(f"  Medium: {dashboard.medium_violations}")
            click.echo(f"  Low: {dashboard.low_violations}")
            
            click.echo("\nViolation Trends:")
            click.echo(f"  Last 24h: {dashboard.violations_last_24h}")
            click.echo(f"  Last 7d: {dashboard.violations_last_7d}")
            click.echo(f"  Last 30d: {dashboard.violations_last_30d}")
            
            if dashboard.overdue_violations:
                click.echo(f"\n⚠️  Overdue violations: {len(dashboard.overdue_violations)}")
            
            click.echo(f"\nOverall compliance score: {dashboard.overall_compliance_score:.1f}%")
            
        finally:
            await cli_instance.cleanup()
    
    asyncio.run(_dashboard())


@monitoring.command('violations')
@click.option('--status', type=click.Choice(['open', 'resolved', 'investigating']))
@click.option('--severity', type=click.Choice(['low', 'medium', 'high', 'critical']))
@click.option('--days-back', default=30, help='Days back to search')
def list_violations(status, severity, days_back):
    """List compliance violations"""
    
    async def _violations():
        await cli_instance.initialize()
        try:
            # Convert severity to enum if provided
            severity_enum = None
            if severity:
                severity_enum = ViolationSeverity(severity)
            
            report = await cli_instance.compliance_manager.monitoring_system.get_violation_report(
                severity=severity_enum,
                status=status,
                days_back=days_back
            )
            
            click.echo(f"Compliance Violations ({days_back} days)")
            click.echo("=" * 50)
            click.echo(f"Total violations: {report['summary']['total_violations']}")
            
            click.echo("\nBy Severity:")
            for sev, count in report['summary']['by_severity'].items():
                click.echo(f"  {sev}: {count}")
            
            click.echo("\nBy Status:")
            for st, count in report['summary']['by_status'].items():
                click.echo(f"  {st}: {count}")
            
            click.echo(f"\nAverage risk score: {report['summary']['average_risk_score']:.1f}")
            
            # Show recent violations
            click.echo("\nRecent Violations:")
            for violation in report['violations'][:10]:  # Show first 10
                status_icon = "🔴" if violation['severity'] == 'critical' else "🟡" if violation['severity'] == 'high' else "🟢"
                overdue_text = " (OVERDUE)" if violation['is_overdue'] else ""
                click.echo(f"  {status_icon} {violation['title']}{overdue_text}")
                click.echo(f"    ID: {violation['violation_id']}")
                click.echo(f"    Severity: {violation['severity']} | Risk: {violation['risk_score']:.1f}")
                click.echo(f"    Detected: {violation['detected_at']}")
                click.echo()
            
        finally:
            await cli_instance.cleanup()
    
    asyncio.run(_violations())


@cli.group()
def audit():
    """Audit trail management commands"""
    pass


@audit.command('verify')
@click.option('--days-back', default=7, help='Days back to verify')
@click.option('--categories', help='Comma-separated audit categories')
def verify_audit_trail(days_back, categories):
    """Verify audit trail completeness and integrity"""
    
    async def _verify():
        await cli_instance.initialize()
        try:
            end_time = datetime.now(timezone.utc)
            start_time = end_time - timedelta(days=days_back)
            
            # Parse categories if provided
            category_list = None
            if categories:
                from audit_trail_verifier import AuditEventCategory
                category_list = [AuditEventCategory(cat.strip()) for cat in categories.split(',')]
            
            # Verify completeness
            completeness_check = await cli_instance.compliance_manager.audit_verifier.verify_audit_trail_completeness(
                start_time, end_time, category_list
            )
            
            # Verify integrity
            integrity_check = await cli_instance.compliance_manager.audit_verifier.verify_audit_trail_integrity(
                start_time, end_time
            )
            
            click.echo(f"Audit Trail Verification ({days_back} days)")
            click.echo("=" * 50)
            
            click.echo("Completeness Check:")
            click.echo(f"  Status: {completeness_check.overall_status.value}")
            click.echo(f"  Events checked: {completeness_check.total_events_checked}")
            click.echo(f"  Gaps found: {len(completeness_check.gaps_found)}")
            click.echo(f"  Completeness score: {completeness_check.completeness_score:.1f}%")
            
            click.echo("\nIntegrity Check:")
            click.echo(f"  Status: {integrity_check.overall_status.value}")
            click.echo(f"  Integrity score: {integrity_check.integrity_score:.1f}%")
            click.echo(f"  Gaps found: {len(integrity_check.gaps_found)}")
            
            # Show gaps if any
            all_gaps = completeness_check.gaps_found + integrity_check.gaps_found
            if all_gaps:
                click.echo(f"\n⚠️  Issues Found ({len(all_gaps)}):")
                for gap in all_gaps[:5]:  # Show first 5 gaps
                    click.echo(f"  - {gap.description} ({gap.severity})")
                    click.echo(f"    Duration: {gap.duration_minutes} minutes")
                if len(all_gaps) > 5:
                    click.echo(f"  ... and {len(all_gaps) - 5} more")
            
        finally:
            await cli_instance.cleanup()
    
    asyncio.run(_verify())


@cli.command('assessment')
@click.option('--output', '-o', help='Output file path')
@click.option('--format', 'output_format', default='text', type=click.Choice(['json', 'text']))
def full_assessment(output, output_format):
    """Perform full compliance assessment"""
    
    async def _assess():
        await cli_instance.initialize()
        try:
            click.echo("Performing full compliance assessment...")
            
            status = await cli_instance.compliance_manager.perform_full_compliance_assessment()
            
            if output_format == 'json':
                # Convert to dict for JSON serialization
                status_dict = {
                    "overall_score": status.overall_score,
                    "gdpr_compliant": status.gdpr_compliant,
                    "data_retention_compliant": status.data_retention_compliant,
                    "audit_trail_compliant": status.audit_trail_compliant,
                    "evidence_complete": status.evidence_complete,
                    "violations_count": status.violations_count,
                    "critical_violations": status.critical_violations,
                    "last_assessment": status.last_assessment.isoformat(),
                    "next_assessment": status.next_assessment.isoformat(),
                    "recommendations": status.recommendations
                }
                
                status_json = json.dumps(status_dict, indent=2)
                if output:
                    Path(output).write_text(status_json)
                    click.echo(f"✓ Assessment saved to: {output}")
                else:
                    click.echo(status_json)
            else:
                # Text format
                click.echo("\nCompliance Assessment Results")
                click.echo("=" * 50)
                click.echo(f"Overall Score: {status.overall_score:.1f}%")
                
                compliance_status = "COMPLIANT" if status.overall_score >= 90 else "NON-COMPLIANT"
                status_color = click.style(compliance_status, fg='green' if status.overall_score >= 90 else 'red')
                click.echo(f"Status: {status_color}")
                
                click.echo(f"\nComponent Status:")
                click.echo(f"  GDPR: {'✓' if status.gdpr_compliant else '✗'}")
                click.echo(f"  Data Retention: {'✓' if status.data_retention_compliant else '✗'}")
                click.echo(f"  Audit Trail: {'✓' if status.audit_trail_compliant else '✗'}")
                click.echo(f"  Evidence Collection: {'✓' if status.evidence_complete else '✗'}")
                
                click.echo(f"\nViolations:")
                click.echo(f"  Open: {status.violations_count}")
                click.echo(f"  Critical: {status.critical_violations}")
                
                if status.recommendations:
                    click.echo(f"\nRecommendations ({len(status.recommendations)}):")
                    for i, rec in enumerate(status.recommendations, 1):
                        click.echo(f"  {i}. {rec}")
                
                click.echo(f"\nNext Assessment: {status.next_assessment.strftime('%Y-%m-%d %H:%M')}")
            
        finally:
            await cli_instance.cleanup()
    
    asyncio.run(_assess())


@cli.command('report')
@click.option('--output', '-o', help='Output file path')
@click.option('--format', 'output_format', default='json', type=click.Choice(['json', 'text']))
def comprehensive_report(output, output_format):
    """Generate comprehensive compliance report"""
    
    async def _report():
        await cli_instance.initialize()
        try:
            click.echo("Generating comprehensive compliance report...")
            
            report = await cli_instance.compliance_manager.generate_comprehensive_compliance_report()
            
            if output_format == 'json':
                report_json = json.dumps(report, indent=2, default=str)
                if output:
                    Path(output).write_text(report_json)
                    click.echo(f"✓ Comprehensive report saved to: {output}")
                else:
                    click.echo(report_json)
            else:
                # Text format
                click.echo("\nComprehensive Compliance Report")
                click.echo("=" * 60)
                click.echo(f"Report ID: {report['report_id']}")
                click.echo(f"Generated: {report['generated_at']}")
                
                overall = report['overall_compliance']
                click.echo(f"\nOverall Compliance: {overall['score']:.1f}% ({overall['status']})")
                
                click.echo(f"\nGDPR Compliance:")
                gdpr = report['gdpr_compliance']
                click.echo(f"  Status: {gdpr['status']}")
                click.echo(f"  Data subjects: {gdpr['data_subjects']}")
                click.echo(f"  Processing records: {gdpr['processing_records']}")
                click.echo(f"  Pending erasure requests: {gdpr['erasure_requests']}")
                
                click.echo(f"\nData Retention:")
                retention = report['data_retention']
                click.echo(f"  Total records: {retention['total_records']}")
                click.echo(f"  Expired records: {retention['expired_records']}")
                click.echo(f"  Expiring soon: {retention['expiring_soon']}")
                
                click.echo(f"\nMonitoring:")
                monitoring = report['monitoring']
                click.echo(f"  Total violations: {monitoring['total_violations']}")
                click.echo(f"  Open violations: {monitoring['open_violations']}")
                click.echo(f"  Critical violations: {monitoring['critical_violations']}")
                
                click.echo(f"\nAudit Trail:")
                audit = report['audit_trail']
                click.echo(f"  Overall score: {audit['overall_score']:.1f}%")
                click.echo(f"  Integrity score: {audit['integrity_score']:.1f}%")
                click.echo(f"  Gaps found: {audit['gaps_found']}")
                
                if report['recommendations']:
                    click.echo(f"\nRecommendations:")
                    for i, rec in enumerate(report['recommendations'], 1):
                        click.echo(f"  {i}. {rec}")
                
                click.echo(f"\nExecutive Summary:")
                click.echo(report['executive_summary'])
            
        finally:
            await cli_instance.cleanup()
    
    asyncio.run(_report())


if __name__ == '__main__':
    cli()