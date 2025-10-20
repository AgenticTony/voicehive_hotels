"""
Unit tests for Auth Router MFA endpoints
Tests MFA enrollment, verification, and management endpoints
"""

import pytest
import json
import base64
from datetime import datetime, timezone
from unittest.mock import Mock, patch, AsyncMock
from uuid import uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient

from services.orchestrator.routers.auth import router
from services.orchestrator.auth.mfa_models import (
    MFAEnrollmentRequest, MFAEnrollmentResponse, MFAEnrollmentVerificationRequest,
    MFAVerificationRequest, MFAStatusResponse, MFADisableRequest
)
from services.orchestrator.auth.mfa_service import MFAService, MFAEnrollmentError, MFAVerificationError
from auth_models import UserContext


class TestAuthRouterMFA:
    """Test suite for Auth Router MFA endpoints"""

    def setup_method(self):
        """Set up test fixtures"""
        self.user_id = str(uuid4())
        self.user_email = "test@example.com"
        self.current_user = UserContext(
            user_id=self.user_id,
            email=self.user_email,
            roles=[],
            session_id="test-session"
        )

    @pytest.mark.asyncio
    async def test_start_mfa_enrollment_success(self):
        """Test successful MFA enrollment start"""
        # Mock MFA service
        mock_mfa_service = Mock(spec=MFAService)
        mock_mfa_service.start_enrollment.return_value = {
            "provisioning_uri": "otpauth://totp/test",
            "qr_code": base64.b64encode(b"qr_data").decode('utf-8')
        }

        with patch('services.orchestrator.routers.auth.get_current_user', return_value=self.current_user):
            with patch('services.orchestrator.routers.auth.get_mfa_service', return_value=mock_mfa_service):
                from services.orchestrator.routers.auth import start_mfa_enrollment

                result = await start_mfa_enrollment(
                    MFAEnrollmentRequest(),
                    self.current_user,
                    mock_mfa_service
                )

                assert isinstance(result, MFAEnrollmentResponse)
                assert result.provisioning_uri == "otpauth://totp/test"
                assert result.qr_code == base64.b64encode(b"qr_data").decode('utf-8')

                # Should call MFA service with correct parameters
                mock_mfa_service.start_enrollment.assert_called_once_with(
                    user_id=self.user_id,
                    enrolled_by=self.user_id
                )

    @pytest.mark.asyncio
    async def test_start_mfa_enrollment_already_enabled(self):
        """Test MFA enrollment start when already enabled"""
        mock_mfa_service = Mock(spec=MFAService)
        mock_mfa_service.start_enrollment.side_effect = MFAEnrollmentError("MFA is already enabled")

        with patch('services.orchestrator.routers.auth.get_current_user', return_value=self.current_user):
            with patch('services.orchestrator.routers.auth.get_mfa_service', return_value=mock_mfa_service):
                from services.orchestrator.routers.auth import start_mfa_enrollment

                with pytest.raises(HTTPException) as exc_info:
                    await start_mfa_enrollment(
                        MFAEnrollmentRequest(),
                        self.current_user,
                        mock_mfa_service
                    )

                assert exc_info.value.status_code == 400
                assert "MFA is already enabled" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_complete_mfa_enrollment_success(self):
        """Test successful MFA enrollment completion"""
        mock_request = Mock()
        mock_request.client.host = "192.168.1.1"
        mock_request.headers.get.return_value = "test-agent"

        mock_mfa_service = Mock(spec=MFAService)
        mock_mfa_service.complete_enrollment.return_value = {
            "recovery_codes": ["CODE1", "CODE2", "CODE3"]
        }

        with patch('services.orchestrator.routers.auth.get_current_user', return_value=self.current_user):
            with patch('services.orchestrator.routers.auth.get_mfa_service', return_value=mock_mfa_service):
                from services.orchestrator.routers.auth import complete_mfa_enrollment

                result = await complete_mfa_enrollment(
                    MFAEnrollmentVerificationRequest(verification_code="123456"),
                    self.current_user,
                    mock_mfa_service,
                    mock_request
                )

                assert result.success is True
                assert result.recovery_codes == ["CODE1", "CODE2", "CODE3"]

                # Should call MFA service with correct parameters
                mock_mfa_service.complete_enrollment.assert_called_once_with(
                    user_id=self.user_id,
                    verification_code="123456",
                    ip_address="192.168.1.1",
                    user_agent="test-agent"
                )

    @pytest.mark.asyncio
    async def test_complete_mfa_enrollment_invalid_code(self):
        """Test MFA enrollment completion with invalid code"""
        mock_request = Mock()
        mock_request.client.host = "192.168.1.1"
        mock_request.headers.get.return_value = "test-agent"

        mock_mfa_service = Mock(spec=MFAService)
        mock_mfa_service.complete_enrollment.side_effect = MFAVerificationError("Invalid verification code")

        with patch('services.orchestrator.routers.auth.get_current_user', return_value=self.current_user):
            with patch('services.orchestrator.routers.auth.get_mfa_service', return_value=mock_mfa_service):
                from services.orchestrator.routers.auth import complete_mfa_enrollment

                with pytest.raises(HTTPException) as exc_info:
                    await complete_mfa_enrollment(
                        MFAEnrollmentVerificationRequest(verification_code="000000"),
                        self.current_user,
                        mock_mfa_service,
                        mock_request
                    )

                assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_verify_mfa_code_totp_success(self):
        """Test successful TOTP code verification"""
        mock_request = Mock()
        mock_request.client.host = "192.168.1.1"
        mock_request.headers.get.return_value = "test-agent"

        mock_mfa_service = Mock(spec=MFAService)
        mock_mfa_service.verify_code.return_value = True
        mock_mfa_service.get_mfa_status.return_value = {"recovery_codes_available": 8}

        with patch('services.orchestrator.routers.auth.get_current_user', return_value=self.current_user):
            with patch('services.orchestrator.routers.auth.get_mfa_service', return_value=mock_mfa_service):
                with patch('services.orchestrator.routers.auth.mfa_verification_tracker') as mock_tracker:
                    from services.orchestrator.routers.auth import verify_mfa_code

                    result = await verify_mfa_code(
                        MFAVerificationRequest(code="123456"),
                        self.current_user,
                        mock_mfa_service,
                        mock_request
                    )

                    assert result.success is True
                    assert result.verification_method == "totp"
                    assert result.message == "MFA verification successful"
                    assert result.remaining_recovery_codes is None

                    # Should mark session as MFA verified
                    mock_tracker.mark_mfa_verified.assert_called_once_with("test-session", self.user_id)

    @pytest.mark.asyncio
    async def test_verify_mfa_code_recovery_success(self):
        """Test successful recovery code verification"""
        mock_request = Mock()
        mock_request.client.host = "192.168.1.1"
        mock_request.headers.get.return_value = "test-agent"

        mock_mfa_service = Mock(spec=MFAService)
        mock_mfa_service.verify_code.return_value = True
        mock_mfa_service.get_mfa_status.return_value = {"recovery_codes_available": 7}

        with patch('services.orchestrator.routers.auth.get_current_user', return_value=self.current_user):
            with patch('services.orchestrator.routers.auth.get_mfa_service', return_value=mock_mfa_service):
                with patch('services.orchestrator.routers.auth.mfa_verification_tracker') as mock_tracker:
                    from services.orchestrator.routers.auth import verify_mfa_code

                    result = await verify_mfa_code(
                        MFAVerificationRequest(code="ABCD1234"),  # 8-char recovery code
                        self.current_user,
                        mock_mfa_service,
                        mock_request
                    )

                    assert result.success is True
                    assert result.verification_method == "recovery_code"
                    assert result.remaining_recovery_codes == 7

    @pytest.mark.asyncio
    async def test_verify_mfa_code_failure(self):
        """Test MFA code verification failure"""
        mock_request = Mock()
        mock_request.client.host = "192.168.1.1"

        mock_mfa_service = Mock(spec=MFAService)
        mock_mfa_service.verify_code.return_value = False

        with patch('services.orchestrator.routers.auth.get_current_user', return_value=self.current_user):
            with patch('services.orchestrator.routers.auth.get_mfa_service', return_value=mock_mfa_service):
                from services.orchestrator.routers.auth import verify_mfa_code

                result = await verify_mfa_code(
                    MFAVerificationRequest(code="000000"),
                    self.current_user,
                    mock_mfa_service,
                    mock_request
                )

                assert result.success is False
                assert result.verification_method == "unknown"
                assert result.message == "Invalid MFA code"

    @pytest.mark.asyncio
    async def test_get_mfa_status(self):
        """Test getting MFA status"""
        mock_mfa_service = Mock(spec=MFAService)
        mock_mfa_service.get_mfa_status.return_value = {
            "enabled": True,
            "enrolled": True,
            "enrolled_at": "2023-01-01T00:00:00",
            "last_verified_at": "2023-01-01T12:00:00",
            "recovery_codes_available": 8,
            "recovery_codes_used": 2
        }

        with patch('services.orchestrator.routers.auth.get_current_user', return_value=self.current_user):
            with patch('services.orchestrator.routers.auth.get_mfa_service', return_value=mock_mfa_service):
                from services.orchestrator.routers.auth import get_mfa_status

                result = await get_mfa_status(self.current_user, mock_mfa_service)

                assert isinstance(result, MFAStatusResponse)
                assert result.enabled is True
                assert result.enrolled is True
                assert result.recovery_codes_available == 8
                assert result.recovery_codes_used == 2

    @pytest.mark.asyncio
    async def test_disable_mfa_success(self):
        """Test successful MFA disabling"""
        mock_auth_service = Mock()
        mock_auth_service.authenticate_user.return_value = self.current_user

        mock_mfa_service = Mock(spec=MFAService)
        mock_mfa_service.disable_mfa.return_value = None

        with patch('services.orchestrator.routers.auth.RequireMFAEnabled', return_value=self.current_user):
            with patch('services.orchestrator.routers.auth.get_mfa_service', return_value=mock_mfa_service):
                with patch('services.orchestrator.routers.auth.get_auth_service', return_value=mock_auth_service):
                    from services.orchestrator.routers.auth import disable_mfa

                    result = await disable_mfa(
                        MFADisableRequest(confirmation=True, current_password="password123"),
                        self.current_user,
                        mock_mfa_service,
                        mock_auth_service
                    )

                    assert result.success is True

                    # Should verify password and disable MFA
                    mock_auth_service.authenticate_user.assert_called_once_with(
                        self.user_email, "password123"
                    )
                    mock_mfa_service.disable_mfa.assert_called_once_with(
                        user_id=self.user_id,
                        disabled_by=self.user_id
                    )

    @pytest.mark.asyncio
    async def test_disable_mfa_wrong_password(self):
        """Test MFA disabling with wrong password"""
        from auth_models import AuthenticationError

        mock_auth_service = Mock()
        mock_auth_service.authenticate_user.side_effect = AuthenticationError("Invalid credentials")

        mock_mfa_service = Mock(spec=MFAService)

        with patch('services.orchestrator.routers.auth.RequireMFAEnabled', return_value=self.current_user):
            with patch('services.orchestrator.routers.auth.get_mfa_service', return_value=mock_mfa_service):
                with patch('services.orchestrator.routers.auth.get_auth_service', return_value=mock_auth_service):
                    from services.orchestrator.routers.auth import disable_mfa

                    with pytest.raises(HTTPException) as exc_info:
                        await disable_mfa(
                            MFADisableRequest(confirmation=True, current_password="wrong_password"),
                            self.current_user,
                            mock_mfa_service,
                            mock_auth_service
                        )

                    assert exc_info.value.status_code == 401
                    assert "Invalid current password" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_regenerate_recovery_codes_success(self):
        """Test successful recovery codes regeneration"""
        mock_auth_service = Mock()
        mock_auth_service.authenticate_user.return_value = self.current_user

        mock_mfa_service = Mock(spec=MFAService)
        mock_mfa_service.regenerate_recovery_codes.return_value = ["NEW1", "NEW2", "NEW3"]

        with patch('services.orchestrator.routers.auth.RequireRecentMFA', return_value=self.current_user):
            with patch('services.orchestrator.routers.auth.get_mfa_service', return_value=mock_mfa_service):
                with patch('services.orchestrator.routers.auth.get_auth_service', return_value=mock_auth_service):
                    from services.orchestrator.routers.auth import regenerate_recovery_codes
                    from services.orchestrator.auth.mfa_models import MFARecoveryCodesRegenerateRequest

                    result = await regenerate_recovery_codes(
                        MFARecoveryCodesRegenerateRequest(current_password="password123"),
                        self.current_user,
                        mock_mfa_service,
                        mock_auth_service
                    )

                    assert result.recovery_codes == ["NEW1", "NEW2", "NEW3"]

                    # Should verify password and regenerate codes
                    mock_auth_service.authenticate_user.assert_called_once_with(
                        self.user_email, "password123"
                    )
                    mock_mfa_service.regenerate_recovery_codes.assert_called_once_with(self.user_id)

    @pytest.mark.asyncio
    async def test_get_mfa_audit_log(self):
        """Test getting MFA audit log"""
        mock_mfa_service = Mock(spec=MFAService)

        with patch('services.orchestrator.routers.auth.RequireMFAEnabled', return_value=self.current_user):
            with patch('services.orchestrator.routers.auth.get_mfa_service', return_value=mock_mfa_service):
                from services.orchestrator.routers.auth import get_mfa_audit_log

                result = await get_mfa_audit_log(
                    page=1,
                    page_size=50,
                    current_user=self.current_user,
                    mfa_service=mock_mfa_service
                )

                # For now, returns empty response (implementation placeholder)
                assert result.events == []
                assert result.total_count == 0
                assert result.page == 1
                assert result.page_size == 50

    @pytest.mark.asyncio
    async def test_get_user_mfa_status_admin(self):
        """Test admin getting user MFA status"""
        target_user_id = str(uuid4())
        admin_user = UserContext(
            user_id=str(uuid4()),
            email="admin@example.com",
            roles=[],
            session_id="admin-session"
        )

        # Mock user lookup
        mock_user = Mock()
        mock_user.email = "target@example.com"
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_db_session = Mock()
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        mock_mfa_service = Mock(spec=MFAService)
        mock_mfa_service.get_mfa_status.return_value = {
            "enabled": True,
            "enrolled": True,
            "enrolled_at": "2023-01-01T00:00:00",
            "last_verified_at": "2023-01-01T12:00:00",
            "recovery_codes_available": 8
        }

        with patch('services.orchestrator.routers.auth.require_permissions'):
            with patch('services.orchestrator.routers.auth.get_mfa_service', return_value=mock_mfa_service):
                from services.orchestrator.routers.auth import get_user_mfa_status_admin

                result = await get_user_mfa_status_admin(
                    target_user_id,
                    admin_user,
                    mock_mfa_service,
                    mock_db_session
                )

                assert result.user_id == target_user_id
                assert result.email == "target@example.com"
                assert result.mfa_enabled is True

    @pytest.mark.asyncio
    async def test_get_user_mfa_status_admin_user_not_found(self):
        """Test admin getting MFA status for non-existent user"""
        target_user_id = str(uuid4())
        admin_user = UserContext(
            user_id=str(uuid4()),
            email="admin@example.com",
            roles=[],
            session_id="admin-session"
        )

        # Mock user lookup returning None
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db_session = Mock()
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        mock_mfa_service = Mock(spec=MFAService)

        with patch('services.orchestrator.routers.auth.require_permissions'):
            with patch('services.orchestrator.routers.auth.get_mfa_service', return_value=mock_mfa_service):
                from services.orchestrator.routers.auth import get_user_mfa_status_admin

                with pytest.raises(HTTPException) as exc_info:
                    await get_user_mfa_status_admin(
                        target_user_id,
                        admin_user,
                        mock_mfa_service,
                        mock_db_session
                    )

                assert exc_info.value.status_code == 404
                assert "User not found" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_disable_user_mfa_admin(self):
        """Test admin disabling user MFA"""
        target_user_id = str(uuid4())
        admin_user = UserContext(
            user_id=str(uuid4()),
            email="admin@example.com",
            roles=[],
            session_id="admin-session"
        )

        mock_mfa_service = Mock(spec=MFAService)
        mock_mfa_service.disable_mfa.return_value = None

        with patch('services.orchestrator.routers.auth.require_permissions'):
            with patch('services.orchestrator.routers.auth.get_mfa_service', return_value=mock_mfa_service):
                from services.orchestrator.routers.auth import disable_user_mfa_admin

                result = await disable_user_mfa_admin(
                    target_user_id,
                    admin_user,
                    mock_mfa_service
                )

                assert f"MFA disabled for user {target_user_id}" in result["message"]

                # Should disable MFA for target user
                mock_mfa_service.disable_mfa.assert_called_once_with(
                    user_id=target_user_id,
                    disabled_by=str(admin_user.user_id)
                )