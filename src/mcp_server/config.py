import os
import yaml
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field, SecretStr, ConfigDict
from dotenv import load_dotenv

# Carrega variáveis de ambiente do .env
load_dotenv()

class GoogleAdsConfig(BaseModel):
    """Configurações necessárias para a Google Ads API."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    developer_token: str
    client_id: str
    client_secret: SecretStr
    refresh_token: SecretStr
    login_customer_id: Optional[str] = None
    use_proto_plus: bool = True

    @classmethod
    def load(cls, yaml_path: str = "google-ads.yaml") -> "GoogleAdsConfig":
        """
        Carrega configurações de múltiplas fontes na seguinte prioridade:
        1. Variáveis de ambiente (GOOGLE_ADS_*)
        2. Arquivo YAML (google-ads.yaml)
        """
        config_data = {}

        # 1. Tenta carregar do YAML se existir
        path = Path(yaml_path)
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                yaml_data = yaml.safe_load(f)
                if yaml_data:
                    config_data.update(yaml_data)

        # 2. Sobrescreve com variáveis de ambiente se presentes
        env_mapping = {
            "GOOGLE_ADS_DEVELOPER_TOKEN": "developer_token",
            "GOOGLE_ADS_CLIENT_ID": "client_id",
            "GOOGLE_ADS_CLIENT_SECRET": "client_secret",
            "GOOGLE_ADS_REFRESH_TOKEN": "refresh_token",
            "GOOGLE_ADS_LOGIN_CUSTOMER_ID": "login_customer_id",
        }

        for env_var, key in env_mapping.items():
            val = os.getenv(env_var)
            if val:
                config_data[key] = val

        # Valida e retorna
        return cls(**config_data)

def get_settings() -> GoogleAdsConfig:
    """Singleton para acesso às configurações."""
    return GoogleAdsConfig.load()
