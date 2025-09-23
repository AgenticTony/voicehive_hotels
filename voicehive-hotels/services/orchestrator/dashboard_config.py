"""
Dashboard Configuration for VoiceHive Hotels
Grafana dashboard definitions for business metrics and system health
"""

import json
from typing import Dict, List, Any
from dataclasses import dataclass, asdict


@dataclass
class GrafanaPanel:
    """Grafana panel configuration"""
    id: int
    title: str
    type: str
    targets: List[Dict[str, Any]]
    gridPos: Dict[str, int]
    options: Dict[str, Any] = None
    fieldConfig: Dict[str, Any] = None
    alert: Dict[str, Any] = None


@dataclass
class GrafanaDashboard:
    """Grafana dashboard configuration"""
    id: int
    title: str
    tags: List[str]
    panels: List[GrafanaPanel]
    time: Dict[str, str]
    refresh: str
    templating: Dict[str, Any] = None
    annotations: Dict[str, Any] = None


class DashboardGenerator:
    """Generate Grafana dashboards for VoiceHive Hotels"""
    
    def __init__(self):
        self.panel_id_counter = 1
    
    def _get_next_panel_id(self) -> int:
        """Get next panel ID"""
        panel_id = self.panel_id_counter
        self.panel_id_counter += 1
        return panel_id
    
    def create_business_metrics_dashboard(self) -> Dict[str, Any]:
        """Create business metrics dashboard"""
        panels = []
        
        # Call Success Rate Panel
        panels.append(GrafanaPanel(
            id=self._get_next_panel_id(),
            title="Call Success Rate",
            type="stat",
            targets=[{
                "expr": "rate(voicehive_call_success_total[5m]) / (rate(voicehive_call_success_total[5m]) + rate(voicehive_call_failures_total[5m])) * 100",
                "legendFormat": "Success Rate %",
                "refId": "A"
            }],
            gridPos={"h": 8, "w": 6, "x": 0, "y": 0},
            options={
                "reduceOptions": {
                    "values": False,
                    "calcs": ["lastNotNull"],
                    "fields": ""
                },
                "orientation": "auto",
                "textMode": "auto",
                "colorMode": "value",
                "graphMode": "area",
                "justifyMode": "auto"
            },
            fieldConfig={
                "defaults": {
                    "color": {"mode": "thresholds"},
                    "thresholds": {
                        "steps": [
                            {"color": "red", "value": None},
                            {"color": "yellow", "value": 95},
                            {"color": "green", "value": 99}
                        ]
                    },
                    "unit": "percent",
                    "min": 0,
                    "max": 100
                }
            }
        ))
        
        # Active Calls Panel
        panels.append(GrafanaPanel(
            id=self._get_next_panel_id(),
            title="Active Calls",
            type="stat",
            targets=[{
                "expr": "sum(voicehive_concurrent_calls)",
                "legendFormat": "Active Calls",
                "refId": "A"
            }],
            gridPos={"h": 8, "w": 6, "x": 6, "y": 0},
            options={
                "reduceOptions": {
                    "values": False,
                    "calcs": ["lastNotNull"],
                    "fields": ""
                },
                "orientation": "auto",
                "textMode": "auto",
                "colorMode": "value",
                "graphMode": "area"
            },
            fieldConfig={
                "defaults": {
                    "color": {"mode": "palette-classic"},
                    "unit": "short"
                }
            }
        ))
        
        # PMS Response Time Panel
        panels.append(GrafanaPanel(
            id=self._get_next_panel_id(),
            title="PMS Response Time",
            type="stat",
            targets=[{
                "expr": "histogram_quantile(0.95, rate(voicehive_pms_response_seconds_bucket[5m]))",
                "legendFormat": "95th Percentile",
                "refId": "A"
            }],
            gridPos={"h": 8, "w": 6, "x": 12, "y": 0},
            options={
                "reduceOptions": {
                    "values": False,
                    "calcs": ["lastNotNull"],
                    "fields": ""
                },
                "orientation": "auto",
                "textMode": "auto",
                "colorMode": "value",
                "graphMode": "area"
            },
            fieldConfig={
                "defaults": {
                    "color": {"mode": "thresholds"},
                    "thresholds": {
                        "steps": [
                            {"color": "green", "value": None},
                            {"color": "yellow", "value": 2},
                            {"color": "red", "value": 5}
                        ]
                    },
                    "unit": "s"
                }
            }
        ))
        
        # Guest Satisfaction Panel
        panels.append(GrafanaPanel(
            id=self._get_next_panel_id(),
            title="Guest Satisfaction Score",
            type="stat",
            targets=[{
                "expr": "histogram_quantile(0.5, rate(voicehive_guest_satisfaction_bucket[1h]))",
                "legendFormat": "Average Score",
                "refId": "A"
            }],
            gridPos={"h": 8, "w": 6, "x": 18, "y": 0},
            options={
                "reduceOptions": {
                    "values": False,
                    "calcs": ["lastNotNull"],
                    "fields": ""
                },
                "orientation": "auto",
                "textMode": "auto",
                "colorMode": "value",
                "graphMode": "area"
            },
            fieldConfig={
                "defaults": {
                    "color": {"mode": "thresholds"},
                    "thresholds": {
                        "steps": [
                            {"color": "red", "value": None},
                            {"color": "yellow", "value": 3},
                            {"color": "green", "value": 4}
                        ]
                    },
                    "unit": "short",
                    "min": 1,
                    "max": 5
                }
            }
        ))
        
        # Call Volume Over Time
        panels.append(GrafanaPanel(
            id=self._get_next_panel_id(),
            title="Call Volume Over Time",
            type="timeseries",
            targets=[{
                "expr": "rate(voicehive_call_success_total[5m]) + rate(voicehive_call_failures_total[5m])",
                "legendFormat": "Calls/sec",
                "refId": "A"
            }],
            gridPos={"h": 8, "w": 12, "x": 0, "y": 8},
            fieldConfig={
                "defaults": {
                    "color": {"mode": "palette-classic"},
                    "unit": "reqps"
                }
            }
        ))
        
        # PMS Operations Success Rate
        panels.append(GrafanaPanel(
            id=self._get_next_panel_id(),
            title="PMS Operations Success Rate",
            type="timeseries",
            targets=[{
                "expr": "rate(voicehive_pms_operations_total{status=\"success\"}[5m]) / rate(voicehive_pms_operations_total[5m]) * 100",
                "legendFormat": "{{pms_type}} - {{operation}}",
                "refId": "A"
            }],
            gridPos={"h": 8, "w": 12, "x": 12, "y": 8},
            fieldConfig={
                "defaults": {
                    "color": {"mode": "palette-classic"},
                    "unit": "percent",
                    "min": 0,
                    "max": 100
                }
            }
        ))
        
        # Revenue Impact
        panels.append(GrafanaPanel(
            id=self._get_next_panel_id(),
            title="Revenue Impact by Hotel",
            type="barchart",
            targets=[{
                "expr": "sum by (hotel_id) (rate(voicehive_revenue_impact_total[1h]))",
                "legendFormat": "{{hotel_id}}",
                "refId": "A"
            }],
            gridPos={"h": 8, "w": 24, "x": 0, "y": 16},
            fieldConfig={
                "defaults": {
                    "color": {"mode": "palette-classic"},
                    "unit": "currencyUSD"
                }
            }
        ))
        
        dashboard = GrafanaDashboard(
            id=1,
            title="VoiceHive Hotels - Business Metrics",
            tags=["voicehive", "business", "kpi"],
            panels=panels,
            time={"from": "now-1h", "to": "now"},
            refresh="30s",
            templating={
                "list": [
                    {
                        "name": "hotel_id",
                        "type": "query",
                        "query": "label_values(voicehive_call_success_total, hotel_id)",
                        "refresh": 1,
                        "includeAll": True,
                        "multi": True
                    }
                ]
            }
        )
        
        return self._dashboard_to_json(dashboard)
    
    def create_system_health_dashboard(self) -> Dict[str, Any]:
        """Create system health dashboard"""
        panels = []
        
        # System Overview Row
        panels.append(GrafanaPanel(
            id=self._get_next_panel_id(),
            title="System Health Overview",
            type="row",
            targets=[],
            gridPos={"h": 1, "w": 24, "x": 0, "y": 0}
        ))
        
        # CPU Usage
        panels.append(GrafanaPanel(
            id=self._get_next_panel_id(),
            title="CPU Usage",
            type="timeseries",
            targets=[{
                "expr": "voicehive_cpu_usage_percent",
                "legendFormat": "{{component}}",
                "refId": "A"
            }],
            gridPos={"h": 8, "w": 8, "x": 0, "y": 1},
            fieldConfig={
                "defaults": {
                    "color": {"mode": "palette-classic"},
                    "unit": "percent",
                    "min": 0,
                    "max": 100
                }
            }
        ))
        
        # Memory Usage
        panels.append(GrafanaPanel(
            id=self._get_next_panel_id(),
            title="Memory Usage",
            type="timeseries",
            targets=[{
                "expr": "voicehive_memory_usage_bytes / 1024 / 1024",
                "legendFormat": "{{component}}",
                "refId": "A"
            }],
            gridPos={"h": 8, "w": 8, "x": 8, "y": 1},
            fieldConfig={
                "defaults": {
                    "color": {"mode": "palette-classic"},
                    "unit": "decbytes"
                }
            }
        ))
        
        # Active Connections
        panels.append(GrafanaPanel(
            id=self._get_next_panel_id(),
            title="Active Connections",
            type="timeseries",
            targets=[{
                "expr": "voicehive_active_connections",
                "legendFormat": "{{connection_type}}",
                "refId": "A"
            }],
            gridPos={"h": 8, "w": 8, "x": 16, "y": 1},
            fieldConfig={
                "defaults": {
                    "color": {"mode": "palette-classic"},
                    "unit": "short"
                }
            }
        ))
        
        # Error Rates
        panels.append(GrafanaPanel(
            id=self._get_next_panel_id(),
            title="Error Rates",
            type="timeseries",
            targets=[{
                "expr": "rate(voicehive_errors_total[5m])",
                "legendFormat": "{{error_type}}",
                "refId": "A"
            }],
            gridPos={"h": 8, "w": 12, "x": 0, "y": 9},
            fieldConfig={
                "defaults": {
                    "color": {"mode": "palette-classic"},
                    "unit": "reqps"
                }
            }
        ))
        
        # Response Times
        panels.append(GrafanaPanel(
            id=self._get_next_panel_id(),
            title="Response Times (95th Percentile)",
            type="timeseries",
            targets=[{
                "expr": "histogram_quantile(0.95, rate(voicehive_request_duration_seconds_bucket[5m]))",
                "legendFormat": "{{endpoint}}",
                "refId": "A"
            }],
            gridPos={"h": 8, "w": 12, "x": 12, "y": 9},
            fieldConfig={
                "defaults": {
                    "color": {"mode": "palette-classic"},
                    "unit": "s"
                }
            }
        ))
        
        dashboard = GrafanaDashboard(
            id=2,
            title="VoiceHive Hotels - System Health",
            tags=["voicehive", "system", "health"],
            panels=panels,
            time={"from": "now-1h", "to": "now"},
            refresh="30s"
        )
        
        return self._dashboard_to_json(dashboard)
    
    def create_sla_monitoring_dashboard(self) -> Dict[str, Any]:
        """Create SLA monitoring dashboard"""
        panels = []
        
        # SLA Overview
        panels.append(GrafanaPanel(
            id=self._get_next_panel_id(),
            title="SLA Compliance Overview",
            type="stat",
            targets=[{
                "expr": "voicehive_sla_compliance_percentage",
                "legendFormat": "{{sla_name}}",
                "refId": "A"
            }],
            gridPos={"h": 8, "w": 24, "x": 0, "y": 0},
            options={
                "reduceOptions": {
                    "values": False,
                    "calcs": ["lastNotNull"],
                    "fields": ""
                },
                "orientation": "horizontal",
                "textMode": "auto",
                "colorMode": "value"
            },
            fieldConfig={
                "defaults": {
                    "color": {"mode": "thresholds"},
                    "thresholds": {
                        "steps": [
                            {"color": "red", "value": None},
                            {"color": "yellow", "value": 95},
                            {"color": "green", "value": 99}
                        ]
                    },
                    "unit": "percent",
                    "min": 0,
                    "max": 100
                }
            }
        ))
        
        # Call Success Rate SLA
        panels.append(GrafanaPanel(
            id=self._get_next_panel_id(),
            title="Call Success Rate SLA (99%)",
            type="timeseries",
            targets=[
                {
                    "expr": "rate(voicehive_call_success_total[5m]) / (rate(voicehive_call_success_total[5m]) + rate(voicehive_call_failures_total[5m])) * 100",
                    "legendFormat": "Current Success Rate",
                    "refId": "A"
                },
                {
                    "expr": "99",
                    "legendFormat": "SLA Target (99%)",
                    "refId": "B"
                }
            ],
            gridPos={"h": 8, "w": 12, "x": 0, "y": 8},
            fieldConfig={
                "defaults": {
                    "color": {"mode": "palette-classic"},
                    "unit": "percent",
                    "min": 95,
                    "max": 100
                }
            }
        ))
        
        # PMS Availability SLA
        panels.append(GrafanaPanel(
            id=self._get_next_panel_id(),
            title="PMS Availability SLA (99.5%)",
            type="timeseries",
            targets=[
                {
                    "expr": "voicehive_pms_availability * 100",
                    "legendFormat": "{{hotel_id}} - {{pms_type}}",
                    "refId": "A"
                },
                {
                    "expr": "99.5",
                    "legendFormat": "SLA Target (99.5%)",
                    "refId": "B"
                }
            ],
            gridPos={"h": 8, "w": 12, "x": 12, "y": 8},
            fieldConfig={
                "defaults": {
                    "color": {"mode": "palette-classic"},
                    "unit": "percent",
                    "min": 95,
                    "max": 100
                }
            }
        ))
        
        # SLA Violations
        panels.append(GrafanaPanel(
            id=self._get_next_panel_id(),
            title="SLA Violations (Last 24h)",
            type="table",
            targets=[{
                "expr": "increase(voicehive_sla_violations_total[24h])",
                "legendFormat": "{{sla_name}}",
                "refId": "A",
                "format": "table"
            }],
            gridPos={"h": 8, "w": 24, "x": 0, "y": 16},
            fieldConfig={
                "defaults": {
                    "color": {"mode": "thresholds"},
                    "thresholds": {
                        "steps": [
                            {"color": "green", "value": None},
                            {"color": "yellow", "value": 1},
                            {"color": "red", "value": 5}
                        ]
                    }
                }
            }
        ))
        
        dashboard = GrafanaDashboard(
            id=3,
            title="VoiceHive Hotels - SLA Monitoring",
            tags=["voicehive", "sla", "compliance"],
            panels=panels,
            time={"from": "now-24h", "to": "now"},
            refresh="1m"
        )
        
        return self._dashboard_to_json(dashboard)
    
    def _dashboard_to_json(self, dashboard: GrafanaDashboard) -> Dict[str, Any]:
        """Convert dashboard to JSON format"""
        dashboard_dict = asdict(dashboard)
        
        # Add Grafana-specific fields following official JSON model
        dashboard_dict.update({
            "uid": f"voicehive-{dashboard.id}",
            "version": 1,
            "schemaVersion": 39,  # Updated to latest schema version
            "editable": True,
            "fiscalYearStartMonth": 0,
            "gnetId": None,
            "graphTooltip": 1,  # Shared crosshair
            "links": [],
            "liveNow": False,
            "style": "dark",
            "timezone": "browser",  # Use browser timezone
            "weekStart": "",
            "timepicker": {
                "refresh_intervals": ["5s", "10s", "30s", "1m", "5m", "15m", "30m", "1h", "2h", "1d"],
                "time_options": ["5m", "15m", "1h", "6h", "12h", "24h", "2d", "7d", "30d"]
            }
        })
        
        return dashboard_dict


# Dashboard configurations
dashboard_generator = DashboardGenerator()

BUSINESS_METRICS_DASHBOARD = dashboard_generator.create_business_metrics_dashboard()
SYSTEM_HEALTH_DASHBOARD = dashboard_generator.create_system_health_dashboard()
SLA_MONITORING_DASHBOARD = dashboard_generator.create_sla_monitoring_dashboard()


def export_dashboards_to_files():
    """Export dashboards to JSON files for Grafana import"""
    import os
    
    dashboard_dir = "dashboards"
    os.makedirs(dashboard_dir, exist_ok=True)
    
    dashboards = {
        "business-metrics.json": BUSINESS_METRICS_DASHBOARD,
        "system-health.json": SYSTEM_HEALTH_DASHBOARD,
        "sla-monitoring.json": SLA_MONITORING_DASHBOARD
    }
    
    for filename, dashboard in dashboards.items():
        filepath = os.path.join(dashboard_dir, filename)
        with open(filepath, 'w') as f:
            json.dump(dashboard, f, indent=2)
        print(f"Exported dashboard to {filepath}")


if __name__ == "__main__":
    export_dashboards_to_files()