"""
Unit tests for PrometheusClient
Tests real metrics querying functionality
"""

import pytest
import asyncio
import aiohttp
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from monitoring.prometheus_client import (
    PrometheusClient,
    PrometheusClientError,
    PrometheusQuery,
    MetricResult
)


class TestPrometheusClient:
    """Test cases for PrometheusClient"""

    @pytest.fixture
    def client(self):
        """Create test PrometheusClient instance"""
        return PrometheusClient(
            prometheus_url="http://test-prometheus:9090",
            timeout=5.0,
            max_retries=2
        )

    @pytest.fixture
    def mock_response_data(self):
        """Mock Prometheus API response data"""
        return {
            "status": "success",
            "data": {
                "resultType": "vector",
                "result": [
                    {
                        "metric": {"__name__": "voicehive_call_success_total", "job": "orchestrator"},
                        "value": [1635724800, "99.5"]
                    },
                    {
                        "metric": {"__name__": "voicehive_call_failures_total", "job": "orchestrator"},
                        "value": [1635724800, "0.5"]
                    }
                ]
            }
        }

    @pytest.mark.asyncio
    async def test_init(self, client):
        """Test PrometheusClient initialization"""
        assert client.prometheus_url == "http://test-prometheus:9090"
        assert client.timeout == 5.0
        assert client.max_retries == 2

        # Test URL normalization
        client_with_slash = PrometheusClient(prometheus_url="http://test:9090/")
        assert client_with_slash.prometheus_url == "http://test:9090"

    @pytest.mark.asyncio
    async def test_make_request_success(self, client, mock_response_data):
        """Test successful HTTP request to Prometheus API"""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value=mock_response_data)

        mock_session = AsyncMock()
        mock_session.get = AsyncMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_response)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with patch('aiohttp.ClientSession') as mock_client_session:
            mock_client_session.return_value = mock_session

            result = await client._make_request("query", {"query": "up"})

            assert result == mock_response_data["data"]
            mock_client_session.assert_called_once()
            mock_session.get.assert_called_once()

    @pytest.mark.asyncio
    async def test_make_request_prometheus_error(self, client):
        """Test Prometheus API error response"""
        error_response = {
            "status": "error",
            "error": "Invalid query"
        }

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value=error_response)

        mock_session = AsyncMock()
        mock_session.get = AsyncMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_response)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with patch('aiohttp.ClientSession') as mock_client_session:
            mock_client_session.return_value = mock_session

            with pytest.raises(PrometheusClientError) as exc_info:
                await client._make_request("query", {"query": "invalid"})

            assert "Invalid query" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_make_request_http_error(self, client):
        """Test HTTP error response"""
        mock_response = AsyncMock()
        mock_response.status = 500
        mock_response.text = AsyncMock(return_value="Internal Server Error")

        mock_session = AsyncMock()
        mock_session.get = AsyncMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_response)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with patch('aiohttp.ClientSession') as mock_client_session:
            mock_client_session.return_value = mock_session

            with pytest.raises(PrometheusClientError) as exc_info:
                await client._make_request("query", {"query": "up"})

            assert "HTTP 500" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_make_request_timeout_retry(self, client):
        """Test timeout with retry logic"""
        mock_session = AsyncMock()
        mock_session.get = AsyncMock(side_effect=asyncio.TimeoutError())
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with patch('aiohttp.ClientSession') as mock_client_session:
            mock_client_session.return_value = mock_session

            with patch('asyncio.sleep') as mock_sleep:
                with pytest.raises(PrometheusClientError) as exc_info:
                    await client._make_request("query", {"query": "up"})

                assert "timed out after" in str(exc_info.value)
                # Should retry max_retries times
                assert mock_session.get.call_count == client.max_retries + 1
                # Should sleep with exponential backoff
                assert mock_sleep.call_count == client.max_retries

    @pytest.mark.asyncio
    async def test_query_instant_vector(self, client):
        """Test instant query with vector result"""
        mock_data = {
            "resultType": "vector",
            "result": [
                {
                    "metric": {"job": "orchestrator", "instance": "app1"},
                    "value": [1635724800, "99.5"]
                },
                {
                    "metric": {"job": "orchestrator", "instance": "app2"},
                    "value": [1635724800, "98.2"]
                }
            ]
        }

        with patch.object(client, '_make_request', return_value=mock_data):
            results = await client.query_instant("voicehive_success_rate")

            assert len(results) == 2
            assert isinstance(results[0], MetricResult)
            assert results[0].metric["job"] == "orchestrator"
            assert results[0].value == 99.5
            assert results[0].timestamp == 1635724800
            assert results[1].value == 98.2

    @pytest.mark.asyncio
    async def test_query_instant_scalar(self, client):
        """Test instant query with scalar result"""
        mock_data = {
            "resultType": "scalar",
            "result": [1635724800, "42.0"]
        }

        with patch.object(client, '_make_request', return_value=mock_data):
            results = await client.query_instant("count(up)")

            assert len(results) == 1
            assert results[0].value == 42.0
            assert results[0].timestamp == 1635724800
            assert results[0].metric == {}

    @pytest.mark.asyncio
    async def test_query_instant_with_time(self, client):
        """Test instant query with specific time"""
        query_time = datetime(2021, 11, 1, 12, 0, 0)

        with patch.object(client, '_make_request', return_value={"resultType": "vector", "result": []}):
            await client.query_instant("up", time=query_time)

            # Verify timestamp was passed correctly
            expected_timestamp = str(int(query_time.timestamp()))
            client._make_request.assert_called_once_with(
                "query",
                {"query": "up", "time": expected_timestamp}
            )

    @pytest.mark.asyncio
    async def test_query_range(self, client):
        """Test range query"""
        mock_data = {
            "resultType": "matrix",
            "result": [
                {
                    "metric": {"job": "orchestrator"},
                    "values": [
                        [1635724800, "99.5"],
                        [1635724830, "99.2"],
                        [1635724860, "99.8"]
                    ]
                }
            ]
        }

        start_time = datetime(2021, 11, 1, 12, 0, 0)
        end_time = datetime(2021, 11, 1, 13, 0, 0)

        with patch.object(client, '_make_request', return_value=mock_data):
            results = await client.query_range("voicehive_success_rate", start_time, end_time, "30s")

            assert len(results) == 1
            assert results[0].metric["job"] == "orchestrator"
            assert len(results[0].value) == 3
            assert results[0].value[0] == [1635724800, "99.5"]

    @pytest.mark.asyncio
    async def test_get_business_metrics_success(self, client):
        """Test successful business metrics retrieval"""
        # Mock multiple queries for business metrics
        query_responses = {
            # Call success rate
            "rate(voicehive_call_success_total[5m]) / (rate(voicehive_call_success_total[5m]) + rate(voicehive_call_failures_total[5m])) * 100": [
                MetricResult(metric={}, value=99.2, timestamp=1635724800)
            ],
            # Active calls
            "sum(voicehive_concurrent_calls)": [
                MetricResult(metric={}, value=15.0, timestamp=1635724800)
            ],
            # PMS response time
            "histogram_quantile(0.95, rate(voicehive_pms_response_seconds_bucket[5m]))": [
                MetricResult(metric={}, value=0.85, timestamp=1635724800)
            ],
            # Guest satisfaction
            "histogram_quantile(0.5, rate(voicehive_guest_satisfaction_bucket[1h]))": [
                MetricResult(metric={}, value=4.3, timestamp=1635724800)
            ]
        }

        async def mock_query_instant(query):
            return query_responses.get(query, [])

        # Mock the _get_peak_value method
        async def mock_get_peak_value(metric_name, time_range, hotel_id=None):
            return 45.0

        with patch.object(client, 'query_instant', side_effect=mock_query_instant):
            with patch.object(client, '_get_peak_value', side_effect=mock_get_peak_value):
                metrics = await client.get_business_metrics()

                assert metrics["call_success_rate"]["current"] == 99.2
                assert metrics["call_success_rate"]["status"] == "healthy"
                assert metrics["active_calls"]["current"] == 15
                assert metrics["active_calls"]["peak_24h"] == 45.0
                assert metrics["pms_response_time"]["p95_ms"] == 850  # 0.85 seconds = 850ms
                assert metrics["pms_response_time"]["status"] == "healthy"
                assert metrics["guest_satisfaction"]["average"] == 4.3

    @pytest.mark.asyncio
    async def test_get_business_metrics_with_hotel_filter(self, client):
        """Test business metrics with hotel ID filter"""
        with patch.object(client, 'query_instant', return_value=[MetricResult(metric={}, value=98.5)]):
            with patch.object(client, '_get_peak_value', return_value=30.0):
                metrics = await client.get_business_metrics(hotel_id="hotel123")

                assert metrics["call_success_rate"]["current"] == 98.5

    @pytest.mark.asyncio
    async def test_get_business_metrics_error(self, client):
        """Test business metrics error handling"""
        with patch.object(client, 'query_instant', side_effect=PrometheusClientError("Connection failed")):
            metrics = await client.get_business_metrics()

            # Should return fallback metrics
            assert metrics["call_success_rate"]["current"] == 0.0
            assert metrics["call_success_rate"]["status"] == "unknown"

    @pytest.mark.asyncio
    async def test_get_performance_metrics_success(self, client):
        """Test successful performance metrics retrieval"""
        query_responses = {
            "sum(rate(voicehive_requests_total[5m]))": [MetricResult(metric={}, value=12.5)],
            "histogram_quantile(0.50, rate(voicehive_request_duration_seconds_bucket[5m]))": [MetricResult(metric={}, value=0.125)],
            "histogram_quantile(0.95, rate(voicehive_request_duration_seconds_bucket[5m]))": [MetricResult(metric={}, value=0.45)],
            "histogram_quantile(0.99, rate(voicehive_request_duration_seconds_bucket[5m]))": [MetricResult(metric={}, value=0.85)],
            "sum(rate(voicehive_errors_total[5m]))": [MetricResult(metric={}, value=0.02)],
            "voicehive_cpu_usage_percent": [MetricResult(metric={}, value=15.2)],
            "voicehive_memory_usage_bytes / 1024 / 1024": [MetricResult(metric={}, value=256.0)],
            "voicehive_active_connections": [MetricResult(metric={}, value=45.0)]
        }

        async def mock_query_instant(query):
            return query_responses.get(query, [])

        # Mock helper methods
        async def mock_get_peak_value(metric_name, time_range):
            return 45.2

        async def mock_get_average_value(metric_name, time_range):
            return 18.7

        async def mock_get_total_errors(time_range):
            return 23

        async def mock_get_critical_errors(time_range):
            return 2

        with patch.object(client, 'query_instant', side_effect=mock_query_instant):
            with patch.object(client, '_get_peak_value', side_effect=mock_get_peak_value):
                with patch.object(client, '_get_average_value', side_effect=mock_get_average_value):
                    with patch.object(client, '_get_total_errors', side_effect=mock_get_total_errors):
                        with patch.object(client, '_get_critical_errors', side_effect=mock_get_critical_errors):
                            metrics = await client.get_performance_metrics("1h")

                            assert metrics["request_rate"]["current_rps"] == 12.5
                            assert metrics["request_rate"]["peak_rps"] == 45.2
                            assert metrics["request_rate"]["average_rps"] == 18.7
                            assert metrics["response_times"]["p50_ms"] == 125
                            assert metrics["response_times"]["p95_ms"] == 450
                            assert metrics["response_times"]["p99_ms"] == 850
                            assert metrics["error_rates"]["total_errors"] == 23
                            assert metrics["error_rates"]["critical_errors"] == 2
                            assert metrics["resource_usage"]["cpu_percent"] == 15.2
                            assert metrics["resource_usage"]["memory_mb"] == 256

    @pytest.mark.asyncio
    async def test_get_circuit_breaker_stats(self, client):
        """Test circuit breaker statistics retrieval"""
        query_responses = {
            "voicehive_database_circuit_breaker_state": [
                MetricResult(metric={"breaker_name": "db_read"}, value=0),
                MetricResult(metric={"breaker_name": "db_write"}, value=1)
            ],
            "voicehive_tts_synthesis_circuit_breaker_state": [
                MetricResult(metric={"breaker_name": "synthesis"}, value=0)
            ],
            "voicehive_asr_circuit_breaker_state": [
                MetricResult(metric={"breaker_name": "recognition"}, value=2)
            ],
            "voicehive_apaleo_circuit_breaker_state": [
                MetricResult(metric={"breaker_name": "api"}, value=0)
            ]
        }

        async def mock_query_instant(query):
            return query_responses.get(query, [])

        with patch.object(client, 'query_instant', side_effect=mock_query_instant):
            stats = await client.get_circuit_breaker_stats()

            assert "database" in stats
            assert stats["database"]["db_read"]["state"] == "closed"
            assert stats["database"]["db_write"]["state"] == "open"
            assert "tts" in stats
            assert stats["tts"]["synthesis"]["state"] == "closed"
            assert "asr" in stats
            assert stats["asr"]["recognition"]["state"] == "half_open"
            assert "apaleo" in stats
            assert stats["apaleo"]["api"]["state"] == "closed"

    @pytest.mark.asyncio
    async def test_health_check_success(self, client):
        """Test successful health check"""
        with patch.object(client, 'query_instant', return_value=[MetricResult(metric={}, value=1)]):
            health = await client.health_check()

            assert health["status"] == "healthy"
            assert health["prometheus_url"] == "http://test-prometheus:9090"
            assert health["metrics_available"] == 1

    @pytest.mark.asyncio
    async def test_health_check_failure(self, client):
        """Test failed health check"""
        with patch.object(client, 'query_instant', side_effect=PrometheusClientError("Connection failed")):
            health = await client.health_check()

            assert health["status"] == "unhealthy"
            assert "Connection failed" in health["error"]

    @pytest.mark.asyncio
    async def test_fallback_methods(self, client):
        """Test fallback methods return sensible defaults"""
        fallback_business = client._get_fallback_business_metrics()
        fallback_performance = client._get_fallback_performance_metrics()

        assert fallback_business["call_success_rate"]["current"] == 0.0
        assert fallback_business["call_success_rate"]["status"] == "unknown"
        assert fallback_performance["request_rate"]["current_rps"] == 0.0
        assert fallback_performance["response_times"]["p50_ms"] == 0

    def test_prometheus_query_dataclass(self):
        """Test PrometheusQuery dataclass"""
        query = PrometheusQuery(
            query="up",
            description="Test query",
            expected_type="vector"
        )

        assert query.query == "up"
        assert query.description == "Test query"
        assert query.expected_type == "vector"

    def test_metric_result_dataclass(self):
        """Test MetricResult dataclass"""
        result = MetricResult(
            metric={"job": "test"},
            value=42.0,
            timestamp=1635724800
        )

        assert result.metric["job"] == "test"
        assert result.value == 42.0
        assert result.timestamp == 1635724800

        # Test with default timestamp
        result_no_timestamp = MetricResult(
            metric={},
            value=10.0
        )
        assert result_no_timestamp.timestamp is None

    @pytest.mark.asyncio
    async def test_environment_variable_configuration(self):
        """Test configuration from environment variables"""
        with patch.dict(os.environ, {'PROMETHEUS_URL': 'http://env-prometheus:9090'}):
            client = PrometheusClient()
            assert client.prometheus_url == "http://env-prometheus:9090"

        # Test default when no env var
        with patch.dict(os.environ, {}, clear=True):
            client = PrometheusClient()
            assert client.prometheus_url == "http://prometheus:9090"

    @pytest.mark.asyncio
    async def test_query_parameter_encoding(self, client):
        """Test proper URL encoding of query parameters"""
        complex_query = "rate(voicehive_requests_total{job=\"app\"}[5m])"

        with patch.object(client, '_make_request', return_value={"resultType": "vector", "result": []}):
            await client.query_instant(complex_query)

            # Verify the query was passed correctly
            client._make_request.assert_called_once_with("query", {"query": complex_query})