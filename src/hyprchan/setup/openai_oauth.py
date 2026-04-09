from __future__ import annotations

import base64
import hashlib
import os
import secrets
import webbrowser
from typing import Optional
from urllib.parse import urlencode

from .utils.server import start_ephemeral_server


class OpenAIOAuth:
    """
    Handles OAuth2 flow for OpenAI Codex models.
    """

    DEFAULT_CLIENT_ID = "pdl7p9vjrpe9z6ycpl9p"
    DEFAULT_AUTH_URL = "https://auth.openai.com/api/accounts/authorize"
    DEFAULT_ISSUER = "https://auth.openai.com"
    DEFAULT_AUDIENCE = "https://api.openai.com/v1"
    DEFAULT_SCOPES = ["openid", "profile", "email", "offline_access"]

    def __init__(
        self,
        client_id: Optional[str] = None,
        auth_url: Optional[str] = None,
        issuer: Optional[str] = None,
        audience: Optional[str] = None,
        scopes: Optional[list[str]] = None,
    ) -> None:
        self.client_id = (
            client_id
            or os.getenv("OPENAI_OAUTH_CLIENT_ID", "").strip()
            or self.DEFAULT_CLIENT_ID
        )
        self.auth_url = (
            auth_url
            or os.getenv("OPENAI_OAUTH_AUTH_URL", "").strip()
            or self.DEFAULT_AUTH_URL
        )
        self.issuer = (
            issuer
            or os.getenv("OPENAI_OAUTH_ISSUER", "").strip()
            or self.DEFAULT_ISSUER
        )
        self.audience = (
            audience
            or os.getenv("OPENAI_OAUTH_AUDIENCE", "").strip()
            or self.DEFAULT_AUDIENCE
        )
        self.scopes = scopes or self.DEFAULT_SCOPES

    @staticmethod
    def _b64url(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")

    @classmethod
    def _pkce_pair(cls) -> tuple[str, str]:
        verifier = cls._b64url(secrets.token_bytes(64))
        challenge = cls._b64url(hashlib.sha256(verifier.encode("utf-8")).digest())
        return verifier, challenge

    def generate_auth_url(self, port: int = 8080) -> str:
        """
        Generates the OAuth2 authorization URL.
        """
        _, code_challenge = self._pkce_pair()
        params = {
            "issuer": self.issuer,
            "client_id": self.client_id,
            "audience": self.audience,
            "redirect_uri": f"http://localhost:{port}",
            "max_age": "0",
            "scope": " ".join(self.scopes),
            "response_type": "token",
            "response_mode": "query",
            "state": self._b64url(secrets.token_bytes(24)),
            "nonce": self._b64url(secrets.token_bytes(24)),
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        return f"{self.auth_url}?{urlencode(params)}"

    def catch_token(self, port: int = 8080, timeout: int = 120) -> Optional[str]:
        """
        Starts an ephemeral server to catch the bearer token from the redirect.
        """
        # Open the browser automatically
        url = self.generate_auth_url(port)
        print(f"Opening browser for authentication: {url}")
        webbrowser.open(url)

        # Start the server and wait for the token
        token = start_ephemeral_server(port=port, timeout=timeout)
        return token
