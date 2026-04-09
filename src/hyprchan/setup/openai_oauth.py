from __future__ import annotations

import os
import webbrowser
from typing import Optional
from urllib.parse import urlencode

from .utils.server import start_ephemeral_server


class OpenAIOAuth:
    """
    Handles OAuth2 flow for OpenAI Codex models.
    """

    DEFAULT_CLIENT_ID = ""
    DEFAULT_AUTH_URL = "https://auth.openai.com/authorize"
    DEFAULT_SCOPES = ["openid", "profile", "email", "offline_access"]

    def __init__(
        self,
        client_id: Optional[str] = None,
        auth_url: Optional[str] = None,
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
        self.scopes = scopes or self.DEFAULT_SCOPES

    def generate_auth_url(self, port: int = 8080) -> str:
        """
        Generates the OAuth2 authorization URL.
        """
        if not self.client_id:
            raise RuntimeError(
                "OPENAI_OAUTH_CLIENT_ID is required for Codex OAuth flow."
            )
        params = {
            "client_id": self.client_id,
            "redirect_uri": f"http://localhost:{port}",
            "scope": " ".join(self.scopes),
            "response_type": "token",
            "prompt": "login",
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
