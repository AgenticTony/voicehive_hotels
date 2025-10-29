"""
Prometheus Client for VoiceHive Hotels
Real-time metrics querying from Prometheus server
"""

import aiohttp
import asyncio
import logging
from typing import Dict, List, Optional, Any, Union
from datetime import datetime, timedelta
from dataclasses import dataclass
from urllib.parse import urljoin, urlencode
import json
import os


@dataclass
class PrometheusQuery:
    """Prometheus query configuration"""
    query: str
    description: str
    expected_type: str = "vector"  # vector, matrix, scalar, string


@dataclass
class MetricResult:
    """Prometheus metric result"""
    metric: Dict[str, str]
    value: Union[float, List[List[Union[float, str]]]]
    timestamp: Optional[float] = None


class PrometheusClientError(Exception):
    """Prometheus client error"""
    pass


class PrometheusClient:
    """
    Client for querying Prometheus HTTP API
    Implements real metrics collection for VoiceHive Hotels monitoring
    """

    def __init__(self,
                 prometheus_url: str = None,
                 timeout: float = 10.0,
                 max_retries: int = 3):
        """
        Initialize Prometheus client

        Args:
            prometheus_url: Prometheus server URL (defaults to env var)
            timeout: Request timeout in seconds
            max_retries: Maximum number of retry attempts
        """
        self.prometheus_url = prometheus_url or os.getenv("PROMETHEUS_URL", "http://prometheus:9090")
        self.timeout = timeout
        self.max_retries = max_retries
        self.logger = logging.getLogger(__name__)

        # Remove trailing slash
        self.prometheus_url = self.prometheus_url.rstrip('/')

        # Common query templates
        self.business_queries = {
            "call_success_rate": PrometheusQuery(
                query="rate(voicehive_call_success_total[5m]) / (rate(voicehive_call_success_total[5m]) + rate(voicehive_call_failures_total[5m])) * 100",
                description="Call success rate percentage"
            ),
            "active_calls": PrometheusQuery(
                query="sum(voicehive_concurrent_calls)",
                description="Current number of active calls"
            ),
            "pms_response_time_p95": PrometheusQuery(
                query="histogram_quantile(0.95, rate(voicehive_pms_response_seconds_bucket[5m]))",
                description="PMS response time 95th percentile"
            ),
            "guest_satisfaction": PrometheusQuery(
                query="histogram_quantile(0.5, rate(voicehive_guest_satisfaction_bucket[1h]))",
                description="Average guest satisfaction score"
            )
        }

        self.performance_queries = {
            "request_rate": PrometheusQuery(
                query="sum(rate(voicehive_requests_total[5m]))",
                description="Current request rate per second"
            ),
            "response_time_p50": PrometheusQuery(
                query="histogram_quantile(0.50, rate(voicehive_request_duration_seconds_bucket[5m]))",
                description="Request response time 50th percentile"
            ),
            "response_time_p95": PrometheusQuery(
                query="histogram_quantile(0.95, rate(voicehive_request_duration_seconds_bucket[5m]))",
                description="Request response time 95th percentile"
            ),
            "response_time_p99": PrometheusQuery(
                query="histogram_quantile(0.99, rate(voicehive_request_duration_seconds_bucket[5m]))",
                description="Request response time 99th percentile"
            ),
            "error_rate": PrometheusQuery(
                query="sum(rate(voicehive_errors_total[5m]))",
                description="Error rate per second"
            ),
            "cpu_usage": PrometheusQuery(
                query="voicehive_cpu_usage_percent",
                description="CPU usage percentage"
            ),
            "memory_usage": PrometheusQuery(
                query="voicehive_memory_usage_bytes / 1024 / 1024",
                description="Memory usage in MB"
            ),
            "active_connections": PrometheusQuery(
                query="voicehive_active_connections",
                description="Active connections count"
            )
        }

        self.circuit_breaker_queries = {
            "database_circuit_breaker_state": PrometheusQuery(
                query="voicehive_database_circuit_breaker_state",
                description="Database circuit breaker states"
            ),
            "tts_circuit_breaker_state": PrometheusQuery(
                query="voicehive_tts_synthesis_circuit_breaker_state",
                description="TTS circuit breaker states"
            ),
            "asr_circuit_breaker_state": PrometheusQuery(
                query="voicehive_asr_circuit_breaker_state",
                description="ASR circuit breaker states"
            ),
            "apaleo_circuit_breaker_state": PrometheusQuery(
                query="voicehive_apaleo_circuit_breaker_state",
                description="Apaleo circuit breaker states"
            )
        }

    async def _make_request(self, endpoint: str, params: Dict[str, str]) -> Dict[str, Any]:
        """
        Make HTTP request to Prometheus API with retry logic

        Args:
            endpoint: API endpoint (query, query_range, etc.)
            params: Query parameters

        Returns:
            Prometheus API response data

        Raises:
            PrometheusClientError: If request fails after all retries
        """
        url = urljoin(self.prometheus_url, f"/api/v1/{endpoint}")

        for attempt in range(self.max_retries + 1):
            try:
                timeout = aiohttp.ClientTimeout(total=self.timeout)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(url, params=params) as response:
                        if response.status == 200:
                            data = await response.json()
                            if data.get("status") == "success":
                                return data.get("data", {})
                            else:
                                error_msg = data.get("error", "Unknown Prometheus error")
                                raise PrometheusClientError(f"Prometheus API error: {error_msg}")
                        else:
                            error_text = await response.text()
                            raise PrometheusClientError(
                                f"HTTP {response.status}: {error_text}"
                            )
            except asyncio.TimeoutError:
                if attempt < self.max_retries:
                    self.logger.warning(
                        "Prometheus request timeout, retrying",
                        attempt=attempt + 1,
                        max_retries=self.max_retries
                    )
                    await asyncio.sleep(2 ** attempt)  # Exponential backoff
                else:
                    raise PrometheusClientError(
                        f"Prometheus request timed out after {self.max_retries} retries"
                    )
            except aiohttp.ClientError as e:
                if attempt < self.max_retries:
                    self.logger.warning(
                        "Prometheus client error, retrying",
                        error=str(e),
                        attempt=attempt + 1
                    )
                    await asyncio.sleep(2 ** attempt)
                else:
                    raise PrometheusClientError(f"Prometheus client error: {str(e)}")

    async def query_instant(self, query: str, time: Optional[datetime] = None) -> List[MetricResult]:
        """
        Execute instant query against Prometheus

        Args:
            query: PromQL query string
            time: Query evaluation time (defaults to now)

        Returns:
            List of metric results
        """
        params = {"query": query}
        if time:
            params["time"] = str(int(time.timestamp()))

        try:
            data = await self._make_request("query", params)

            result_type = data.get("resultType")
            result = data.get("result", [])

            if result_type == "vector":
                return [
                    MetricResult(
                        metric=item.get("metric", {}),
                        value=float(item["value"][1]) if item.get("value") else 0.0,
                        timestamp=float(item["value"][0]) if item.get("value") else None
                    )
                    for item in result
                ]
            elif result_type == "scalar":
                return [
                    MetricResult(
                        metric={},
                        value=float(result[1]) if len(result) > 1 else 0.0,
                        timestamp=float(result[0]) if len(result) > 0 else None
                    )
                ]
            else:
                self.logger.warning(f"Unsupported result type: {result_type}")
                return []

        except PrometheusClientError:
            raise
        except Exception as e:
            raise PrometheusClientError(f"Error parsing Prometheus response: {str(e)}")

    async def query_range(self,
                         query: str,
                         start: datetime,
                         end: datetime,
                         step: str = "30s") -> List[MetricResult]:
        """
        Execute range query against Prometheus

        Args:
            query: PromQL query string
            start: Start time
            end: End time
            step: Query resolution step

        Returns:
            List of metric results with time series data
        """
        params = {
            "query": query,
            "start": str(int(start.timestamp())),
            "end": str(int(end.timestamp())),
            "step": step
        }

        try:
            data = await self._make_request("query_range", params)

            result = data.get("result", [])

            return [
                MetricResult(
                    metric=item.get("metric", {}),
                    value=item.get("values", []),
                    timestamp=None  # Range queries have multiple timestamps in values
                )
                for item in result
            ]

        except PrometheusClientError:
            raise
        except Exception as e:
            raise PrometheusClientError(f"Error parsing Prometheus range response: {str(e)}")

    async def get_business_metrics(self, hotel_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Get business metrics for monitoring dashboard

        Args:
            hotel_id: Optional hotel ID filter

        Returns:
            Business metrics dictionary
        """
        metrics = {}

        try:
            # Call success rate
            query = self.business_queries["call_success_rate"].query
            if hotel_id:
                query = f'({query}) and on() group_left() voicehive_call_success_total{{hotel_id="{hotel_id}"}}'

            results = await self.query_instant(query)
            call_success_rate = results[0].value if results else 0.0

            metrics["call_success_rate"] = {
                "current": round(call_success_rate, 1),
                "target": 99.0,
                "status": "healthy" if call_success_rate >= 99.0 else ("degraded" if call_success_rate >= 95.0 else "unhealthy")
            }

            # Active calls
            query = self.business_queries["active_calls"].query
            if hotel_id:
                query = f'sum(voicehive_concurrent_calls{{hotel_id="{hotel_id}"}})'

            results = await self.query_instant(query)
            active_calls = int(results[0].value) if results else 0

            metrics["active_calls"] = {
                "current": active_calls,
                "peak_24h": await self._get_peak_value("voicehive_concurrent_calls", "24h", hotel_id),
                "status": "normal"
            }

            # PMS response time
            query = self.business_queries["pms_response_time_p95"].query
            if hotel_id:
                query = f'histogram_quantile(0.95, rate(voicehive_pms_response_seconds_bucket{{hotel_id="{hotel_id}"}}[5m]))'

            results = await self.query_instant(query)
            pms_p95_seconds = results[0].value if results else 0.0
            pms_p95_ms = int(pms_p95_seconds * 1000)

            metrics["pms_response_time"] = {
                "p95_ms": pms_p95_ms,
                "target_ms": 2000,
                "status": "healthy" if pms_p95_ms <= 2000 else "degraded"
            }

            # Guest satisfaction
            results = await self.query_instant(self.business_queries["guest_satisfaction"].query)
            guest_satisfaction = results[0].value if results else 4.0

            metrics["guest_satisfaction"] = {
                "average": round(guest_satisfaction, 1),
                "target": 4.0,
                "status": "excellent" if guest_satisfaction >= 4.0 else "good"
            }

        except PrometheusClientError as e:
            self.logger.error("Failed to fetch business metrics", error=str(e))
            # Return fallback values to prevent complete failure
            metrics = self._get_fallback_business_metrics()

        return metrics

    async def get_performance_metrics(self, time_range: str = "1h") -> Dict[str, Any]:
        """
        Get performance metrics summary

        Args:
            time_range: Time range for metrics (1h, 6h, 24h)

        Returns:
            Performance metrics dictionary
        """
        metrics = {}

        try:
            # Request rate
            results = await self.query_instant(self.performance_queries["request_rate"].query)
            current_rps = results[0].value if results else 0.0

            # Get peak and average for the time range
            peak_rps = await self._get_peak_value("voicehive_requests_total", time_range)
            avg_rps = await self._get_average_value("voicehive_requests_total", time_range)

            metrics["request_rate"] = {
                "current_rps": round(current_rps, 1),
                "peak_rps": round(peak_rps, 1),
                "average_rps": round(avg_rps, 1)
            }

            # Response times
            p50_results = await self.query_instant(self.performance_queries["response_time_p50"].query)
            p95_results = await self.query_instant(self.performance_queries["response_time_p95"].query)
            p99_results = await self.query_instant(self.performance_queries["response_time_p99"].query)

            p50_ms = int((p50_results[0].value if p50_results else 0.0) * 1000)
            p95_ms = int((p95_results[0].value if p95_results else 0.0) * 1000)
            p99_ms = int((p99_results[0].value if p99_results else 0.0) * 1000)

            metrics["response_times"] = {
                "p50_ms": p50_ms,
                "p95_ms": p95_ms,
                "p99_ms": p99_ms
            }

            # Error rates
            error_results = await self.query_instant(self.performance_queries["error_rate"].query)
            error_rate = error_results[0].value if error_results else 0.0

            # Calculate error percentage based on request rate
            error_percentage = (error_rate / max(current_rps, 1)) * 100 if current_rps > 0 else 0.0

            metrics["error_rates"] = {
                "total_errors": await self._get_total_errors(time_range),
                "error_rate_percent": round(error_percentage, 2),
                "critical_errors": await self._get_critical_errors(time_range)
            }

            # Resource usage
            cpu_results = await self.query_instant(self.performance_queries["cpu_usage"].query)
            memory_results = await self.query_instant(self.performance_queries["memory_usage"].query)
            connections_results = await self.query_instant(self.performance_queries["active_connections"].query)

            cpu_percent = cpu_results[0].value if cpu_results else 0.0
            memory_mb = int(memory_results[0].value) if memory_results else 0
            active_connections = int(connections_results[0].value) if connections_results else 0

            metrics["resource_usage"] = {
                "cpu_percent": round(cpu_percent, 1),
                "memory_mb": memory_mb,
                "active_connections": active_connections
            }

        except PrometheusClientError as e:
            self.logger.error("Failed to fetch performance metrics", error=str(e))
            # Return fallback values to prevent complete failure
            metrics = self._get_fallback_performance_metrics()

        return metrics

    async def get_circuit_breaker_stats(self) -> Dict[str, Any]:
        """
        Get circuit breaker statistics

        Returns:
            Circuit breaker statistics dictionary
        """
        stats = {}

        try:
            for service, query_config in self.circuit_breaker_queries.items():
                results = await self.query_instant(query_config.query)

                service_name = service.replace("_circuit_breaker_state", "")
                stats[service_name] = {}

                for result in results:
                    breaker_name = result.metric.get("breaker_name", "default")
                    state_value = int(result.value)

                    # Convert state value to human readable
                    state_map = {0: "closed", 1: "open", 2: "half_open"}
                    state = state_map.get(state_value, "unknown")

                    stats[service_name][breaker_name] = {
                        "state": state,
                        "numeric_state": state_value
                    }

        except PrometheusClientError as e:
            self.logger.error("Failed to fetch circuit breaker stats", error=str(e))
            stats = {}

        return stats

    async def health_check(self) -> Dict[str, Any]:
        """
        Check Prometheus server health

        Returns:
            Health status dictionary
        """
        try:
            # Simple query to test connectivity
            results = await self.query_instant("up")

            return {
                "status": "healthy",
                "prometheus_url": self.prometheus_url,
                "metrics_available": len(results),
                "timestamp": datetime.utcnow().isoformat()
            }
        except PrometheusClientError as e:
            return {
                "status": "unhealthy",
                "prometheus_url": self.prometheus_url,
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }

    async def get_endpoint_metrics(self, time_range: str = "1h") -> List[Dict[str, Any]]:
        """
        Get endpoint-specific performance metrics from Prometheus

        Args:
            time_range: Time range for metrics (1h, 6h, 24h)

        Returns:
            List of endpoint metrics with RPS and P95 response times
        """
        try:
            # Map of endpoints to track
            endpoints = [
                "/call/webhook",
                "/pms/booking",
                "/auth/validate",
                "/monitoring/health",
                "/auth/guest/login",
                "/tts/synthesize",
                "/asr/transcribe"
            ]

            endpoint_metrics = []

            for endpoint in endpoints:
                try:
                    # Query request rate (RPS) for this endpoint
                    rps_query = f'rate(voicehive_requests_total{{handler="{endpoint}"}}[{time_range}])'
                    rps_results = await self.query_instant(rps_query)
                    rps = round(sum(r.value for r in rps_results), 2) if rps_results else 0.0

                    # Query P95 response time for this endpoint
                    p95_query = f'histogram_quantile(0.95, rate(voicehive_request_duration_seconds_bucket{{handler="{endpoint}"}}[{time_range}]))'
                    p95_results = await self.query_instant(p95_query)
                    p95_seconds = sum(r.value for r in p95_results) if p95_results else 0.0
                    p95_ms = round(p95_seconds * 1000)  # Convert to milliseconds

                    # Query error rate for this endpoint
                    error_query = f'rate(voicehive_errors_total{{handler="{endpoint}"}}[{time_range}])'
                    error_results = await self.query_instant(error_query)
                    error_rate = sum(r.value for r in error_results) if error_results else 0.0

                    endpoint_metrics.append({
                        "endpoint": endpoint,
                        "rps": rps,
                        "p95_ms": p95_ms,
                        "error_rate": round(error_rate, 4),
                        "status": "healthy" if error_rate < 0.01 else "degraded" if error_rate < 0.05 else "unhealthy"
                    })

                except Exception as e:
                    self.logger.warning(f"Failed to get metrics for endpoint {endpoint}", error=str(e))
                    endpoint_metrics.append({
                        "endpoint": endpoint,
                        "rps": 0.0,
                        "p95_ms": 0,
                        "error_rate": 0.0,
                        "status": "unknown"
                    })

            # Sort by RPS (most active first)
            endpoint_metrics.sort(key=lambda x: x["rps"], reverse=True)

            return endpoint_metrics

        except Exception as e:
            self.logger.error("Failed to get endpoint metrics", error=str(e))
            # Return fallback data
            return [
                {"endpoint": "/call/webhook", "rps": 0.0, "p95_ms": 0, "error_rate": 0.0, "status": "unknown"},
                {"endpoint": "/pms/booking", "rps": 0.0, "p95_ms": 0, "error_rate": 0.0, "status": "unknown"},
                {"endpoint": "/auth/validate", "rps": 0.0, "p95_ms": 0, "error_rate": 0.0, "status": "unknown"}
            ]

    async def _get_peak_value(self, metric_name: str, time_range: str, hotel_id: Optional[str] = None) -> float:
        """Get peak value for a metric over time range"""
        try:
            # Convert time range to hours for calculation
            hours_map = {"1h": 1, "6h": 6, "24h": 24, "7d": 168}
            hours = hours_map.get(time_range, 1)

            start_time = datetime.utcnow() - timedelta(hours=hours)
            end_time = datetime.utcnow()

            query = f"max_over_time(sum(rate({metric_name}[5m]))[{time_range}:])"
            if hotel_id:
                query = f"max_over_time(sum(rate({metric_name}{{hotel_id=\"{hotel_id}\"}}[5m]))[{time_range}:])"

            results = await self.query_instant(query)
            return results[0].value if results else 0.0
        except:
            return 0.0

    async def _get_average_value(self, metric_name: str, time_range: str) -> float:
        """Get average value for a metric over time range"""
        try:
            query = f"avg_over_time(sum(rate({metric_name}[5m]))[{time_range}:])"
            results = await self.query_instant(query)
            return results[0].value if results else 0.0
        except:
            return 0.0

    async def _get_total_errors(self, time_range: str) -> int:
        """Get total error count for time range"""
        try:
            query = f"increase(voicehive_errors_total[{time_range}])"
            results = await self.query_instant(query)
            return int(sum(r.value for r in results)) if results else 0
        except:
            return 0

    async def _get_critical_errors(self, time_range: str) -> int:
        """Get critical error count for time range"""
        try:
            query = f'increase(voicehive_errors_total{{severity="critical"}}[{time_range}])'
            results = await self.query_instant(query)
            return int(sum(r.value for r in results)) if results else 0
        except:
            return 0

    def _get_fallback_business_metrics(self) -> Dict[str, Any]:
        """Fallback business metrics when Prometheus is unavailable"""
        return {
            "call_success_rate": {
                "current": 0.0,
                "target": 99.0,
                "status": "unknown"
            },
            "active_calls": {
                "current": 0,
                "peak_24h": 0,
                "status": "unknown"
            },
            "pms_response_time": {
                "p95_ms": 0,
                "target_ms": 2000,
                "status": "unknown"
            },
            "guest_satisfaction": {
                "average": 0.0,
                "target": 4.0,
                "status": "unknown"
            }
        }

    def _get_fallback_performance_metrics(self) -> Dict[str, Any]:
        """Fallback performance metrics when Prometheus is unavailable"""
        return {
            "request_rate": {
                "current_rps": 0.0,
                "peak_rps": 0.0,
                "average_rps": 0.0
            },
            "response_times": {
                "p50_ms": 0,
                "p95_ms": 0,
                "p99_ms": 0
            },
            "error_rates": {
                "total_errors": 0,
                "error_rate_percent": 0.0,
                "critical_errors": 0
            },
            "resource_usage": {
                "cpu_percent": 0.0,
                "memory_mb": 0,
                "active_connections": 0
            }
        }


# Global instance for reuse
prometheus_client = PrometheusClient()