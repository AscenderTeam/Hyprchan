import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Optional
from urllib.parse import parse_qs, urlparse


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        query = parse_qs(urlparse(self.path).query)
        token = None

        # Check for common token parameter names
        for key in ["token", "access_token", "code"]:
            if key in query:
                token = query[key][0]
                break

        if token:
            self.server.received_token = token
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(
                b"<html><body><h1>Authentication Successful</h1>"
                b"<p>You can close this window and return to the terminal.</p></body></html>"
            )
        else:
            # If no token in query, it might be in the fragment (implicit flow)
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(b"""
                <html>
                <head><title>Processing...</title></head>
                <body>
                    <h1>Processing authentication...</h1>
                    <script>
                        const hash = window.location.hash.substring(1);
                        if (hash) {
                            const params = new URLSearchParams(hash);
                            const token = params.get('access_token') || params.get('token');
                            if (token) {
                                window.location.search = '?token=' + token;
                            } else {
                                document.body.innerHTML = '<h1>Authentication Failed</h1><p>No token found in fragment.</p>';
                            }
                        } else {
                             document.body.innerHTML = '<h1>Authentication Failed</h1><p>No token or fragment found.</p>';
                        }
                    </script>
                </body>
                </html>
            """)

    def log_message(self, format, *args):
        # Silence server logs
        return


def start_ephemeral_server(port: int = 8080, timeout: int = 60) -> Optional[str]:
    """
    Starts an ephemeral HTTP server to listen for an OAuth callback.
    Returns the received token or None if it times out.
    """
    server = HTTPServer(("localhost", port), OAuthCallbackHandler)
    server.received_token = None
    server.timeout = 0.5  # Short timeout for handle_request loop

    import time
    start_time = time.time()

    while time.time() - start_time < timeout:
        if server.received_token:
            break
        server.handle_request()

    token = server.received_token
    server.server_close()
    return token
