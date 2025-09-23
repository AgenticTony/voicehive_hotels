"""
SLO Monitoring and Error Budget Tracking System
Production-grade SLO compliance monitoring with burn rate alerting
"""

import asyncio
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, asdict
import aiohttp
import json
from logging_adapter import get_safe_logger
from sli_slo_config import (
    SLODefinition, SLOCompliance, BurnRateWindow, 
    ErrorBudgetPolicy, SLO_REGISTRY
)

logger = get_safe_logger("slo_monitor")

@dataclass
class SLOStatus:
    """Current SLO status and compliance information"""
    slo_name: str
    service: str
    current_sli_value: float
    target_percentage: float
    compliance_period: str
    compliance_status: SLOCompliance
    error_budget_remaining: float  # Percentage remaining
    error_budget_consumed: float   # Percentage consumed
    burn_rate_1h: float
    burn_rate_6h: float
    burn_rate_24h: float
    burn_rate_72h: float
    last_updated: datetime
    alerts_active: List[str]
    metadata: Dict[str, Any]

@dataclass
class ErrorBudgetAlert:
    """Error budget alert information"""
    slo_name: str
    alert_type: str  # "burn_rate", "exhaustion", "violation"
    severity: str    # "critical", "warning", "info"
    message: str
    current_value: float
    threshold: float
    window: str
    timestamp: datetime
    runbook_url: str

class PrometheusClient:
    """Async Prometheus client for SLO queries"""
    
    def __init__(self, prometheus_url: str, timeout: int = 30):
        self.prometheus_url = prometheus_url.rstrip('/')
        self.timeout = timeout
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=self.timeout)
        )
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def query(self, query: str, time_param: Optional[str] = None) -> Dict[str, Any]:
        """Execute Prometheus query"""
        if not self.session:
            raise RuntimeError("PrometheusClient not initialized. Use async context manager.")
        
        params = {'query': query}
        if time_param:
            params['time'] = time_param
        
        try:
            async with self.session.get(
                f"{self.prometheus_url}/api/v1/query",
                params=params
            ) as response:
                response.raise_for_status()
                data = await response.json()
                
                if data['status'] != 'success':
                    raise ValueError(f"Prometheus query failed: {data.get('error', 'Unknown error')}")
                
                return data['data']
                
        except Exception as e:
            logger.error(
                "prometheus_query_failed",
                query=query,
                error=str(e),
                prometheus_url=self.prometheus_url
            )
            raise
    
    async def query_range(self, query: str, start: str, end: str, step: str) -> Dict[str, Any]:
        """Execute Prometheus range query"""
        if not self.session:
            raise RuntimeError("PrometheusClient not initialized. Use async context manager.")
        
        params = {
            'query': query,
            'start': start,
            'end': end,
            'step': step
        }
        
        try:
            async with self.session.get(
                f"{self.prometheus_url}/api/v1/query_range",
                params=params
            ) as response:
                response.raise_for_status()
                data = await response.json()
                
                if data['status'] != 'success':
                    raise ValueError(f"Prometheus range query failed: {data.get('error', 'Unknown error')}")
                
                return data['data']
                
        except Exception as e:
            logger.error(
                "prometheus_range_query_failed",
                query=query,
                error=str(e)
            )
            raise

class SLOMonitor:
    """SLO monitoring and error budget tracking system"""
    
    def __init__(self, prometheus_url: str, alert_webhook_url: Optional[str] = None):
        self.prometheus_url = prometheus_url
        self.alert_webhook_url = alert_webhook_url
        self.slo_definitions = {slo.name: slo for slo in SLO_REGISTRY}
        self.current_status: Dict[str, SLOStatus] = {}
        self.active_alerts: Dict[str, List[ErrorBudgetAlert]] = {}
        
    async def evaluate_slo(self, slo: SLODefinition) -> SLOStatus:
        """Evaluate a single SLO and return current status"""
        
        async with PrometheusClient(self.prometheus_url) as prom:
            try:
                # Query current SLI value
                sli_result = await prom.query(slo.sli.query)
                current_sli_value = self._extract_metric_value(sli_result)
                
                if current_sli_value is None:
                    logger.warning(
                        "sli_query_no_data",
                        slo_name=slo.name,
                        query=slo.sli.query
                    )
                    current_sli_value = 0.0
                
                # Convert to percentage if needed
                if slo.sli.unit == "percentage" and current_sli_value <= 1.0:
                    current_sli_value *= 100
                
                # Calculate burn rates for different windows
                burn_rates = await self._calculate_burn_rates(prom, slo)
                
                # Determine compliance status and error budget
                primary_target = slo.targets[0]  # Use first target as primary
                compliance_status, error_budget_remaining, error_budget_consumed = \
                    self._calculate_error_budget(current_sli_value, primary_target)
                
                # Check for active alerts
                alerts_active = await self._check_slo_alerts(slo, current_sli_value, burn_rates, error_budget_consumed)
                
                status = SLOStatus(
                    slo_name=slo.name,
                    service=slo.service,
                    current_sli_value=current_sli_value,
                    target_percentage=primary_target.target_percentage,
                    compliance_period=primary_target.compliance_period,
                    compliance_status=compliance_status,
                    error_budget_remaining=error_budget_remaining,
                    error_budget_consumed=error_budget_consumed,
                    burn_rate_1h=burn_rates.get(BurnRateWindow.FAST, 0.0),
                    burn_rate_6h=burn_rates.get(BurnRateWindow.MEDIUM, 0.0),
                    burn_rate_24h=burn_rates.get(BurnRateWindow.SLOW, 0.0),
                    burn_rate_72h=burn_rates.get(BurnRateWindow.VERY_SLOW, 0.0),
                    last_updated=datetime.utcnow(),
                    alerts_active=alerts_active,
                    metadata={
                        "sli_type": slo.sli.sli_type.value,
                        "tags": slo.tags,
                        "all_targets": [
                            {
                                "target": target.target_percentage,
                                "period": target.compliance_period,
                                "description": target.description
                            }
                            for target in slo.targets
                        ]
                    }
                )
                
                logger.info(
                    "slo_evaluated",
                    slo_name=slo.name,
                    sli_value=current_sli_value,
                    target=primary_target.target_percentage,
                    compliance_status=compliance_status.value,
                    error_budget_remaining=error_budget_remaining,
                    burn_rate_1h=burn_rates.get(BurnRateWindow.FAST, 0.0)
                )
                
                return status
                
            except Exception as e:
                logger.error(
                    "slo_evaluation_failed",
                    slo_name=slo.name,
                    error=str(e)
                )
                
                # Return unknown status on error
                return SLOStatus(
                    slo_name=slo.name,
                    service=slo.service,
                    current_sli_value=0.0,
                    target_percentage=slo.targets[0].target_percentage,
                    compliance_period=slo.targets[0].compliance_period,
                    compliance_status=SLOCompliance.UNKNOWN,
                    error_budget_remaining=0.0,
                    error_budget_consumed=100.0,
                    burn_rate_1h=0.0,
                    burn_rate_6h=0.0,
                    burn_rate_24h=0.0,
                    burn_rate_72h=0.0,
                    last_updated=datetime.utcnow(),
                    alerts_active=["evaluation_failed"],
                    metadata={"error": str(e)}
                )
    
    async def _calculate_burn_rates(self, prom: PrometheusClient, slo: SLODefinition) -> Dict[BurnRateWindow, float]:
        """Calculate burn rates for different time windows"""
        burn_rates = {}
        
        for window in BurnRateWindow:
            try:
                # Calculate error rate for the window
                error_rate_query = self._build_error_rate_query(slo, window.value)
                result = await prom.query(error_rate_query)
                error_rate = self._extract_metric_value(result) or 0.0
                
                # Convert error rate to burn rate
                # Burn rate = (error rate) / (error budget rate)
                target_percentage = slo.targets[0].target_percentage
                error_budget_rate = (100 - target_percentage) / 100
                
                if error_budget_rate > 0:
                    burn_rate = error_rate / error_budget_rate
                else:
                    burn_rate = 0.0
                
                burn_rates[window] = burn_rate
                
            except Exception as e:
                logger.warning(
                    "burn_rate_calculation_failed",
                    slo_name=slo.name,
                    window=window.value,
                    error=str(e)
                )
                burn_rates[window] = 0.0
        
        return burn_rates
    
    def _build_error_rate_query(self, slo: SLODefinition, window: str) -> str:
        """Build Prometheus query for error rate calculation"""
        base_query = slo.sli.query
        
        # Replace [5m] with the appropriate window
        if slo.sli.good_total_ratio:
            # For good/total ratios, error rate = 1 - good_rate
            error_query = f"1 - ({base_query.replace('[5m]', f'[{window}]')})"
        else:
            # For bad/total ratios, use directly
            error_query = base_query.replace('[5m]', f'[{window}]')
        
        return error_query
    
    def _calculate_error_budget(self, current_sli: float, target: Any) -> Tuple[SLOCompliance, float, float]:
        """Calculate error budget status"""
        target_percentage = target.target_percentage
        
        if current_sli >= target_percentage:
            compliance_status = SLOCompliance.COMPLIANT
            # Error budget remaining calculation
            error_budget_consumed = max(0, (target_percentage - current_sli) / (100 - target_percentage) * 100)
        else:
            # SLO is violated
            compliance_status = SLOCompliance.VIOLATED
            error_budget_consumed = 100.0  # Fully consumed when violated
        
        # Check if at risk (consuming budget quickly)
        if compliance_status == SLOCompliance.COMPLIANT and error_budget_consumed > 50:
            compliance_status = SLOCompliance.AT_RISK
        
        error_budget_remaining = max(0, 100 - error_budget_consumed)
        
        return compliance_status, error_budget_remaining, error_budget_consumed
    
    async def _check_slo_alerts(self, slo: SLODefinition, current_sli: float, 
                               burn_rates: Dict[BurnRateWindow, float], 
                               error_budget_consumed: float) -> List[str]:
        """Check for SLO-related alerts"""
        alerts = []
        
        # Check burn rate thresholds
        for window, burn_rate in burn_rates.items():
            threshold = slo.error_budget_policy.burn_rate_thresholds.get(window, float('inf'))
            if burn_rate > threshold:
                alert_name = f"burn_rate_{window.value}_exceeded"
                alerts.append(alert_name)
                
                # Create alert object
                alert = ErrorBudgetAlert(
                    slo_name=slo.name,
                    alert_type="burn_rate",
                    severity="critical" if window in [BurnRateWindow.FAST, BurnRateWindow.MEDIUM] else "warning",
                    message=f"Burn rate for {window.value} window ({burn_rate:.2f}) exceeds threshold ({threshold:.2f})",
                    current_value=burn_rate,
                    threshold=threshold,
                    window=window.value,
                    timestamp=datetime.utcnow(),
                    runbook_url=f"https://docs.voicehive.com/runbooks/slo-burn-rate/{slo.name}"
                )
                
                await self._send_alert(alert)
        
        # Check error budget exhaustion
        if error_budget_consumed >= slo.error_budget_policy.alert_on_exhaustion_percentage:
            alert_name = "error_budget_exhaustion"
            alerts.append(alert_name)
            
            alert = ErrorBudgetAlert(
                slo_name=slo.name,
                alert_type="exhaustion",
                severity="critical",
                message=f"Error budget {error_budget_consumed:.1f}% consumed, exceeds threshold {slo.error_budget_policy.alert_on_exhaustion_percentage:.1f}%",
                current_value=error_budget_consumed,
                threshold=slo.error_budget_policy.alert_on_exhaustion_percentage,
                window="current",
                timestamp=datetime.utcnow(),
                runbook_url=f"https://docs.voicehive.com/runbooks/slo-budget-exhaustion/{slo.name}"
            )
            
            await self._send_alert(alert)
        
        # Check SLO violation
        target_percentage = slo.targets[0].target_percentage
        if current_sli < target_percentage:
            alert_name = "slo_violation"
            alerts.append(alert_name)
            
            alert = ErrorBudgetAlert(
                slo_name=slo.name,
                alert_type="violation",
                severity="critical",
                message=f"SLO violated: current {current_sli:.2f}% < target {target_percentage:.2f}%",
                current_value=current_sli,
                threshold=target_percentage,
                window="current",
                timestamp=datetime.utcnow(),
                runbook_url=f"https://docs.voicehive.com/runbooks/slo-violation/{slo.name}"
            )
            
            await self._send_alert(alert)
        
        return alerts
    
    async def _send_alert(self, alert: ErrorBudgetAlert):
        """Send alert to configured webhook"""
        if not self.alert_webhook_url:
            logger.info(
                "slo_alert_generated",
                slo_name=alert.slo_name,
                alert_type=alert.alert_type,
                severity=alert.severity,
                message=alert.message
            )
            return
        
        try:
            async with aiohttp.ClientSession() as session:
                payload = {
                    "alert_type": "slo_alert",
                    "slo_name": alert.slo_name,
                    "alert_details": asdict(alert),
                    "timestamp": alert.timestamp.isoformat()
                }
                
                async with session.post(
                    self.alert_webhook_url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    response.raise_for_status()
                    
                logger.info(
                    "slo_alert_sent",
                    slo_name=alert.slo_name,
                    alert_type=alert.alert_type,
                    webhook_url=self.alert_webhook_url
                )
                
        except Exception as e:
            logger.error(
                "slo_alert_send_failed",
                slo_name=alert.slo_name,
                error=str(e),
                webhook_url=self.alert_webhook_url
            )
    
    def _extract_metric_value(self, prometheus_result: Dict[str, Any]) -> Optional[float]:
        """Extract numeric value from Prometheus query result"""
        try:
            result = prometheus_result.get('result', [])
            if not result:
                return None
            
            # Handle vector results
            if isinstance(result, list) and len(result) > 0:
                value_data = result[0].get('value', [])
                if len(value_data) >= 2:
                    return float(value_data[1])
            
            return None
            
        except (ValueError, TypeError, IndexError) as e:
            logger.warning(
                "metric_value_extraction_failed",
                result=prometheus_result,
                error=str(e)
            )
            return None
    
    async def evaluate_all_slos(self) -> Dict[str, SLOStatus]:
        """Evaluate all configured SLOs"""
        results = {}
        
        for slo_name, slo in self.slo_definitions.items():
            if not slo.enabled:
                continue
                
            try:
                status = await self.evaluate_slo(slo)
                results[slo_name] = status
                self.current_status[slo_name] = status
                
            except Exception as e:
                logger.error(
                    "slo_evaluation_error",
                    slo_name=slo_name,
                    error=str(e)
                )
        
        return results
    
    async def get_slo_dashboard_data(self) -> Dict[str, Any]:
        """Get SLO data formatted for dashboard display"""
        await self.evaluate_all_slos()
        
        dashboard_data = {
            "summary": {
                "total_slos": len(self.current_status),
                "compliant": len([s for s in self.current_status.values() if s.compliance_status == SLOCompliance.COMPLIANT]),
                "at_risk": len([s for s in self.current_status.values() if s.compliance_status == SLOCompliance.AT_RISK]),
                "violated": len([s for s in self.current_status.values() if s.compliance_status == SLOCompliance.VIOLATED]),
                "unknown": len([s for s in self.current_status.values() if s.compliance_status == SLOCompliance.UNKNOWN]),
                "last_updated": datetime.utcnow().isoformat()
            },
            "slos": {
                name: {
                    "name": status.slo_name,
                    "service": status.service,
                    "current_sli": status.current_sli_value,
                    "target": status.target_percentage,
                    "compliance_status": status.compliance_status.value,
                    "error_budget_remaining": status.error_budget_remaining,
                    "burn_rates": {
                        "1h": status.burn_rate_1h,
                        "6h": status.burn_rate_6h,
                        "24h": status.burn_rate_24h,
                        "72h": status.burn_rate_72h
                    },
                    "alerts_active": status.alerts_active,
                    "metadata": status.metadata
                }
                for name, status in self.current_status.items()
            }
        }
        
        return dashboard_data
    
    async def start_monitoring(self, interval_seconds: int = 60):
        """Start continuous SLO monitoring"""
        logger.info(
            "slo_monitoring_started",
            interval_seconds=interval_seconds,
            slo_count=len(self.slo_definitions)
        )
        
        while True:
            try:
                await self.evaluate_all_slos()
                await asyncio.sleep(interval_seconds)
                
            except Exception as e:
                logger.error(
                    "slo_monitoring_cycle_failed",
                    error=str(e)
                )
                await asyncio.sleep(min(interval_seconds, 30))  # Shorter retry interval on error

# Global SLO monitor instance
slo_monitor: Optional[SLOMonitor] = None

def get_slo_monitor(prometheus_url: str, alert_webhook_url: Optional[str] = None) -> SLOMonitor:
    """Get or create global SLO monitor instance"""
    global slo_monitor
    
    if slo_monitor is None:
        slo_monitor = SLOMonitor(prometheus_url, alert_webhook_url)
    
    return slo_monitor