import os
from google.ads.googleads.client import GoogleAdsClient
from src.mcp_server.config import get_settings

def create_google_ads_client() -> GoogleAdsClient:
    """
    Cria um cliente Google Ads a partir das configurações carregadas.
    """
    bundle_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../custom_bundle.pem"))
    if os.path.exists(bundle_path):
        os.environ["GRPC_DEFAULT_SSL_ROOTS_FILE_PATH"] = bundle_path
        os.environ["SSL_CERT_FILE"] = bundle_path

    settings = get_settings()

    config = {
        "developer_token": settings.developer_token,
        "client_id": settings.client_id,
        "client_secret": settings.client_secret.get_secret_value(),
        "refresh_token": settings.refresh_token.get_secret_value(),
        "use_proto_plus": settings.use_proto_plus,
    }

    if settings.login_customer_id:
        config["login_customer_id"] = settings.login_customer_id

    # O GoogleAdsClient pode carregar de um dicionário
    return GoogleAdsClient.load_from_dict(config)
