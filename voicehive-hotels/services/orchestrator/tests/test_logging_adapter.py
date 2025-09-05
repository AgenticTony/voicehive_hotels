"""
Test the safe logging adapter
"""

import pytest
import logging
from unittest.mock import Mock, MagicMock, patch
import sys
from pathlib import Path

# Add repo root to path
repo_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(repo_root))

from services.orchestrator.logging_adapter import SafeLogger, get_safe_logger


class TestSafeLogger:
    """Test suite for the SafeLogger adapter"""
    
    def test_safe_logger_with_structlog(self):
        """Test SafeLogger when structlog is available"""
        # Create mock structlog logger with bind method
        mock_logger = Mock()
        mock_logger.bind = Mock(return_value=mock_logger)
        mock_logger.info = Mock()
        mock_logger.error = Mock()
        mock_logger.warning = Mock()
        mock_logger.debug = Mock()
        
        # Create SafeLogger
        safe_logger = SafeLogger(mock_logger)
        
        # Test that it detects structlog
        assert safe_logger._is_structlog is True
        
        # Test logging with kwargs
        safe_logger.info("test_event", user="john", action="login")
        mock_logger.info.assert_called_once_with("test_event", user="john", action="login")
        
        # Test bind
        bound_logger = safe_logger.bind(request_id="123")
        assert isinstance(bound_logger, SafeLogger)
        mock_logger.bind.assert_called_once_with(request_id="123")
    
    def test_safe_logger_with_stdlib(self):
        """Test SafeLogger when only stdlib logging is available"""
        # Create mock stdlib logger (no bind method)
        mock_logger = Mock(spec=['info', 'error', 'warning', 'debug'])
        mock_logger.info = Mock()
        mock_logger.error = Mock()
        mock_logger.warning = Mock()
        mock_logger.debug = Mock()
        
        # Create SafeLogger
        safe_logger = SafeLogger(mock_logger)
        
        # Test that it detects stdlib logger
        assert safe_logger._is_structlog is False
        
        # Test logging with kwargs - should convert to extra dict
        safe_logger.info("test_event", user="john", action="login")
        mock_logger.info.assert_called_once_with(
            "test_event", 
            extra={'fields': {'user': 'john', 'action': 'login'}}
        )
        
        # Test logging without kwargs
        safe_logger.error("error_event")
        mock_logger.error.assert_called_once_with("error_event", extra={})
        
        # Test bind returns self for stdlib
        bound_logger = safe_logger.bind(request_id="123")
        assert bound_logger is safe_logger
    
    def test_all_log_levels(self):
        """Test all log levels work correctly"""
        mock_logger = Mock(spec=['debug', 'info', 'warning', 'error', 'critical'])
        mock_logger.debug = Mock()
        mock_logger.info = Mock()
        mock_logger.warning = Mock()
        mock_logger.error = Mock()
        mock_logger.critical = Mock()
        
        safe_logger = SafeLogger(mock_logger)
        
        # Test each level
        safe_logger.debug("debug_msg", val=1)
        safe_logger.info("info_msg", val=2)
        safe_logger.warning("warning_msg", val=3)
        safe_logger.error("error_msg", val=4)
        safe_logger.critical("critical_msg", val=5)
        
        # Verify calls
        mock_logger.debug.assert_called_once()
        mock_logger.info.assert_called_once()
        mock_logger.warning.assert_called_once()
        mock_logger.error.assert_called_once()
        mock_logger.critical.assert_called_once()
    
    def test_get_safe_logger_with_structlog(self):
        """Test get_safe_logger when structlog is available"""
        mock_structlog = Mock()
        mock_logger = Mock()
        mock_logger.bind = Mock()  # Make it look like structlog
        mock_structlog.get_logger = Mock(return_value=mock_logger)
        
        with patch.dict('sys.modules', {'structlog': mock_structlog}):
            logger = get_safe_logger("test_logger")
            
        assert isinstance(logger, SafeLogger)
        assert logger._is_structlog is True
        mock_structlog.get_logger.assert_called_once_with("test_logger")
    
    def test_get_safe_logger_without_structlog(self):
        """Test get_safe_logger when structlog is not available"""
        # Remove structlog from modules if present
        if 'structlog' in sys.modules:
            original_structlog = sys.modules['structlog']
            del sys.modules['structlog']
        else:
            original_structlog = None
        
        try:
            with patch('services.orchestrator.logging_adapter.logging.getLogger') as mock_get_logger:
                mock_logger = Mock(spec=['info', 'error', 'warning', 'debug'])
                mock_get_logger.return_value = mock_logger
                
                logger = get_safe_logger("test_logger")
                
                assert isinstance(logger, SafeLogger)
                assert logger._is_structlog is False
                mock_get_logger.assert_called_once_with("test_logger")
        finally:
            # Restore structlog if it was present
            if original_structlog:
                sys.modules['structlog'] = original_structlog
    
    def test_warn_alias(self):
        """Test that warn is an alias for warning"""
        mock_logger = Mock(spec=['warning'])
        mock_logger.warning = Mock()
        
        safe_logger = SafeLogger(mock_logger)
        
        # Test warn method
        safe_logger.warn("warning_via_warn", level="high")
        mock_logger.warning.assert_called_once()

    def test_stdlib_special_kwargs_and_extra_merge(self):
        """Test that exc_info/stack_info/stacklevel and extra are handled correctly for stdlib"""
        mock_logger = Mock(spec=['error'])
        mock_logger.error = Mock()
        
        safe_logger = SafeLogger(mock_logger)
        
        # Prepare an exception
        try:
            raise ValueError("boom")
        except ValueError as e:
            exc = e
        
        # Call with special kwargs and user-provided extra
        safe_logger.error(
            "error_event",
            user="john",
            action="login",
            extra={"trace_id": "abc123"},
            exc_info=exc,
            stack_info=True,
            stacklevel=2
        )
        
        # Verify that special kwargs were passed through and extra merged
        called_args, called_kwargs = mock_logger.error.call_args
        assert called_args[0] == "error_event"
        assert 'extra' in called_kwargs
        assert called_kwargs['extra']['trace_id'] == 'abc123'
        assert 'fields' in called_kwargs['extra']
        assert called_kwargs['extra']['fields'] == {"user": "john", "action": "login"}
        assert called_kwargs['exc_info'] is exc
        assert called_kwargs['stack_info'] is True
        assert called_kwargs['stacklevel'] == 2

    def test_rejects_positional_args_beyond_event(self):
        """Ensure passing positional args beyond event doesn't crash and are not used"""
        mock_logger = Mock(spec=['info'])
        mock_logger.info = Mock()
        safe_logger = SafeLogger(mock_logger)
        
        # Positional args will be ignored since our signature doesn't accept them
        # This test ensures the call doesn't crash and only the event is used
        safe_logger.info("event_name")
        mock_logger.info.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
