import socket
import hashlib
import webbrowser
import urllib.parse
import os
from typing import Optional
from google_auth_oauthlib.flow import Flow

_PORT = 8080
_SERVER = "127.0.0.1"
_REDIRECT_URI = f"http://{_SERVER}:{_PORT}"
_SCOPE = "https://www.googleapis.com/auth/adwords"

def run_oauth_flow(client_id: str, client_secret: str) -> Optional[str]:
    """Inicia o fluxo OAuth e captura o token localmente para a Skill."""
    client_config = {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [_REDIRECT_URI]
        }
    }

    try:
        flow = Flow.from_client_config(client_config, scopes=[_SCOPE])
        flow.redirect_uri = _REDIRECT_URI
        state_token = hashlib.sha256(os.urandom(1024)).hexdigest()

        auth_url, _ = flow.authorization_url(
            access_type="offline",
            state=state_token,
            prompt="consent",
            include_granted_scopes="true",
        )

        # Abre o navegador para o usuário
        webbrowser.open(auth_url)

        # Servidor local para capturar o código
        sock = socket.socket()
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((_SERVER, _PORT))
        sock.listen(1)
        
        connection, _ = sock.accept()
        data = connection.recv(2048)
        decoded = data.decode("utf-8")
        
        import re
        match = re.search(r"GET\s\/\?(.*) ", decoded)
        if not match:
            return None
            
        params = dict(urllib.parse.parse_qsl(match.group(1)))
        
        html_response = (
            "HTTP/1.1 200 OK\n"
            "Content-Type: text/html\n\n"
            "<html><body style='font-family: Arial; text-align: center; margin-top: 50px;'>"
            "<h2>Autenticação Concluída!</h2>"
            "<p>Você já pode fechar esta aba e voltar para a sua Skill.</p>"
            "</body></html>"
        )
        connection.sendall(html_response.encode("utf-8"))
        connection.close()

        if "error" in params:
            return None
            
        code = params.get("code")
        flow.fetch_token(code=code)
        return flow.credentials.refresh_token

    except Exception:
        return None
