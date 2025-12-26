"""
Communication utilities for RLM socket protocol.

Protocol: 4-byte big-endian length prefix + JSON payload.
Used for communication between LMHandler and environment subprocesses.
"""

from dataclasses import dataclass
from typing import Optional, Tuple, Dict, Any
import socket
import struct
import json


# =============================================================================
# Message Dataclasses
# =============================================================================


@dataclass
class LMRequest:
    """Request message sent to the LM Handler."""

    prompt: str | Dict[str, Any]
    model: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dict, excluding None values."""
        d = {"prompt": self.prompt}
        if self.model is not None:
            d["model"] = self.model
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "LMRequest":
        """Create from dict."""
        return cls(
            prompt=data.get("prompt", ""),
            model=data.get("model"),
        )


@dataclass
class LMResponse:
    """Response message from the LM Handler."""

    content: Optional[str] = None
    error: Optional[str] = None
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def success(self) -> bool:
        """Check if response was successful."""
        return self.error is None

    def to_dict(self) -> dict:
        """Convert to dict, excluding None values."""
        if self.error is not None:
            return {"error": self.error}
        return {
            "content": self.content or "",
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "LMResponse":
        """Create from dict."""
        return cls(
            content=data.get("content"),
            error=data.get("error"),
            prompt_tokens=data.get("prompt_tokens", 0),
            completion_tokens=data.get("completion_tokens", 0),
        )

    @classmethod
    def success_response(
        cls, content: str, prompt_tokens: int = 0, completion_tokens: int = 0
    ) -> "LMResponse":
        """Create a successful response."""
        return cls(
            content=content,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )

    @classmethod
    def error_response(cls, error: str) -> "LMResponse":
        """Create an error response."""
        return cls(error=error)


# =============================================================================
# Socket Protocol Helpers
# =============================================================================


def socket_send(sock: socket.socket, data: dict) -> None:
    """Send a length-prefixed JSON message over socket.

    Protocol: 4-byte big-endian length prefix + UTF-8 JSON payload.
    """
    payload = json.dumps(data).encode("utf-8")
    sock.sendall(struct.pack(">I", len(payload)) + payload)


def socket_recv(sock: socket.socket) -> dict:
    """Receive a length-prefixed JSON message from socket.

    Protocol: 4-byte big-endian length prefix + UTF-8 JSON payload.
    Returns empty dict if connection closed before length received.

    Raises:
        ConnectionError: If connection closes mid-message.
    """
    raw_len = sock.recv(4)
    if not raw_len:
        return {}

    length = struct.unpack(">I", raw_len)[0]
    payload = b""
    while len(payload) < length:
        chunk = sock.recv(length - len(payload))
        if not chunk:
            raise ConnectionError("Connection closed before message complete")
        payload += chunk

    return json.loads(payload.decode("utf-8"))


def socket_request(address: Tuple[str, int], data: dict, timeout: int = 300) -> dict:
    """Send a request and receive a response over a new socket connection.

    Opens a new TCP connection, sends the request, waits for response, then closes.

    Args:
        address: (host, port) tuple to connect to.
        data: Dictionary to send as JSON.
        timeout: Socket timeout in seconds (default 300).

    Returns:
        Response dictionary.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        sock.connect(address)
        socket_send(sock, data)
        return socket_recv(sock)


# =============================================================================
# Typed Request Helpers
# =============================================================================


def send_lm_request(
    address: Tuple[str, int], request: LMRequest, timeout: int = 300
) -> LMResponse:
    """Send an LM request and return typed response.

    Args:
        address: (host, port) tuple of LM Handler server.
        request: LMRequest to send.
        timeout: Socket timeout in seconds.

    Returns:
        LMResponse with content or error.
    """
    try:
        response_data = socket_request(address, request.to_dict(), timeout)
        return LMResponse.from_dict(response_data)
    except Exception as e:
        return LMResponse.error_response(f"Request failed: {e}")
