import os
import json
import re
import difflib
from typing import Any, Dict, List, Optional
from google.protobuf.json_format import MessageToDict

def proto_to_dict(message: Any) -> Dict[str, Any]:
    """
    Converte um objeto Protobuf do Google Ads para um dicionário Python limpo.
    Garante que Enums sejam convertidos para strings e IDs mantidos como strings.
    Lida com objetos proto-plus do SDK do Google Ads.
    """
    # Se for um objeto do SDK (proto-plus), extraímos o protobuf bruto (_pb)
    obj = getattr(message, "_pb", message)
    
    return MessageToDict(
        obj,
        preserving_proto_field_name=True,
        use_integers_for_enums=False,
        always_print_fields_with_no_presence=True
    )

def dense_proto_to_dict(message: Any) -> Dict[str, Any]:
    """
    Versão densa do proto_to_dict. 
    Remove campos com valores padrão (0, False, string vazia) para economizar tokens.
    Ideal para snapshots e dashboards.
    """
    obj = getattr(message, "_pb", message)
    
    return MessageToDict(
        obj,
        preserving_proto_field_name=True,
        use_integers_for_enums=False,
        always_print_fields_with_no_presence=False # Remove o que não está presente
    )

def format_response(results: List[Dict[str, Any]], customer_id: str, query: str = None, warnings: List[str] = None) -> Dict[str, Any]:
    """
    Formata o envelope de resposta padronizado pela arquitetura.
    """
    return {
        "metadata": {
            "customer_id": str(customer_id),
            "row_count": len(results),
            "query": query,
            "warnings": warnings or []
        },
        "results": results
    }

class GaqlLinter:
    """
    Linter nativo para queries GAQL.
    Valida campos e sugere correções utilizando metadados cacheados.
    """
    def __init__(self):
        self.metadata_dir = os.path.join("docs", "architecture")
        self.resources = ["campaign", "ad_group", "ad_group_ad"]
        self.fields_cache: Dict[str, Dict[str, Any]] = {}
        self._load_metadata()

    def _load_metadata(self):
        """Carrega os arquivos JSON de metadados gerados na auditoria."""
        for res in self.resources:
            file_name = f"api-audit-{res.replace('_', '-')}.json"
            file_path = os.path.join(self.metadata_dir, file_name)
            if os.path.exists(file_path):
                # Tenta primeiro utf-16 pois os arquivos foram gerados via redirect no Windows
                for encoding in ["utf-16", "utf-8"]:
                    try:
                        with open(file_path, "r", encoding=encoding) as f:
                            data = json.load(f)
                            for field in data:
                                self.fields_cache[field["name"]] = field
                        break # Sucesso
                    except Exception:
                        continue

    def validate_query(self, query: str) -> Dict[str, Any]:
        """
        Analisa a query e retorna status de validação.
        """
        # Se não houver cache de campos carregado, delega a validação diretamente à Google Ads API
        if not self.fields_cache:
            return {"valid": True}

        # Extrai campos do SELECT (simplificado)
        select_match = re.search(r"SELECT\s+(.*?)\s+FROM", query, re.IGNORECASE | re.DOTALL)
        if not select_match:
            return {"valid": False, "error": "SELECT clause not found"}

        fields = [f.strip() for f in select_match.group(1).split(",")]
        invalid_fields = []
        
        for field in fields:
            # Remove aliases se houver (ex: campaign.id AS id)
            clean_field = field.split(" AS ")[0].strip()
            if clean_field not in self.fields_cache:
                # Se o campo não está no cache, tentamos encontrar uma sugestão
                suggestion = self.get_suggestion(clean_field)
                invalid_fields.append({
                    "field": clean_field,
                    "suggestion": suggestion
                })

        if invalid_fields:
            return {
                "valid": False,
                "error_code": "INVALID_GAQL_FIELD",
                "invalid_fields": invalid_fields
            }

        return {"valid": True}

    def get_suggestion(self, invalid_field: str) -> Optional[str]:
        """Sugere o campo mais próximo usando distância de Levenshtein."""
        all_fields = list(self.fields_cache.keys())
        matches = difflib.get_close_matches(invalid_field, all_fields, n=1, cutoff=0.6)
        return matches[0] if matches else None

class ResourceResolver:
    """
    Resolve nomes de recursos (Campanhas, Grupos, etc) para IDs numéricos.
    Implementa a estratégia de 'Token Efficiency' da Story 8.1.
    """
    def __init__(self, client):
        self.client = client
        self.ga_service = client.get_service("GoogleAdsService")

    def resolve(self, customer_id: str, resource_type: str, name_or_id: str) -> Dict[str, Any]:
        """
        Tenta resolver um nome para ID.
        Retorna { "id": str, "resolved": bool, "ambiguous": bool, "matches": list }
        """
        name_or_id = str(name_or_id).strip()

        # 1. Se for numérico puro ou resource_name, assume que já é um ID/Path
        if name_or_id.isdigit() or "/" in name_or_id:
            return {"id": name_or_id, "resolved": False, "ambiguous": False}

        # 2. Caso contrário, trata como nome e busca via GAQL
        resource_type = resource_type.upper()
        query = ""
        
        if resource_type == "CAMPAIGN":
            query = f"SELECT campaign.id, campaign.name FROM campaign WHERE campaign.name LIKE '%{name_or_id}%' AND campaign.status != 'REMOVED'"
        elif resource_type == "AD_GROUP":
            query = f"SELECT ad_group.id, ad_group.name FROM ad_group WHERE ad_group.name LIKE '%{name_or_id}%' AND ad_group.status != 'REMOVED'"
        elif resource_type == "USER_LIST":
            query = f"SELECT user_list.id, user_list.name FROM user_list WHERE user_list.name LIKE '%{name_or_id}%'"
        elif resource_type == "ASSET_GROUP":
            query = f"SELECT asset_group.id, asset_group.name FROM asset_group WHERE asset_group.name LIKE '%{name_or_id}%' AND asset_group.status != 'REMOVED'"
        elif resource_type == "AUDIENCE":
            query = f"SELECT audience.id, audience.name FROM audience WHERE audience.name LIKE '%{name_or_id}%'"
        elif resource_type == "CONVERSION_ACTION":
            query = f"SELECT conversion_action.id, conversion_action.name FROM conversion_action WHERE conversion_action.name LIKE '%{name_or_id}%' AND conversion_action.status != 'REMOVED'"
        else:
            return {"error": f"Tipo de recurso '{resource_type}' não suportado para resolução."}

        try:
            response = self.ga_service.search(customer_id=str(customer_id), query=query)
            matches = []
            for row in response:
                if resource_type == "CAMPAIGN":
                    matches.append({"id": str(row.campaign.id), "name": row.campaign.name})
                elif resource_type == "AD_GROUP":
                    matches.append({"id": str(row.ad_group.id), "name": row.ad_group.name})
                elif resource_type == "USER_LIST":
                    matches.append({"id": str(row.user_list.id), "name": row.user_list.name})
                elif resource_type == "ASSET_GROUP":
                    matches.append({"id": str(row.asset_group.id), "name": row.asset_group.name})
                elif resource_type == "AUDIENCE":
                    matches.append({"id": str(row.audience.id), "name": row.audience.name})
                elif resource_type == "CONVERSION_ACTION":
                    matches.append({"id": str(row.conversion_action.id), "name": row.conversion_action.name})

            if len(matches) == 0:
                return {"error": f"Nenhum {resource_type} encontrado com o nome '{name_or_id}'."}
            elif len(matches) == 1:
                return {"id": matches[0]["id"], "resolved": True, "ambiguous": False}
            else:
                return {
                    "error": "AMBIGUITY_DETECTED",
                    "ambiguous": True,
                    "message": f"Múltiplos recursos encontrados para '{name_or_id}'. Por favor, forneça o ID específico.",
                    "matches": matches
                }
        except Exception as e:
            return {"error": f"Erro na API ao resolver nome: {str(e)}"}

def translate_google_ads_error(e: Exception) -> Dict[str, Any]:
    """
    Traduz exceções complexas do Google Ads em mensagens semânticas para a IA.
    Implementa o Self-Healing AI da Story 8.4.
    """
    error_response = {
        "status": "ERROR",
        "error_type": type(e).__name__,
        "message": str(e),
        "suggestions": []
    }

    # Verifica se é uma GoogleAdsException
    if hasattr(e, "failure"):
        try:
            details = []
            for error in e.failure.errors:
                msg = error.message
                code = ""
                
                # Extrai o código de erro específico se disponível
                for field in ["query_error", "request_error", "database_error", "policy_violation_error", "authorization_error"]:
                    if hasattr(error.error_code, field):
                        code = getattr(error.error_code, field).name
                        break
                
                detail = {"code": code, "message": msg}
                
                # Sugestões baseadas no código
                if code == "UNRECOGNIZED_FIELD":
                    error_response["suggestions"].append("Verifique se o campo no SELECT/WHERE existe para este recurso.")
                elif code == "PROHIBITED_EMPTY_TEXT_IN_PARAMETER":
                    error_response["suggestions"].append("Alguns campos de texto não podem ser vazios.")
                elif code == "USER_PERMISSION_DENIED":
                    error_response["message"] = "ACESSO NEGADO: Sua conta não tem permissão para gerenciar este Customer ID."
                    error_response["suggestions"].append("Verifique se o Customer ID está correto ou se você é administrador da conta.")
                elif code == "DEVELOPER_TOKEN_PROHIBITED":
                    error_response["message"] = "TOKEN INVÁLIDO: O Developer Token fornecido não tem permissão para este recurso."
                
                details.append(detail)
            
            error_response["details"] = details
            if details:
                # Se não definimos uma mensagem customizada (semântica) ainda, usamos a do erro
                if error_response["message"] == str(e):
                    error_response["message"] = details[0]["message"]
                error_response["error_code"] = details[0]["code"]

        except Exception:
            pass # Fallback para o erro genérico já montado

    return error_response
