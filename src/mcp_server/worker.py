import sys
import os
from typing import Optional

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from mcp.server.fastmcp import FastMCP
from src.mcp_server import logic, auth, config

mcp = FastMCP("Google Ads AI Skill Worker")

# ─────────────────────────────────────────────
# SETUP & UTILITY
# ─────────────────────────────────────────────

@mcp.tool()
def run_setup(client_id: str, client_secret: str, developer_token: str, login_customer_id: str = None) -> dict:
    """
    [SETUP] Inicia o fluxo de autenticação OAuth. Abre o navegador para login e salva as credenciais no .env.
    """
    try:
        refresh_token = auth.run_oauth_flow(client_id, client_secret)
        if not refresh_token:
            return {"status": "ERROR", "message": "Falha na autenticação via navegador."}
        with open(".env", "w") as f:
            f.write(f"GOOGLE_ADS_DEVELOPER_TOKEN={developer_token}\n")
            f.write(f"GOOGLE_ADS_CLIENT_ID={client_id}\n")
            f.write(f"GOOGLE_ADS_CLIENT_SECRET={client_secret}\n")
            f.write(f"GOOGLE_ADS_REFRESH_TOKEN={refresh_token}\n")
            if login_customer_id:
                f.write(f"GOOGLE_ADS_LOGIN_CUSTOMER_ID={login_customer_id.replace('-', '')}\n")
        return {"status": "SUCCESS", "message": "Autenticação concluída e configurada!"}
    except Exception as e:
        return {"status": "ERROR", "message": str(e)}


@mcp.tool()
def check_connection() -> dict:
    """[UTILITY] Verifica se o Worker está pronto e autenticado."""
    return {"status": logic.connection_status()}


@mcp.tool()
def list_accounts() -> dict:
    """[UTILITY] Lista todas as contas acessíveis (MCC e sub-contas)."""
    return logic.list_accessible_customers()


# ─────────────────────────────────────────────
# REPORTING & AUDIT
# ─────────────────────────────────────────────

@mcp.tool()
def get_account_snapshot(customer_id: str, date_range: str = "LAST_30_DAYS") -> dict:
    """[REPORT] Snapshot de saúde da conta: campanhas ativas, budget, impressões, cliques, ROAS."""
    return logic.get_account_snapshot(customer_id, date_range)


@mcp.tool()
def get_advertiser_verification_status(customer_id: str) -> dict:
    """[REPORT] Consulta o status de Verificação de Identidade do Anunciante (Advertiser Identity Verification), prazos limites (deadlines), se anúncios estão pausados e o link de envio de documentos."""
    return logic.get_advertiser_verification_status(customer_id)


@mcp.tool()
def get_account_alerts_and_notices(customer_id: str) -> dict:
    """[REPORT] Diagnóstico 360° de alertas críticos e avisos da conta: suspensões, verificação de anunciante pendente, faturamento/billing, campanhas com bloqueio de entrega e reprovações de política."""
    return logic.get_account_alerts_and_notices(customer_id)


@mcp.tool()
def get_budget_pacing_and_exhaustion(customer_id: str, target_monthly_budget: float = None) -> dict:
    """[REPORT] Analisa o consumo de orçamento (budget pacing) no mês atual: run rate projetado, risco de estouro ou sub-investimento e orçamento diário recomendado."""
    return logic.get_budget_pacing_and_exhaustion(customer_id, target_monthly_budget)


@mcp.tool()
def get_conversion_tracking_health(customer_id: str) -> dict:
    """[REPORT] Audita a saúde das tags e ações de conversão da conta: identifica conversões primárias pausadas, inativas ou sem disparos recentes."""
    return logic.get_conversion_tracking_health(customer_id)


@mcp.tool()
def get_auction_competitor_drift(customer_id: str, campaign_id: str = None) -> dict:
    """[REPORT] Radar Competitivo de Leilão: compara os últimos 7 dias com os últimos 30 dias para identificar novos concorrentes e subida de agressividade no leilão."""
    return logic.get_auction_competitor_drift(customer_id, campaign_id)


@mcp.tool()
def get_policy_violations_and_appeals(customer_id: str, campaign_id: str = None) -> dict:
    """[REPORT] Diagnóstico de políticas e recursos de anúncios: identifica anúncios reprovados (DISAPPROVED), limitados (APPROVED_LIMITED) e em apelação (UNDER_APPEAL)."""
    return logic.get_policy_violations_and_appeals(customer_id, campaign_id)


@mcp.tool()
def get_campaign_performance(customer_id: str, date_range: str = "LAST_7_DAYS") -> dict:
    """[REPORT] Performance detalhada por campanha: cliques, impressões, custo, conversões."""
    return logic.get_campaign_performance(customer_id, date_range)


@mcp.tool()
def get_search_terms(customer_id: str, date_range: str = "LAST_30_DAYS", min_clicks: int = 1) -> dict:
    """[REPORT] Relatório de termos de pesquisa. Use min_clicks para filtrar ruído."""
    return logic.get_search_terms(customer_id, date_range, min_clicks)


@mcp.tool()
def get_change_history(customer_id: str, last_n_days: int = 7) -> dict:
    """[REPORT] Histórico de alterações recentes na conta."""
    return logic.get_change_history(customer_id, last_n_days)


@mcp.tool()
def get_account_capabilities(customer_id: str) -> dict:
    """[REPORT] Tipos de campanha ativos, extensões configuradas e features habilitadas."""
    return logic.get_account_capabilities(customer_id)


@mcp.tool()
def get_demographic_insights(customer_id: str, date_range: str = "LAST_30_DAYS") -> dict:
    """[REPORT] Performance segmentada por faixa etária, gênero e renda."""
    return logic.get_demographic_insights(customer_id, date_range)


@mcp.tool()
def get_keyword_performance(customer_id: str, date_range: str = "LAST_30_DAYS", campaign_id: str = None) -> dict:
    """[REPORT] Performance por keyword: Quality Score, CPC médio, impressões, cliques, conversões. campaign_id é opcional."""
    return logic.get_keyword_performance(customer_id, date_range, campaign_id)


@mcp.tool()
def get_ad_performance(customer_id: str, date_range: str = "LAST_30_DAYS", campaign_id: str = None) -> dict:
    """[REPORT] Performance por anúncio RSA: força do anúncio, CTR, conversões. campaign_id é opcional."""
    return logic.get_ad_performance(customer_id, date_range, campaign_id)


@mcp.tool()
def get_auction_insights(customer_id: str, date_range: str = "LAST_30_DAYS", campaign_id: str = None) -> dict:
    """[REPORT] Análise competitiva: impression share vs concorrentes no leilão. campaign_id é opcional."""
    return logic.get_auction_insights(customer_id, date_range, campaign_id)


@mcp.tool()
def list_conversion_actions(customer_id: str) -> dict:
    """[REPORT] Lista todas as ações de conversão configuradas na conta."""
    return logic.list_conversion_actions(customer_id)


@mcp.tool()
def get_recommendations(customer_id: str) -> dict:
    """[REPORT] Lista recomendações de otimização do Google Ads para a conta."""
    return logic.get_recommendations(customer_id)


@mcp.tool()
def get_shared_negative_lists(customer_id: str) -> dict:
    """[REPORT] Lista as listas de palavras-chave negativas compartilhadas entre campanhas."""
    return logic.get_shared_negative_lists(customer_id)


@mcp.tool()
def search_ads(query: str, customer_id: str = None) -> dict:
    """[CUSTOM] Executa uma query GAQL customizada. Escape hatch para qualquer consulta não coberta pelos outros tools."""
    return logic.search_ads(query, customer_id)


@mcp.tool()
def upload_image_asset(customer_id: str, image_url: str, asset_name: str) -> dict:
    """[CREATE] Faz upload de imagem para a biblioteca de assets da conta. Necessário para PMax e anúncios gráficos."""
    return logic.upload_image_asset(customer_id, image_url, asset_name)


@mcp.tool()
def get_device_performance(customer_id: str, date_range: str = "LAST_30_DAYS", campaign_id: str = None) -> dict:
    """[REPORT] Performance segmentada por dispositivo: Mobile, Desktop, Tablet. campaign_id é opcional."""
    return logic.get_device_performance(customer_id, date_range, campaign_id)


@mcp.tool()
def get_geographic_performance(customer_id: str, date_range: str = "LAST_30_DAYS", campaign_id: str = None) -> dict:
    """[REPORT] Performance por localização geográfica (cidade, estado, país). campaign_id é opcional."""
    return logic.get_geographic_performance(customer_id, date_range, campaign_id)


@mcp.tool()
def get_hourly_performance(customer_id: str, date_range: str = "LAST_7_DAYS", campaign_id: str = None) -> dict:
    """[REPORT] Performance por hora do dia para configurar dayparting. campaign_id é opcional."""
    return logic.get_hourly_performance(customer_id, date_range, campaign_id)


@mcp.tool()
def get_asset_performance(customer_id: str, date_range: str = "LAST_30_DAYS", campaign_id: str = None) -> dict:
    """[REPORT] Performance individual de cada headline e description dentro dos RSAs. campaign_id é opcional."""
    return logic.get_asset_performance(customer_id, date_range, campaign_id)


@mcp.tool()
def get_landing_page_performance(customer_id: str, date_range: str = "LAST_30_DAYS") -> dict:
    """[REPORT] Métricas por URL de destino: cliques, conversões, custo médio por clique."""
    return logic.get_landing_page_performance(customer_id, date_range)


@mcp.tool()
def get_audience_performance(customer_id: str, date_range: str = "LAST_30_DAYS", campaign_id: str = None) -> dict:
    """[REPORT] Performance por segmento de audiência aplicado às campanhas. campaign_id é opcional."""
    return logic.get_audience_performance(customer_id, date_range, campaign_id)


@mcp.tool()
def get_network_performance(customer_id: str, date_range: str = "LAST_30_DAYS", campaign_id: str = None) -> dict:
    """[REPORT] Performance por rede: Google Search, Search Partners e Display Network. campaign_id é opcional."""
    return logic.get_network_performance(customer_id, date_range, campaign_id)


# ─────────────────────────────────────────────
# KEYWORD RESEARCH
# ─────────────────────────────────────────────

@mcp.tool()
def keyword_volume(customer_id: str, keywords: list) -> dict:
    """[RESEARCH] Volume de busca médio mensal e métricas históricas para uma lista de palavras-chave."""
    return logic.get_keyword_historical_metrics(customer_id, keywords)


@mcp.tool()
def keyword_ideas(customer_id: str, keywords: list = None, page_url: str = None) -> dict:
    """[RESEARCH] Sugestões de palavras-chave a partir de termos semente ou URL de página."""
    return logic.generate_keyword_ideas(customer_id, keywords, page_url)


@mcp.tool()
def keyword_forecast(customer_id: str, keywords: list) -> dict:
    """[RESEARCH] Previsão de cliques e impressões para uma lista de palavras-chave."""
    return logic.get_keyword_forecast(customer_id, keywords)


# ─────────────────────────────────────────────
# CAMPAIGN CREATION (ATOMIC)
# ─────────────────────────────────────────────

@mcp.tool()
def create_search_campaign(customer_id: str, campaign_name: str, daily_budget: float) -> dict:
    """[CREATE] Cria uma campanha de pesquisa. Criada PAUSADA por segurança."""
    return logic.create_search_campaign(customer_id, campaign_name, daily_budget)


@mcp.tool()
def create_ad_group(customer_id: str, campaign_id: str, ad_group_name: str, cpc_bid: float = 1.0) -> dict:
    """[CREATE] Cria um grupo de anúncios dentro de uma campanha."""
    return logic.create_ad_group(customer_id, campaign_id, ad_group_name, cpc_bid)


@mcp.tool()
def add_keywords(customer_id: str, ad_group_id: str, keywords: list, match_type: str = "BROAD") -> dict:
    """[CREATE] Adiciona palavras-chave a um grupo. match_type: BROAD | PHRASE | EXACT."""
    return logic.add_keywords(customer_id, ad_group_id, keywords, match_type)


@mcp.tool()
def create_responsive_search_ad(
    customer_id: str,
    ad_group_id: str,
    headlines: list,
    descriptions: list,
    final_url: str
) -> dict:
    """[CREATE] Cria um RSA (Responsive Search Ad). Mínimo 3 headlines e 2 descriptions."""
    return logic.create_responsive_search_ad(customer_id, ad_group_id, headlines, descriptions, final_url)


@mcp.tool()
def create_pmax_campaign(
    customer_id: str, 
    campaign_name: str, 
    daily_budget: float, 
    final_url: str,
    headlines: list = None,
    descriptions: list = None
) -> dict:
    """[CREATE] Cria uma campanha Performance Max com Asset Group inicial. Criada PAUSADA por segurança."""
    return logic.create_pmax_campaign(
        customer_id=customer_id, 
        campaign_name=campaign_name, 
        daily_budget_amount=daily_budget, 
        final_url=final_url,
        headlines=headlines,
        descriptions=descriptions
    )


# ─────────────────────────────────────────────
# CAMPAIGN CREATION (CONVENIENCE)
# ─────────────────────────────────────────────

@mcp.tool()
def create_campaign_structure(
    customer_id: str,
    campaign_name: str,
    daily_budget: float,
    keywords: list,
    ad_group_name: str = None,
    cpc_bid: float = 1.0,
    match_type: str = "BROAD"
) -> dict:
    """
    [CREATE] Cria Campanha + Grupo de Anúncios + Palavras-chave em um único passo.
    Use quando não precisar criar RSAs ainda. Campanha criada PAUSADA.
    """
    try:
        camp = logic.create_search_campaign(customer_id, campaign_name, daily_budget)
        if camp.get("status") != "SUCCESS":
            return camp
        campaign_id = camp["campaign"].split("/")[-1]

        ag_name = ad_group_name or f"{campaign_name} - Grupo 1"
        ag = logic.create_ad_group(customer_id, campaign_id, ag_name, cpc_bid)
        if ag.get("status") != "SUCCESS":
            return {"status": "PARTIAL", "campaign": camp, "ad_group_error": ag}
        ad_group_id = ag["ad_group_id"].split("/")[-1]

        kw = logic.add_keywords(customer_id, ad_group_id, keywords, match_type)

        return {
            "status": "SUCCESS",
            "campaign": {"id": campaign_id, "name": campaign_name},
            "ad_group": {"id": ad_group_id, "name": ag_name},
            "keywords": kw,
            "note": "Campanha criada PAUSADA."
        }
    except Exception as e:
        return {"status": "ERROR", "message": str(e)}


@mcp.tool()
def create_full_campaign(
    customer_id: str,
    campaign_name: str,
    daily_budget: float,
    final_url: str,
    groups: list
) -> dict:
    """
    [CREATE] Cria campanha completa com múltiplos grupos, keywords e RSAs em um único passo.
    Cada grupo deve ter: {name, keywords, headlines (min 3), descriptions (min 2)}.
    Campanha criada PAUSADA por segurança.
    """
    try:
        camp = logic.create_search_campaign(customer_id, campaign_name, daily_budget)
        if camp.get("status") != "SUCCESS":
            return camp
        campaign_id = camp["campaign"].split("/")[-1]

        results = {"campaign": {"id": campaign_id, "name": campaign_name}, "groups": []}

        for group in groups:
            ag = logic.create_ad_group(customer_id, campaign_id, group["name"])
            if ag.get("status") != "SUCCESS":
                results["groups"].append({"name": group["name"], "error": ag})
                continue
            ad_group_id = ag["ad_group_id"].split("/")[-1]

            kw = logic.add_keywords(customer_id, ad_group_id, group["keywords"], "BROAD")
            ad = logic.create_responsive_search_ad(
                customer_id, ad_group_id, group["headlines"], group["descriptions"], final_url
            )

            results["groups"].append({
                "name": group["name"],
                "ad_group_id": ad_group_id,
                "keywords_added": kw.get("added_count", 0),
                "ad_status": ad.get("status")
            })

        results["status"] = "SUCCESS"
        results["note"] = "Campanha criada PAUSADA. Ative manualmente quando pronto."
        return results
    except Exception as e:
        return {"status": "ERROR", "message": str(e)}


# ─────────────────────────────────────────────
# OPTIMIZATION (MUTATIONS)
# ─────────────────────────────────────────────

@mcp.tool()
def add_negative_keywords(customer_id: str, campaign_id: str, keywords: list, match_type: str = "BROAD") -> dict:
    """[MUTATION] Adiciona palavras-chave negativas a uma campanha."""
    return logic.add_negative_keywords(customer_id, campaign_id, keywords, match_type)


@mcp.tool()
def set_campaign_budget(customer_id: str, campaign_id: str, amount: float) -> dict:
    """[MUTATION] Atualiza o orçamento diário de uma campanha (em reais)."""
    return logic.set_campaign_budget(customer_id, campaign_id, amount)


@mcp.tool()
def set_campaign_status(customer_id: str, campaign_id: str, status: str) -> dict:
    """[MUTATION] Altera o status de uma campanha. status: ENABLED | PAUSED | REMOVED."""
    return logic.set_campaign_status(customer_id, campaign_id, status)


@mcp.tool()
def set_campaign_bid_ceiling(customer_id: str, campaign_id: str, bid_ceiling: float = None) -> dict:
    """[MUTATION] Ajusta o teto de lance máximo de CPC (cpc_bid_ceiling_micros) em campanhas Maximizar Cliques (TARGET_SPEND). bid_ceiling em Reais (ex: 2.50). Se 0 ou null, remove o teto."""
    return logic.set_campaign_bid_ceiling(customer_id, campaign_id, bid_ceiling)


@mcp.tool()
def update_rsa_assets(customer_id: str, ad_id: str, headlines: list, descriptions: list) -> dict:
    """[MUTATION] Atualiza os assets (headlines/descriptions) de um RSA existente."""
    return logic.update_rsa_assets(customer_id, ad_id, headlines, descriptions)


@mcp.tool()
def replace_keywords_exact(customer_id: str, ad_group_ids: list) -> dict:
    """
    [MUTATION] Remove todas as keywords de uma lista de ad groups e recria com correspondência EXATA.
    """
    try:
        client = logic.create_google_ads_client()
        ga_service = client.get_service("GoogleAdsService")
        criterion_service = client.get_service("AdGroupCriterionService")
        results = []

        for ad_group_id in ad_group_ids:
            query = f"""
                SELECT ad_group_criterion.resource_name, ad_group_criterion.keyword.text
                FROM ad_group_criterion
                WHERE ad_group_criterion.type = 'KEYWORD'
                AND ad_group_criterion.status != 'REMOVED'
                AND ad_group.id = {ad_group_id}
            """
            rows = ga_service.search(customer_id=str(customer_id), query=query)
            keywords_found = [
                (r.ad_group_criterion.resource_name, r.ad_group_criterion.keyword.text)
                for r in rows
            ]

            if not keywords_found:
                results.append({"ad_group_id": ad_group_id, "status": "SKIP", "reason": "sem keywords"})
                continue

            remove_ops = []
            for rn, _ in keywords_found:
                op = client.get_type("AdGroupCriterionOperation")
                op.remove = rn
                remove_ops.append(op)
            criterion_service.mutate_ad_group_criteria(customer_id=str(customer_id), operations=remove_ops)

            texts = [kw for _, kw in keywords_found]
            logic.add_keywords(customer_id, str(ad_group_id), texts, "EXACT")
            results.append({
                "ad_group_id": ad_group_id,
                "status": "SUCCESS",
                "replaced": len(texts),
                "keywords": texts
            })

        return {"status": "SUCCESS", "results": results}
    except Exception as e:
        return {"status": "ERROR", "message": str(e)}


@mcp.tool()
def set_keyword_bid(customer_id: str, ad_group_id: str, keyword_resource_name: str, new_bid: float) -> dict:
    """[MUTATION] Ajusta o CPC de uma keyword individual. keyword_resource_name obtido via get_keyword_performance."""
    return logic.set_keyword_bid(customer_id, ad_group_id, keyword_resource_name, new_bid)


@mcp.tool()
def set_ad_group_status(customer_id: str, ad_group_id: str, status: str) -> dict:
    """[MUTATION] Pausa ou ativa um grupo de anúncios. status: ENABLED | PAUSED. Aceita ID numérico ou Nome."""
    return logic.set_ad_group_status(customer_id, ad_group_id, status)


@mcp.tool()
def add_callout_extension(customer_id: str, campaign_id: str, callouts: list) -> dict:
    """[MUTATION] Adiciona extensões de callout a uma campanha. callouts: lista de strings (máx 25 chars cada)."""
    return logic.add_callout_extension(customer_id, campaign_id, callouts)


@mcp.tool()
def add_call_extension(customer_id: str, campaign_id: str, phone_number: str, country_code: str = "BR") -> dict:
    """[MUTATION] Adiciona extensão de ligação (número de telefone) a uma campanha."""
    return logic.add_call_extension(customer_id, campaign_id, phone_number, country_code)


@mcp.tool()
def add_structured_snippet(customer_id: str, campaign_id: str, header: str, values: list) -> dict:
    """[MUTATION] Adiciona extensão de snippets estruturados. header: Serviços|Marcas|Cursos|etc. values: lista de até 10 itens."""
    return logic.add_structured_snippet(customer_id, campaign_id, header, values)


@mcp.tool()
def add_promotion_extension(customer_id: str, campaign_id: str, promotion_text: str, discount_modifier: str, discount_value: float, final_url: str, start_date: str = None, end_date: str = None) -> dict:
    """[MUTATION] Adiciona extensão de promoção. discount_modifier: PERCENT_OFF|UP_TO_PERCENT_OFF|AMOUNT_OFF|UP_TO_AMOUNT_OFF."""
    return logic.add_promotion_extension(customer_id, campaign_id, promotion_text, discount_modifier, discount_value, final_url, start_date, end_date)


@mcp.tool()
def apply_recommendation(customer_id: str, recommendation_resource_name: str) -> dict:
    """[MUTATION] Aplica uma recomendação do Google Ads. Obtenha o resource_name via get_recommendations."""
    return logic.apply_recommendation(customer_id, recommendation_resource_name)


@mcp.tool()
def dismiss_recommendation(customer_id: str, recommendation_resource_name: str) -> dict:
    """[MUTATION] Descarta uma recomendação do Google Ads."""
    return logic.dismiss_recommendation(customer_id, recommendation_resource_name)


@mcp.tool()
def bulk_pause_keywords(
    customer_id: str,
    min_clicks: int = 10,
    max_conversions: float = 0,
    date_range: str = "LAST_30_DAYS",
    dry_run: bool = True
) -> dict:
    """[MUTATION] Pausa em lote keywords com cliques >= min_clicks e conversões <= max_conversions. dry_run=True por padrão."""
    return logic.bulk_pause_keywords(customer_id, min_clicks, max_conversions, date_range, dry_run)


@mcp.tool()
def set_ad_group_bid(customer_id: str, ad_group_id: str, cpc_bid: float) -> dict:
    """[MUTATION] Atualiza o CPC padrão de um grupo de anúncios."""
    return logic.set_ad_group_bid(customer_id, ad_group_id, cpc_bid)


@mcp.tool()
def create_shared_negative_list(customer_id: str, name: str, keywords: list = None, match_type: str = "BROAD") -> dict:
    """[CREATE] Cria lista de negativos compartilhada entre campanhas. Use link_shared_negative_list para aplicar a campanhas."""
    return logic.create_shared_negative_list(customer_id, name, keywords, match_type)


@mcp.tool()
def remove_campaign_asset(customer_id: str, campaign_asset_resource_name: str) -> dict:
    """[MUTATION] Remove uma extensão de campanha (sitelink, callout, etc). Use search_ads para obter o resource_name."""
    return logic.remove_campaign_asset(customer_id, campaign_asset_resource_name)


@mcp.tool()
def add_price_extension(customer_id: str, campaign_id: str, price_qualifier: str, language_code: str, items: list) -> dict:
    """[MUTATION] Adiciona extensão de tabela de preços. Cada item: {header, description, price, unit, final_url}."""
    return logic.add_price_extension(customer_id, campaign_id, price_qualifier, language_code, items)


@mcp.tool()
def add_campaign_sitelinks(customer_id: str, campaign_id: str, sitelinks: list) -> dict:
    """
    [MUTATION] Adiciona extensões de sitelink a uma campanha.
    Cada sitelink deve ter: {text, description1, description2, final_url}.
    """
    try:
        client = logic.create_google_ads_client()
        asset_service = client.get_service("AssetService")
        campaign_asset_service = client.get_service("CampaignAssetService")
        campaign_service = client.get_service("CampaignService")

        added = []
        for sl in sitelinks:
            asset_op = client.get_type("AssetOperation")
            asset = asset_op.create
            asset.sitelink_asset.link_text = sl["text"][:25]
            asset.sitelink_asset.description1 = sl.get("description1", "")[:35]
            asset.sitelink_asset.description2 = sl.get("description2", "")[:35]
            asset.final_urls.append(sl["final_url"])

            asset_res = asset_service.mutate_assets(customer_id=str(customer_id), operations=[asset_op])
            asset_rn = asset_res.results[0].resource_name

            ca_op = client.get_type("CampaignAssetOperation")
            ca = ca_op.create
            ca.asset = asset_rn
            ca.campaign = campaign_service.campaign_path(customer_id, campaign_id)
            ca.field_type = client.enums.AssetFieldTypeEnum.SITELINK
            campaign_asset_service.mutate_campaign_assets(customer_id=str(customer_id), operations=[ca_op])

            added.append({"text": sl["text"], "url": sl["final_url"]})

        return {"status": "SUCCESS", "sitelinks_added": len(added), "sitelinks": added}
    except Exception as e:
        return {"status": "ERROR", "message": str(e)}


# ─────────────────────────────────────────────
# TARGETING & BID ADJUSTMENTS
# ─────────────────────────────────────────────

@mcp.tool()
def set_device_bid_adjustment(customer_id: str, campaign_id: str, device: str, modifier: float) -> dict:
    """[MUTATION] Ajusta o bid por dispositivo. device: MOBILE|DESKTOP|TABLET. modifier: 0.0 (excluir) a 10.0 (1.0 = sem ajuste)."""
    return logic.set_device_bid_adjustment(customer_id, campaign_id, device, modifier)


@mcp.tool()
def set_location_targeting(customer_id: str, campaign_id: str, geo_target_ids: list, negative: bool = False) -> dict:
    """[MUTATION] Adiciona alvos de localização a uma campanha. Use search_geo_targets para obter IDs. negative=True para excluir."""
    return logic.set_location_targeting(customer_id, campaign_id, geo_target_ids, negative)


@mcp.tool()
def set_language_targeting(customer_id: str, campaign_id: str, language_ids: list) -> dict:
    """[MUTATION] Define idiomas alvo de uma campanha. IDs: 1014=pt-BR, 1000=en, 1003=es."""
    return logic.set_language_targeting(customer_id, campaign_id, language_ids)


@mcp.tool()
def set_ad_schedule(customer_id: str, campaign_id: str, schedules: list) -> dict:
    """[MUTATION] Configura dayparting na campanha. Cada schedule: {day_of_week, start_hour, end_hour, bid_modifier}. day_of_week: MONDAY..SUNDAY."""
    return logic.set_ad_schedule(customer_id, campaign_id, schedules)


@mcp.tool()
def search_geo_targets(location_name: str, country_code: str = "BR") -> dict:
    """[UTILITY] Busca IDs de localização por nome. Use antes de set_location_targeting."""
    return logic.search_geo_targets(location_name, country_code)


@mcp.tool()
def create_label(customer_id: str, name: str, description: str = "") -> dict:
    """[CREATE] Cria uma etiqueta para organizar campanhas, grupos e keywords."""
    return logic.create_label(customer_id, name, description)


@mcp.tool()
def apply_label(customer_id: str, label_id: str, resource_type: str, resource_ids: list) -> dict:
    """[MUTATION] Aplica etiqueta a campanhas ou grupos. resource_type: CAMPAIGN|AD_GROUP."""
    return logic.apply_label(customer_id, label_id, resource_type, resource_ids)


@mcp.tool()
def list_labels(customer_id: str) -> dict:
    """[REPORT] Lista todas as etiquetas da conta."""
    return logic.list_labels(customer_id)


# ─────────────────────────────────────────────
# BID STRATEGIES
# ─────────────────────────────────────────────

@mcp.tool()
def list_bid_strategies(customer_id: str) -> dict:
    """[REPORT] Lista estratégias de lance de portfólio configuradas na conta."""
    return logic.list_bid_strategies(customer_id)


@mcp.tool()
def create_bid_strategy(customer_id: str, name: str, strategy_type: str, target_value: float = None) -> dict:
    """[CREATE] Cria estratégia de lance de portfólio. strategy_type: TARGET_CPA|TARGET_ROAS|MAXIMIZE_CONVERSIONS|MAXIMIZE_CONVERSION_VALUE."""
    return logic.create_bid_strategy(customer_id, name, strategy_type, target_value)


@mcp.tool()
def apply_bid_strategy(customer_id: str, campaign_id: str, bid_strategy_id: str) -> dict:
    """[MUTATION] Aplica uma estratégia de lance de portfólio a uma campanha."""
    return logic.apply_bid_strategy(customer_id, campaign_id, bid_strategy_id)


@mcp.tool()
def create_shared_budget(customer_id: str, name: str, amount: float) -> dict:
    """[CREATE] Cria um orçamento compartilhado entre múltiplas campanhas."""
    return logic.create_shared_budget(customer_id, name, amount)


@mcp.tool()
def apply_shared_budget(customer_id: str, campaign_id: str, shared_budget_resource_name: str) -> dict:
    """[MUTATION] Aplica um orçamento compartilhado a uma campanha."""
    return logic.apply_shared_budget(customer_id, campaign_id, shared_budget_resource_name)


@mcp.tool()
def link_shared_negative_list(customer_id: str, campaign_id: str, shared_set_id: str) -> dict:
    """[MUTATION] Aplica uma lista de negativos compartilhada a uma campanha."""
    return logic.link_shared_negative_list(customer_id, campaign_id, shared_set_id)


# ─────────────────────────────────────────────
# CONVERSIONS
# ─────────────────────────────────────────────

@mcp.tool()
def create_conversion_action(customer_id: str, name: str, category: str, conversion_type: str = "WEBPAGE", default_value: float = 0.0) -> dict:
    """[CREATE] Cria uma nova ação de conversão. category: PURCHASE|LEAD|SIGNUP|PAGE_VIEW|OTHER."""
    return logic.create_conversion_action(customer_id, name, category, conversion_type, default_value)


@mcp.tool()
def upload_offline_conversions(customer_id: str, conversions: list) -> dict:
    """[MUTATION] Importa conversões offline (ex: vendas do CRM). Cada item: {gclid, conversion_action_id, conversion_date_time, conversion_value}."""
    return logic.upload_offline_conversions(customer_id, conversions)


# ─────────────────────────────────────────────
# AUDIENCES
# ─────────────────────────────────────────────

@mcp.tool()
def list_user_lists(customer_id: str) -> dict:
    """[REPORT] Lista as audiências (remarketing lists) disponíveis na conta."""
    return logic.list_user_lists(customer_id)


@mcp.tool()
def link_audience_to_adgroup(customer_id: str, ad_group_id: str, user_list_id: str, bid_modifier: float = 1.0) -> dict:
    """[MUTATION] Vincula uma audiência de remarketing a um grupo de anúncios."""
    return logic.link_audience_to_adgroup(customer_id, ad_group_id, user_list_id, bid_modifier)


@mcp.tool()
def remove_ad_group_criterion(
    customer_id: str,
    ad_group_id: str = None,
    criterion_id: str = None,
    criterion_resource_name: str = None
) -> dict:
    """[MUTATION] Remove/desvincula um público-alvo ou critério de um grupo de anúncios. Aceita criterion_resource_name OU ad_group_id + criterion_id."""
    return logic.remove_ad_group_criterion(customer_id, ad_group_id, criterion_id, criterion_resource_name)


# ─────────────────────────────────────────────
# ADVANCED FEATURES
# ─────────────────────────────────────────────

@mcp.tool()
def get_reach_forecast(customer_id: str, keywords: list, daily_budget: float, date_range_days: int = 30) -> dict:
    """[RESEARCH] Estima alcance para um conjunto de keywords e orçamento. Use keyword_forecast para métricas detalhadas."""
    return logic.get_reach_forecast(customer_id, keywords, daily_budget, date_range_days)


@mcp.tool()
def get_billing_info(customer_id: str) -> dict:
    """[UTILITY] Retorna informações de faturamento: método de pagamento, status e configuração de billing."""
    return logic.get_billing_info(customer_id)


@mcp.tool()
def list_invoices(customer_id: str, year: int = None, month: int = None) -> dict:
    """[UTILITY] Lista faturas da conta. Padrão: mês atual. Informe year e month para períodos específicos."""
    return logic.list_invoices(customer_id, year, month)


@mcp.tool()
def upload_customer_match(customer_id: str, list_name: str, emails: list, membership_life_span: int = 30) -> dict:
    """[CREATE] Cria audiência Customer Match a partir de lista de emails (hashed SHA256) para remarketing."""
    return logic.upload_customer_match(customer_id, list_name, emails, membership_life_span)


@mcp.tool()
def create_audience(customer_id: str, name: str, description: str = "", dimensions: list = None) -> dict:
    """[CREATE] Cria audiência personalizada combinando sinais de interesse e comportamento."""
    return logic.create_audience(customer_id, name, description, dimensions)


@mcp.tool()
def set_campaign_targeting_setting(customer_id: str, campaign_id: str, targeting_dimension: str, bid_only: bool = True) -> dict:
    """[MUTATION] Configura targeting dimension: bid_only=True (observação) ou False (segmentação). targeting_dimension: AUDIENCE|PLACEMENT|TOPIC."""
    return logic.set_campaign_targeting_setting(customer_id, campaign_id, targeting_dimension, bid_only)


@mcp.tool()
def set_ad_group_targeting_setting(customer_id: str, ad_group_id: str, targeting_dimension: str, bid_only: bool = True) -> dict:
    """[MUTATION] Configura targeting dimension no grupo de anúncios: bid_only=True (observação) ou False (segmentação). targeting_dimension: AUDIENCE|PLACEMENT|TOPIC."""
    return logic.set_ad_group_targeting_setting(customer_id, ad_group_id, targeting_dimension, bid_only)


# ─────────────────────────────────────────────
# PERFORMANCE MAX (PMAX) 360° TOOLS
# ─────────────────────────────────────────────

@mcp.tool()
def add_pmax_search_themes(customer_id: str, asset_group_id: str, search_themes: list[str]) -> dict:
    """[MUTATION] Injeta temas de pesquisa (Search Themes) em um Asset Group de Performance Max (até 25 temas)."""
    return logic.add_pmax_search_themes(customer_id, asset_group_id, search_themes)


@mcp.tool()
def link_audience_signal_to_pmax(customer_id: str, asset_group_id: str, audience_id: str) -> dict:
    """[MUTATION] Vincula uma audiência (sinal de público) ao Asset Group de Performance Max."""
    return logic.link_audience_signal_to_pmax(customer_id, asset_group_id, audience_id)


@mcp.tool()
def bind_pmax_text_assets(
    customer_id: str,
    asset_group_id: str,
    headlines: list[str] = None,
    long_headlines: list[str] = None,
    descriptions: list[str] = None,
    business_name: str = None
) -> dict:
    """[MUTATION] Cria e vincula textos (Headlines, Long Headlines, Descriptions e Business Name) ao Asset Group de PMax."""
    return logic.bind_pmax_text_assets(customer_id, asset_group_id, headlines, long_headlines, descriptions, business_name)


@mcp.tool()
def list_pmax_signals(customer_id: str, asset_group_id: str) -> dict:
    """[REPORT] Lista todos os sinais (Search Themes e Audiências) configurados em um Asset Group de Performance Max."""
    return logic.list_pmax_signals(customer_id, asset_group_id)


# ─────────────────────────────────────────────
# ENHANCED CONVERSIONS FOR LEADS (CLOSED-LOOP)
# ─────────────────────────────────────────────

@mcp.tool()
def upload_lead_conversion_enhanced(
    customer_id: str,
    conversion_action_id: str,
    conversion_value: float,
    conversion_date_time: str = None,
    email: str = None,
    phone: str = None,
    order_id: str = None,
    gclid: str = None,
    currency_code: str = "BRL"
) -> dict:
    """[MUTATION] Dispara conversão otimizada para leads (Enhanced Conversions for Leads) com hash SHA-256 automático. Atribui receita real e fechamentos offline."""
    return logic.upload_lead_conversion_enhanced(
        customer_id=customer_id,
        conversion_action_id=conversion_action_id,
        conversion_value=conversion_value,
        conversion_date_time=conversion_date_time,
        email=email,
        phone=phone,
        order_id=order_id,
        gclid=gclid,
        currency_code=currency_code
    )


@mcp.tool()
def batch_upload_lead_conversions_enhanced(
    customer_id: str,
    conversions: list
) -> dict:
    """[MUTATION] Dispara lote de conversões otimizadas para leads (Enhanced Conversions for Leads) com hash SHA-256 automático."""
    return logic.batch_upload_lead_conversions_enhanced(customer_id=customer_id, conversions=conversions)


# ─────────────────────────────────────────────
# ENTRYPOINT
# ─────────────────────────────────────────────

if __name__ == "__main__":
    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    port = int(os.environ.get("MCP_PORT", "8765"))

    if transport == "sse":
        mcp.settings.port = port
        mcp.run(transport="sse")
    else:
        mcp.run()
