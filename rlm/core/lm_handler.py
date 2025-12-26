"""
LMHandler - Routes LLM requests from the RLM process and environment subprocesses.

Uses a multi-threaded socket server. Protocol: 4-byte length prefix + JSON payload.
"""

from rlm.clients.base_lm import BaseLM
from rlm.core.comms_utils import socket_send, socket_recv, LMRequest, LMResponse

from typing import Optional, Dict
from socketserver import ThreadingTCPServer, StreamRequestHandler
from threading import Thread


class LMRequestHandler(StreamRequestHandler):
    """Socket handler for LLM completion requests."""

    def handle(self):
        try:
            request_data = socket_recv(self.connection)
            if not isinstance(request_data, dict):
                response = LMResponse.error_response("Request must be a JSON object")
                socket_send(self.connection, response.to_dict())
                return

            request = LMRequest.from_dict(request_data)
            if not request.prompt:
                response = LMResponse.error_response(
                    "Missing or invalid 'prompt' in request."
                )
                socket_send(self.connection, response.to_dict())
                return

            handler: LMHandler = self.server.lm_handler  # type: ignore
            client = handler.get_client(request.model)

            content = client.completion(request.prompt)
            prompt_tokens, completion_tokens = client.get_last_usage()
            response = LMResponse.success_response(
                content, prompt_tokens, completion_tokens
            )
            socket_send(self.connection, response.to_dict())

        except Exception as e:
            response = LMResponse.error_response(str(e))
            socket_send(self.connection, response.to_dict())


class ThreadingLMServer(ThreadingTCPServer):
    """Multi-threaded TCP server for LM requests."""

    daemon_threads = True
    allow_reuse_address = True


class LMHandler:
    """
    Handles all LM calls from the RLM main process and environment subprocesses.

    Uses a multi-threaded socket server for concurrent requests.
    Protocol: 4-byte big-endian length prefix + JSON payload.
    """

    def __init__(
        self,
        client: BaseLM,
        host: str = "127.0.0.1",
        port: int = 0,  # auto-assign available port
    ):
        self.default_client = client
        self.clients: Dict[str, BaseLM] = {}
        self.host = host
        self._server: Optional[ThreadingLMServer] = None
        self._thread: Optional[Thread] = None
        self._port = port

    def register_client(self, model_name: str, client: BaseLM) -> None:
        """Register a client for a specific model name."""
        self.clients[model_name] = client

    def get_client(self, model: Optional[str] = None) -> BaseLM:
        """Get client by model name, or return default."""
        if model and model in self.clients:
            return self.clients[model]
        return self.default_client

    @property
    def port(self) -> int:
        """Get the actual port (useful when auto-assigned)."""
        if self._server:
            return self._server.server_address[1]
        return self._port

    @property
    def address(self) -> tuple[str, int]:
        """Get (host, port) tuple for connecting."""
        return (self.host, self.port)

    def start(self) -> tuple[str, int]:
        """Start the socket server in a background thread. Returns (host, port)."""
        if self._server is not None:
            return self.address

        self._server = ThreadingLMServer((self.host, self._port), LMRequestHandler)
        self._server.lm_handler = self  # type: ignore

        self._thread = Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

        return self.address

    def stop(self):
        """Stop the socket server."""
        if self._server:
            self._server.shutdown()
            self._server = None
            self._thread = None

    def completion(self, prompt: str, model: Optional[str] = None) -> str:
        """Direct completion call (for main process use)."""
        return self.get_client(model).completion(prompt)

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
        return False
