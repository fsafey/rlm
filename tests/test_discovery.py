"""Tests for rlm_search.discovery — Cascade API port-range discovery."""

from __future__ import annotations

from unittest.mock import patch

import pytest
import requests

from rlm_search.discovery import _parse_port_range, _probe_url, discover_cascade_url


class TestParsePortRange:
    def test_range(self):
        assert _parse_port_range("8089-8095") == (8089, 8095)

    def test_single(self):
        assert _parse_port_range("8091") == (8091, 8091)

    def test_whitespace(self):
        assert _parse_port_range("  8089 - 8095  ") == (8089, 8095)


class TestProbeUrl:
    @patch("rlm_search.discovery.requests.get")
    def test_success(self, mock_get):
        mock_get.return_value.status_code = 200
        assert _probe_url("http://localhost:8091") is True
        mock_get.assert_called_once_with("http://localhost:8091/health", timeout=0.5)

    @patch("rlm_search.discovery.requests.get", side_effect=requests.ConnectionError)
    def test_connection_error(self, mock_get):
        assert _probe_url("http://localhost:9999") is False

    @patch("rlm_search.discovery.requests.get", side_effect=requests.Timeout)
    def test_timeout(self, mock_get):
        assert _probe_url("http://localhost:9999") is False


class TestDiscoverCascadeUrl:
    @patch("rlm_search.discovery._probe_url", return_value=True)
    def test_explicit_valid(self, mock_probe):
        url = discover_cascade_url(
            api_url="http://localhost:8090",
            host="localhost",
            port_range="8089-8095",
            explicit=True,
        )
        assert url == "http://localhost:8090"
        mock_probe.assert_called_once_with("http://localhost:8090", timeout=0.5)

    @patch("rlm_search.discovery._probe_url", return_value=False)
    def test_explicit_invalid(self, mock_probe):
        with pytest.raises(ConnectionError, match="unreachable at explicit URL"):
            discover_cascade_url(
                api_url="http://localhost:8090",
                host="localhost",
                port_range="8089-8095",
                explicit=True,
            )

    @patch("rlm_search.discovery._probe_url")
    def test_finds_first_live_port(self, mock_probe):
        # Ports 8089, 8090 fail; 8091 succeeds
        mock_probe.side_effect = [False, False, True]
        url = discover_cascade_url(
            api_url="http://localhost:8090",
            host="localhost",
            port_range="8089-8091",
            explicit=False,
        )
        assert url == "http://localhost:8091"
        assert mock_probe.call_count == 3

    @patch("rlm_search.discovery._probe_url", return_value=False)
    def test_all_fail(self, mock_probe):
        with pytest.raises(ConnectionError, match="not found on localhost ports 8089-8091"):
            discover_cascade_url(
                api_url="http://localhost:8090",
                host="localhost",
                port_range="8089-8091",
                explicit=False,
            )
        assert mock_probe.call_count == 3
