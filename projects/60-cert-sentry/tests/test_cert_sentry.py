import datetime
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure the parent directory is in the path for standalone test execution
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cert_sentry import CertManager, Sentinel, TLSProbe

def test_cert_manager_ca_generation(tmp_path):
    manager = CertManager(output_dir=str(tmp_path))
    manager.generate_ca()

    assert (tmp_path / "ca.key").exists()
    assert (tmp_path / "ca.crt").exists()

def test_cert_manager_issue_cert(tmp_path):
    manager = CertManager(output_dir=str(tmp_path))
    manager.generate_ca()

    result = manager.issue_cert("test.home", days_valid=30)
    assert result is True

    assert (tmp_path / "test.home.key").exists()
    assert (tmp_path / "test.home.crt").exists()

def test_cert_manager_issue_cert_no_ca(tmp_path):
    manager = CertManager(output_dir=str(tmp_path))

    result = manager.issue_cert("test.home", days_valid=30)
    assert result is False
    assert not (tmp_path / "test.home.key").exists()

@patch('cert_sentry.socket.create_connection')
@patch('cert_sentry.ssl.create_default_context')
@patch('cert_sentry.x509.load_der_x509_certificate')
def test_tls_probe_get_expiry(mock_load_cert, mock_create_context, mock_create_connection):
    mock_sock = MagicMock()
    mock_ssock = MagicMock()
    mock_create_connection.return_value.__enter__.return_value = mock_sock
    mock_create_context.return_value.wrap_socket.return_value.__enter__.return_value = mock_ssock
    mock_ssock.getpeercert.return_value = b"fake_cert"

    mock_cert = MagicMock()
    fake_expiry = datetime.datetime(2025, 1, 1, tzinfo=datetime.timezone.utc)
    mock_cert.not_valid_after_utc = fake_expiry
    mock_load_cert.return_value = mock_cert

    expiry = TLSProbe.get_expiry("localhost", 443)
    assert expiry == fake_expiry

@patch('cert_sentry.socket.create_connection')
def test_tls_probe_get_expiry_failure(mock_create_connection):
    mock_create_connection.side_effect = Exception("Connection Failed")
    expiry = TLSProbe.get_expiry("localhost", 443)
    assert expiry is None

@patch('cert_sentry.TLSProbe.get_expiry')
def test_sentinel_check_endpoint_healthy(mock_get_expiry, tmp_path):
    manager = CertManager(output_dir=str(tmp_path))
    sentinel = Sentinel(manager, threshold_days=14, dry_run=True)

    # Expiry 30 days in the future
    future_date = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=30)
    mock_get_expiry.return_value = future_date

    # Should not log any warnings
    with patch('cert_sentry.logger.warning') as mock_warning:
        sentinel.check_endpoint("localhost", 443)
        mock_warning.assert_not_called()

@patch('cert_sentry.TLSProbe.get_expiry')
def test_sentinel_check_endpoint_warning(mock_get_expiry, tmp_path):
    manager = CertManager(output_dir=str(tmp_path))
    sentinel = Sentinel(manager, threshold_days=14, dry_run=True)

    # Expiry 5 days and a few minutes in the future to account for execution time
    future_date = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=5, minutes=1)
    mock_get_expiry.return_value = future_date

    with patch('cert_sentry.logger.warning') as mock_warning:
        sentinel.check_endpoint("localhost", 443)
        mock_warning.assert_called_once()
        assert "expires in 5 days" in mock_warning.call_args[0][0]

@patch('cert_sentry.TLSProbe.get_expiry')
def test_sentinel_check_endpoint_probe_failed(mock_get_expiry, tmp_path):
    manager = CertManager(output_dir=str(tmp_path))
    sentinel = Sentinel(manager, threshold_days=14, dry_run=True)

    mock_get_expiry.return_value = None

    with patch('cert_sentry.logger.error') as mock_error:
        sentinel.check_endpoint("localhost", 443)
        mock_error.assert_called_once()
        assert "Could not determine expiry" in mock_error.call_args[0][0]

@patch('cert_sentry.CertManager.issue_cert')
def test_sentinel_scan_local_certs_renewal(mock_issue_cert, tmp_path):
    manager = CertManager(output_dir=str(tmp_path))
    sentinel = Sentinel(manager, threshold_days=14, dry_run=False)

    # Create fake ca.crt to ensure it's ignored
    (tmp_path / "ca.crt").touch()

    # We will mock check_local_file so we don't have to generate a real cert to parse
    with patch.object(sentinel, 'check_local_file') as mock_check_file:
        # File is 5 days from expiry, should trigger renewal
        mock_check_file.return_value = 5
        mock_issue_cert.return_value = True

        # Create a fake cert file
        (tmp_path / "test.home.crt").touch()

        sentinel.scan_local_certs()

        mock_issue_cert.assert_called_once_with("test.home")
