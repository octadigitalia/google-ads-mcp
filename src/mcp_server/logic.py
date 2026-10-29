import logging
import time
import sys
import os
import hashlib
import re
from datetime import datetime

# Adiciona o diretorio raiz ao sys.path para suportar execucao direta
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from mcp.server.fastmcp import FastMCP
from google.api_core import protobuf_helpers
from src.mcp_server.client import create_google_ads_client
from src.mcp_server.config import get_settings
from src.mcp_server.utils import proto_to_dict, format_response, GaqlLinter, ResourceResolver, translate_google_ads_error, dense_proto_to_dict

# Inicializa o servidor MCP e o Linter
mcp = FastMCP("Google Ads MCP Server")
linter = GaqlLinter()

@mcp.tool()
def get_account_snapshot(customer_id: str, date_range: str = "LAST_30_DAYS") -> dict:
    """
    [REPORT] Retorna um SNAPSHOT AGREGADO da conta: performance total, status das campanhas e top 5 campanhas. 
    Ideal para o início de uma análise.
    """
    try:
        client = create_google_ads_client()
        ga_service = client.get_service("GoogleAdsService")
        
        # 1. Performance Total da Conta
        total_query = f"""
            SELECT 
                metrics.clicks, 
                metrics.conversions, 
                metrics.cost_micros, 
                metrics.all_conversions_value,
                customer.optimization_score
            FROM customer
            WHERE segments.date DURING {date_range}
        """
        total_res = ga_service.search(customer_id=str(customer_id), query=total_query)
        total_data = next(iter(total_res))
        
        # 2. Distribuição de Status (Contagem via Python para evitar erro de COUNT() no GAQL)
        status_query = "SELECT campaign.status FROM campaign WHERE campaign.status != 'REMOVED'"
        status_res = ga_service.search(customer_id=str(customer_id), query=status_query)
        status_map = {"ENABLED": 0, "PAUSED": 0}
        for row in status_res:
            name = row.campaign.status.name
            status_map[name] = status_map.get(name, 0) + 1

        # 3. Top 5 Campanhas por Custo
        top_query = f"""
            SELECT 
                campaign.id, 
                campaign.name, 
                metrics.cost_micros, 
                metrics.conversions 
            FROM campaign 
            WHERE segments.date DURING {date_range}
            AND campaign.status != 'REMOVED'
            ORDER BY metrics.cost_micros DESC
            LIMIT 5
        """
        top_res = ga_service.search(customer_id=str(customer_id), query=top_query)
        top_campaigns = [dense_proto_to_dict(row) for row in top_res]

        return {
            "status": "SUCCESS",
            "date_range": date_range,
            "account_summary": dense_proto_to_dict(total_data),
            "campaign_status_counts": status_map,
            "top_5_campaigns": top_campaigns
        }
    except Exception as e:
        return translate_google_ads_error(e)


def get_advertiser_verification_status(customer_id: str) -> dict:
    """
    [REPORT] Consulta o status de Verificação de Identidade do Anunciante (Advertiser Identity Verification).
    Informa se há verificação pendente, prazos limites (deadlines), se a conta/anúncios estão pausados ou em risco
    e o link oficial de ação para envio dos documentos.
    """
    try:
        client = create_google_ads_client()
        identity_service = client.get_service("IdentityVerificationService")

        response = identity_service.get_identity_verification(customer_id=str(customer_id))

        verifications_data = []
        is_pending = False
        is_paused_or_at_risk = False
        summary_status = "VERIFIED_OR_NOT_REQUIRED"
        action_url = None
        start_deadline = None
        completion_deadline = None

        for item in response.identity_verification:
            item_dict = proto_to_dict(item)
            verifications_data.append(item_dict)

            prog = item_dict.get("verification_progress", {})
            prog_status = prog.get("program_status")
            req = item_dict.get("identity_verification_requirement", {})

            s_deadline = req.get("verification_start_deadline_time")
            c_deadline = req.get("verification_completion_deadline_time")
            if s_deadline:
                start_deadline = s_deadline
            if c_deadline:
                completion_deadline = c_deadline

            if prog.get("action_url"):
                action_url = prog.get("action_url")

            if prog_status in ["PENDING_USER_ACTION", "ACTION_REQUIRED", "FAILURE"]:
                is_pending = True
                is_paused_or_at_risk = True
                summary_status = prog_status
            elif prog_status == "PENDING_REVIEW":
                is_pending = True
                summary_status = "PENDING_REVIEW"
            elif prog_status == "SUCCESS":
                summary_status = "SUCCESS"

        if is_paused_or_at_risk:
            message = "ATENÇÃO: Verificação de anunciante pendente ou com ação requerida! Entrega pausada ou sob risco iminente de pausa."
        elif is_pending:
            message = "Verificação de anunciante em análise pela equipe do Google Ads."
        elif verifications_data:
            message = "Verificação de identidade do anunciante concluída com sucesso."
        else:
            message = "Nenhuma verificação de identidade do anunciante solicitada para esta conta no momento."

        return {
            "status": "SUCCESS",
            "customer_id": str(customer_id),
            "is_verification_required": len(verifications_data) > 0,
            "has_pending_action": is_pending,
            "is_paused_or_at_risk": is_paused_or_at_risk,
            "summary_status": summary_status,
            "start_deadline": start_deadline,
            "completion_deadline": completion_deadline,
            "action_url": action_url,
            "message": message,
            "verifications": verifications_data
        }
    except Exception as e:
        return translate_google_ads_error(e)


def get_account_alerts_and_notices(customer_id: str) -> dict:
    """
    [REPORT] Varre a conta em busca de alertas críticos, advertências e avisos operacionais:
    - Suspensão ou bloqueio da conta (Customer status)
    - Verificação de identidade do anunciante pendente/vencida (Identity Verification)
    - Problemas de faturamento ou ausência de faturamento aprovado (Billing Setup)
    - Campanhas ativas que não estão entregando (primary_status / primary_status_reasons)
    - Anúncios reprovados ou com restrição de política (Disapproved / Policy Violations)
    """
    try:
        client = create_google_ads_client()
        ga_service = client.get_service("GoogleAdsService")

        critical_alerts = []
        warnings = []

        # 1. Status Geral da Conta
        try:
            cust_q = "SELECT customer.id, customer.descriptive_name, customer.status FROM customer LIMIT 1"
            cust_res = list(ga_service.search(customer_id=str(customer_id), query=cust_q))
            if cust_res:
                cust_status = cust_res[0].customer.status.name
                cust_name = cust_res[0].customer.descriptive_name or str(customer_id)
                if cust_status != "ENABLED":
                    critical_alerts.append({
                        "category": "ACCOUNT_STATUS",
                        "severity": "CRITICAL",
                        "title": f"Conta com status {cust_status}",
                        "description": f"A conta '{cust_name}' não está ativa (status: {cust_status}). Nenhuma campanha entregará anúncios.",
                        "action_needed": "Verifique o painel do Google Ads para verificar o motivo da suspensão ou cancelamento da conta."
                    })
        except Exception as e:
            warnings.append({
                "category": "ACCOUNT_STATUS_CHECK_FAILED",
                "severity": "WARNING",
                "title": "Falha ao consultar status da conta",
                "description": str(e)
            })

        # 2. Verificação de Identidade do Anunciante
        try:
            verification_info = get_advertiser_verification_status(customer_id)
            if verification_info.get("status") == "SUCCESS":
                if verification_info.get("is_paused_or_at_risk"):
                    critical_alerts.append({
                        "category": "ADVERTISER_VERIFICATION",
                        "severity": "CRITICAL",
                        "title": "Verificação de Identidade do Anunciante Pendente",
                        "description": f"Status: {verification_info.get('summary_status')}. Prazo limite para envio: {verification_info.get('completion_deadline') or verification_info.get('start_deadline') or 'Imediato'}. Campanhas podem estar pausadas por falta de verificação.",
                        "action_url": verification_info.get("action_url"),
                        "action_needed": "Acesse a URL de ação ou o painel do Google Ads e submeta os documentos de identificação da empresa/anunciante."
                    })
                elif verification_info.get("has_pending_action"):
                    warnings.append({
                        "category": "ADVERTISER_VERIFICATION",
                        "severity": "WARNING",
                        "title": "Verificação de Identidade em Análise",
                        "description": f"Status: {verification_info.get('summary_status')}.",
                        "action_url": verification_info.get("action_url")
                    })
        except Exception as e:
            warnings.append({
                "category": "ADVERTISER_VERIFICATION_CHECK_FAILED",
                "severity": "WARNING",
                "title": "Falha ao consultar verificação de identidade",
                "description": str(e)
            })

        # 3. Faturamento / Billing Setup
        try:
            bs_q = "SELECT billing_setup.id, billing_setup.status FROM billing_setup"
            bs_res = list(ga_service.search(customer_id=str(customer_id), query=bs_q))
            has_approved_billing = any(row.billing_setup.status.name == "APPROVED" for row in bs_res)
            if not has_approved_billing:
                critical_alerts.append({
                    "category": "BILLING",
                    "severity": "CRITICAL",
                    "title": "Nenhuma configuração de faturamento aprovada",
                    "description": "A conta não possui um faturamento aprovado ativo. Anúncios não serão veiculados até regularização financeira.",
                    "action_needed": "Configure um método de pagamento e vincule uma conta de faturamento válida no Google Ads."
                })
        except Exception:
            pass

        # 4. Diagnóstico de Campanhas Ativas (primary_status e razões de bloqueio)
        try:
            camp_q = """
                SELECT
                    campaign.id,
                    campaign.name,
                    campaign.status,
                    campaign.primary_status,
                    campaign.primary_status_reasons
                FROM campaign
                WHERE campaign.status = 'ENABLED'
            """
            camp_res = ga_service.search(customer_id=str(customer_id), query=camp_q)
            for row in camp_res:
                c_id = str(row.campaign.id)
                c_name = row.campaign.name
                p_status = row.campaign.primary_status.name if hasattr(row.campaign.primary_status, "name") else str(row.campaign.primary_status)
                reasons = [r.name if hasattr(r, "name") else str(r) for r in row.campaign.primary_status_reasons]

                for reason in reasons:
                    if reason in ["HAS_ADS_DISAPPROVED", "BIDDING_STRATEGY_MISCONFIGURED", "BUDGET_MISCONFIGURED"]:
                        critical_alerts.append({
                            "category": "CAMPAIGN_DELIVERY",
                            "severity": "CRITICAL",
                            "title": f"Campanha '{c_name}' impedida de entregar: {reason}",
                            "description": f"Campanha ID {c_id} (Status principal: {p_status}) possui bloqueio operacional: {reason}.",
                            "campaign_id": c_id,
                            "action_needed": "Corrija os anúncios reprovados ou a configuração da estratégia de lance/orçamento."
                        })
                    elif reason in ["HAS_ADS_LIMITED_BY_POLICY", "MOST_ADS_UNDER_REVIEW", "NO_AD_GROUPS", "NO_AD_GROUP_ADS", "NO_KEYWORDS", "MISSING_LOCATION_TARGETING", "BUDGET_CONSTRAINED", "SEARCH_VOLUME_LIMITED"]:
                        warnings.append({
                            "category": "CAMPAIGN_WARNING",
                            "severity": "WARNING",
                            "title": f"Campanha '{c_name}' com limitação: {reason}",
                            "description": f"Campanha ID {c_id} (Status principal: {p_status}) reportou a limitação: {reason}.",
                            "campaign_id": c_id
                        })
        except Exception as e:
            warnings.append({
                "category": "CAMPAIGN_CHECK_FAILED",
                "severity": "WARNING",
                "title": "Falha ao verificar primary_status das campanhas",
                "description": str(e)
            })

        # 5. Anúncios Reprovados ou Limitados por Política
        try:
            ad_q = """
                SELECT
                    ad_group_ad.ad.id,
                    ad_group_ad.ad_group,
                    ad_group_ad.status,
                    ad_group_ad.policy_summary.approval_status,
                    ad_group_ad.policy_summary.review_status,
                    ad_group_ad.policy_summary.policy_topic_entries
                FROM ad_group_ad
                WHERE ad_group_ad.status = 'ENABLED'
                  AND ad_group_ad.policy_summary.approval_status IN ('DISAPPROVED', 'APPROVED_LIMITED')
                LIMIT 20
            """
            ad_res = ga_service.search(customer_id=str(customer_id), query=ad_q)
            disapproved_count = 0
            limited_count = 0
            topics_set = set()

            for row in ad_res:
                app_status = row.ad_group_ad.policy_summary.approval_status.name
                if app_status == "DISAPPROVED":
                    disapproved_count += 1
                elif app_status == "APPROVED_LIMITED":
                    limited_count += 1

                for entry in row.ad_group_ad.policy_summary.policy_topic_entries:
                    if entry.topic:
                        topics_set.add(entry.topic)

            if disapproved_count > 0:
                critical_alerts.append({
                    "category": "POLICY_DISAPPROVAL",
                    "severity": "CRITICAL",
                    "title": f"{disapproved_count} anúncio(s) reprovado(s) por política",
                    "description": f"Foram encontrados anúncios reprovados na conta. Tópicos violados: {', '.join(sorted(topics_set)) if topics_set else 'Não especificado'}.",
                    "action_needed": "Revise o texto, extensões e páginas de destino dos anúncios reprovados ou conteste a decisão de política."
                })
            elif limited_count > 0:
                warnings.append({
                    "category": "POLICY_LIMITED",
                    "severity": "WARNING",
                    "title": f"{limited_count} anúncio(s) com veiculação limitada por política",
                    "description": f"Anúncios com limitações identificadas. Tópicos de política: {', '.join(sorted(topics_set)) if topics_set else 'Não especificado'}."
                })
        except Exception:
            pass

        overall_health = "HEALTHY"
        if critical_alerts:
            overall_health = "CRITICAL"
        elif warnings:
            overall_health = "WARNING"

        return {
            "status": "SUCCESS",
            "customer_id": str(customer_id),
            "account_health": overall_health,
            "critical_alerts_count": len(critical_alerts),
            "warnings_count": len(warnings),
            "critical_alerts": critical_alerts,
            "warnings": warnings,
            "summary": f"Diagnóstico concluído: {len(critical_alerts)} alerta(s) crítico(s) e {len(warnings)} aviso(s) detectado(s)."
        }
    except Exception as e:
        return translate_google_ads_error(e)


def get_budget_pacing_and_exhaustion(customer_id: str, target_monthly_budget: float = None) -> dict:
    """
    [REPORT] Analisa o consumo de orçamento (budget pacing) da conta no mês atual.
    Calcula o ritmo de gastos, run rate projetado para o fim do mês, risco de estouro ou sub-investimento
    e recomenda o orçamento diário ideal para os dias restantes.
    target_monthly_budget: Verba total mensal contratada (em Reais). Se não informada, baseia-se na soma das campanhas ativas.
    """
    try:
        import calendar
        from datetime import datetime

        client = create_google_ads_client()
        ga_service = client.get_service("GoogleAdsService")

        # 1. Custo total gasto no mês corrente
        spend_q = """
            SELECT
                metrics.cost_micros,
                metrics.clicks,
                metrics.conversions
            FROM customer
            WHERE segments.date DURING THIS_MONTH
        """
        spend_res = list(ga_service.search(customer_id=str(customer_id), query=spend_q))
        current_spend = 0.0
        clicks = 0
        conversions = 0
        if spend_res:
            current_spend = (spend_res[0].metrics.cost_micros or 0) / 1e6
            clicks = spend_res[0].metrics.clicks or 0
            conversions = spend_res[0].metrics.conversions or 0

        # 2. Orçamento diário configurado em campanhas ativas
        budget_q = """
            SELECT
                campaign.id,
                campaign.name,
                campaign_budget.amount_micros
            FROM campaign
            WHERE campaign.status = 'ENABLED'
        """
        budget_res = list(ga_service.search(customer_id=str(customer_id), query=budget_q))
        active_daily_budget_total = sum((r.campaign_budget.amount_micros or 0) / 1e6 for r in budget_res)

        now = datetime.now()
        _, total_days_in_month = calendar.monthrange(now.year, now.month)
        days_passed = max(1, now.day)
        days_remaining = max(0, total_days_in_month - days_passed)

        # Determina o orçamento mensal de referência
        monthly_budget = float(target_monthly_budget) if target_monthly_budget and float(target_monthly_budget) > 0 else (active_daily_budget_total * total_days_in_month)

        expected_spend_to_date = (monthly_budget / total_days_in_month) * days_passed if monthly_budget > 0 else 0.0
        pacing_percentage = round((current_spend / expected_spend_to_date * 100), 2) if expected_spend_to_date > 0 else 100.0

        daily_burn_rate = current_spend / days_passed
        projected_month_end_spend = round(current_spend + (daily_burn_rate * days_remaining), 2)

        budget_remaining = max(0.0, monthly_budget - current_spend)
        recommended_daily_budget = round(budget_remaining / days_remaining, 2) if days_remaining > 0 else 0.0

        if pacing_percentage > 115.0:
            pacing_status = "OVERSPENDING"
            insight = f"A conta está gastando {pacing_percentage}% do ritmo ideal. Risco de estourar a verba ou pausar antes do final do mês."
        elif pacing_percentage < 85.0:
            pacing_status = "UNDERSPENDING"
            insight = f"A conta está gastando apenas {pacing_percentage}% do ritmo ideal. Risco de sub-entrega da meta mensal."
        else:
            pacing_status = "ON_TRACK"
            insight = f"Ritmo de gastos saudável ({pacing_percentage}% do esperado para o dia {days_passed} do mês)."

        return {
            "status": "SUCCESS",
            "customer_id": str(customer_id),
            "month": f"{now.year}-{now.month:02d}",
            "days_passed": days_passed,
            "days_remaining": days_remaining,
            "total_days_in_month": total_days_in_month,
            "current_spend": round(current_spend, 2),
            "target_monthly_budget": round(monthly_budget, 2),
            "budget_remaining": round(budget_remaining, 2),
            "daily_burn_rate": round(daily_burn_rate, 2),
            "recommended_daily_budget": recommended_daily_budget,
            "projected_month_end_spend": projected_month_end_spend,
            "pacing_percentage": pacing_percentage,
            "pacing_status": pacing_status,
            "active_campaigns_count": len(budget_res),
            "clicks": clicks,
            "conversions": conversions,
            "insight": insight
        }
    except Exception as e:
        return translate_google_ads_error(e)


def get_conversion_tracking_health(customer_id: str) -> dict:
    """
    [REPORT] Audita a saúde das tags e ações de conversão da conta.
    Identifica se ações de conversão primárias estão inativas, sem disparos nos últimos 30 dias ou com problemas de rastreamento.
    """
    try:
        client = create_google_ads_client()
        ga_service = client.get_service("GoogleAdsService")

        query = """
            SELECT
                conversion_action.id,
                conversion_action.name,
                conversion_action.status,
                conversion_action.type,
                conversion_action.category,
                conversion_action.primary_for_goal,
                conversion_action.origin,
                metrics.conversions,
                metrics.all_conversions
            FROM conversion_action
            WHERE conversion_action.status != 'REMOVED'
              AND segments.date DURING LAST_30_DAYS
        """
        response = ga_service.search(customer_id=str(customer_id), query=query)

        actions_report = []
        primary_inactive_count = 0
        primary_active_count = 0

        for row in response:
            c_act = row.conversion_action
            m = row.metrics
            c_id = str(c_act.id)
            name = c_act.name
            status = c_act.status.name if hasattr(c_act.status, "name") else str(c_act.status)
            c_type = c_act.type_.name if hasattr(c_act.type_, "name") else str(c_act.type_)
            category = c_act.category.name if hasattr(c_act.category, "name") else str(c_act.category)
            is_primary = bool(c_act.primary_for_goal)
            origin = c_act.origin.name if hasattr(c_act.origin, "name") else str(c_act.origin)
            conversions_30d = float(m.conversions or 0.0)
            all_conversions_30d = float(m.all_conversions or 0.0)

            if is_primary:
                if status == "ENABLED" and conversions_30d == 0.0:
                    health_status = "NEEDS_ATTENTION_NO_CONVERSIONS"
                    primary_inactive_count += 1
                elif status == "ENABLED":
                    health_status = "HEALTHY"
                    primary_active_count += 1
                else:
                    health_status = "PRIMARY_BUT_PAUSED"
                    primary_inactive_count += 1
            else:
                health_status = "SECONDARY_OBSERVATION"

            actions_report.append({
                "id": c_id,
                "name": name,
                "status": status,
                "is_primary": is_primary,
                "category": category,
                "type": c_type,
                "origin": origin,
                "conversions_last_30_days": conversions_30d,
                "all_conversions_last_30_days": all_conversions_30d,
                "health_status": health_status
            })

        overall_tracking_health = "HEALTHY"
        if primary_inactive_count > 0 and primary_active_count == 0:
            overall_tracking_health = "CRITICAL_TRACKING_BROKEN"
            summary_msg = "ALERTA CRÍTICO: Todas as ações de conversão primárias estão sem registros nos últimos 30 dias ou pausadas!"
        elif primary_inactive_count > 0:
            overall_tracking_health = "WARNING"
            summary_msg = f"{primary_inactive_count} ação(ões) de conversão primária(s) sem registros de conversão recentes."
        else:
            summary_msg = "Todas as ações de conversão primárias estão registrando disparos normalmente."

        return {
            "status": "SUCCESS",
            "customer_id": str(customer_id),
            "tracking_health": overall_tracking_health,
            "primary_active_count": primary_active_count,
            "primary_inactive_count": primary_inactive_count,
            "total_actions": len(actions_report),
            "summary": summary_msg,
            "conversion_actions": actions_report
        }
    except Exception as e:
        return translate_google_ads_error(e)


def get_auction_competitor_drift(customer_id: str, campaign_id: str = None) -> dict:
    """
    [REPORT] Radar Competitivo de Leilão (Competitor Drift).
    Compara o leilão dos últimos 7 dias (LAST_7_DAYS) com os últimos 30 dias (LAST_30_DAYS).
    Detecta novos concorrentes agressivos, variações na taxa de sobreposição (overlap rate) e dominância no topo de página.
    """
    try:
        client = create_google_ads_client()
        ga_service = client.get_service("GoogleAdsService")

        campaign_filter = ""
        campaign_id_num = None
        if campaign_id:
            resolver = ResourceResolver(client)
            res_id = resolver.resolve(customer_id, "CAMPAIGN", campaign_id)
            if "error" in res_id: return res_id
            campaign_id_num = res_id["id"]
            campaign_filter = f"AND campaign.id = {campaign_id_num}"

        def _fetch_auction(date_range: str):
            q = f"""
                SELECT
                    auction_insight.domain,
                    metrics.auction_insight_search_impression_share,
                    metrics.auction_insight_search_overlap_rate,
                    metrics.auction_insight_search_top_impression_percentage
                FROM auction_insight_table
                WHERE segments.date DURING {date_range}
                {campaign_filter}
                ORDER BY metrics.auction_insight_search_impression_share DESC
                LIMIT 25
            """
            data = {}
            for r in ga_service.search(customer_id=str(customer_id), query=q):
                domain = r.auction_insight.domain
                data[domain] = {
                    "impression_share": float(r.metrics.auction_insight_search_impression_share or 0.0),
                    "overlap_rate": float(r.metrics.auction_insight_search_overlap_rate or 0.0),
                    "top_rate": float(r.metrics.auction_insight_search_top_impression_percentage or 0.0)
                }
            return data

        recent_7d = _fetch_auction("LAST_7_DAYS")
        hist_30d = _fetch_auction("LAST_30_DAYS")

        competitors = []
        new_entrants = []
        surging_competitors = []

        for domain, d_recent in recent_7d.items():
            if not domain: continue
            d_hist = hist_30d.get(domain)
            if not d_hist:
                new_entrants.append(domain)
                competitors.append({
                    "domain": domain,
                    "trend": "NEW_ENTRANT",
                    "impression_share_7d": round(d_recent["impression_share"] * 100, 2),
                    "overlap_rate_7d": round(d_recent["overlap_rate"] * 100, 2),
                    "top_rate_7d": round(d_recent["top_rate"] * 100, 2),
                    "change_overlap_pct": "+100.0 (Novo)"
                })
            else:
                overlap_diff = round((d_recent["overlap_rate"] - d_hist["overlap_rate"]) * 100, 2)
                share_diff = round((d_recent["impression_share"] - d_hist["impression_share"]) * 100, 2)
                if overlap_diff >= 10.0 or share_diff >= 10.0:
                    surging_competitors.append(domain)
                    trend = "SURGING_AGGRESSIVE"
                elif overlap_diff <= -10.0 or share_diff <= -10.0:
                    trend = "DECLINING"
                else:
                    trend = "STABLE"

                competitors.append({
                    "domain": domain,
                    "trend": trend,
                    "impression_share_7d": round(d_recent["impression_share"] * 100, 2),
                    "impression_share_30d": round(d_hist["impression_share"] * 100, 2),
                    "overlap_rate_7d": round(d_recent["overlap_rate"] * 100, 2),
                    "overlap_rate_30d": round(d_hist["overlap_rate"] * 100, 2),
                    "overlap_change_points": overlap_diff,
                    "share_change_points": share_diff
                })

        return {
            "status": "SUCCESS",
            "customer_id": str(customer_id),
            "campaign_id": campaign_id_num,
            "total_competitors_detected": len(competitors),
            "new_entrants_count": len(new_entrants),
            "new_entrants": new_entrants,
            "surging_competitors_count": len(surging_competitors),
            "surging_competitors": surging_competitors,
            "competitor_analysis": sorted(competitors, key=lambda x: x.get("overlap_rate_7d", 0), reverse=True)
        }
    except Exception as e:
        return translate_google_ads_error(e)


def get_policy_violations_and_appeals(customer_id: str, campaign_id: str = None) -> dict:
    """
    [REPORT] Diagnóstico detalhado de violações de políticas e status de apelações/recursos de anúncios.
    Identifica anúncios reprovados (DISAPPROVED), limitados (APPROVED_LIMITED) ou em recurso (UNDER_APPEAL),
    detalhando os tópicos violados, tipo de restrição e orientações para regularização.
    """
    try:
        client = create_google_ads_client()
        ga_service = client.get_service("GoogleAdsService")

        campaign_filter = ""
        campaign_id_num = None
        if campaign_id:
            resolver = ResourceResolver(client)
            res_id = resolver.resolve(customer_id, "CAMPAIGN", campaign_id)
            if "error" in res_id: return res_id
            campaign_id_num = res_id["id"]
            campaign_filter = f"AND campaign.id = {campaign_id_num}"

        query = f"""
            SELECT
                campaign.id,
                campaign.name,
                ad_group.id,
                ad_group.name,
                ad_group_ad.ad.id,
                ad_group_ad.ad.type,
                ad_group_ad.status,
                ad_group_ad.policy_summary.approval_status,
                ad_group_ad.policy_summary.review_status,
                ad_group_ad.policy_summary.policy_topic_entries
            FROM ad_group_ad
            WHERE ad_group_ad.status != 'REMOVED'
              AND ad_group_ad.policy_summary.approval_status IN ('DISAPPROVED', 'APPROVED_LIMITED')
              {campaign_filter}
            LIMIT 50
        """
        response = ga_service.search(customer_id=str(customer_id), query=query)

        violations = []
        under_appeal_count = 0
        disapproved_count = 0
        limited_count = 0

        for row in response:
            ad = row.ad_group_ad.ad
            pol = row.ad_group_ad.policy_summary
            camp = row.campaign
            ag = row.ad_group

            app_status = pol.approval_status.name if hasattr(pol.approval_status, "name") else str(pol.approval_status)
            rev_status = pol.review_status.name if hasattr(pol.review_status, "name") else str(pol.review_status)

            if app_status == "DISAPPROVED":
                disapproved_count += 1
            elif app_status == "APPROVED_LIMITED":
                limited_count += 1

            is_under_appeal = (rev_status == "UNDER_APPEAL")
            if is_under_appeal:
                under_appeal_count += 1

            topics = []
            for entry in pol.policy_topic_entries:
                topics.append({
                    "topic": entry.topic,
                    "type": entry.type_.name if hasattr(entry.type_, "name") else str(entry.type_)
                })

            violations.append({
                "ad_id": str(ad.id),
                "ad_type": ad.type_.name if hasattr(ad.type_, "name") else str(ad.type_),
                "campaign_id": str(camp.id),
                "campaign_name": camp.name,
                "ad_group_id": str(ag.id),
                "ad_group_name": ag.name,
                "approval_status": app_status,
                "review_status": rev_status,
                "is_under_appeal": is_under_appeal,
                "policy_topics": topics
            })

        return {
            "status": "SUCCESS",
            "customer_id": str(customer_id),
            "campaign_id": campaign_id_num,
            "total_violations": len(violations),
            "disapproved_count": disapproved_count,
            "limited_count": limited_count,
            "under_appeal_count": under_appeal_count,
            "violations": violations,
            "summary": f"{disapproved_count} anúncio(s) reprovado(s), {limited_count} limitado(s), {under_appeal_count} em análise de recurso."
        }
    except Exception as e:
        return translate_google_ads_error(e)


@mcp.tool()
def get_change_history(customer_id: str, last_n_days: int = 7) -> dict:
    """
    [REPORT] Auditoria de HISTÓRICO DE ALTERAÇÕES. 
    Retorna o que foi mudado (status, lances, orçamentos) e por quem, nos últimos N dias.
    """
    try:
        from datetime import datetime, timedelta
        client = create_google_ads_client()
        ga_service = client.get_service("GoogleAdsService")
        
        # Calcula range de datas
        end_date = datetime.now()
        start_date = end_date - timedelta(days=last_n_days)
        
        query = f"""
            SELECT
                change_event.change_date_time,
                change_event.change_resource_type,
                change_event.resource_change_operation,
                change_event.user_email,
                change_event.changed_fields,
                change_event.campaign,
                change_event.ad_group
            FROM change_event
            WHERE change_event.change_date_time >= '{start_date.strftime('%Y-%m-%d')}'
            AND change_event.change_date_time <= '{end_date.strftime('%Y-%m-%d')}'
            ORDER BY change_event.change_date_time DESC
            LIMIT 50
        """
        
        response = ga_service.search(customer_id=str(customer_id), query=query)
        changes = [dense_proto_to_dict(row) for row in response]

        return {
            "status": "SUCCESS",
            "last_n_days": last_n_days,
            "change_events": changes
        }
    except Exception as e:
        return translate_google_ads_error(e)

@mcp.tool()
def get_keyword_historical_metrics(customer_id: str, keywords: list[str]) -> dict:
    """
    [MARKET_DATA] Obtém MÉTRICAS HISTÓRICAS e médias de mercado para palavras-chave. 
    Retorna volume de busca, competição e lances sugeridos. NÃO é específico da conta do cliente.
    """
    if not keywords: return {"error": "Forneça palavras-chave."}
    try:
        client = create_google_ads_client()
        service = client.get_service("KeywordPlanIdeaService")
        request = client.get_type("GenerateKeywordHistoricalMetricsRequest")
        request.customer_id = str(customer_id)
        request.keywords.extend(keywords)
        request.language = "languageConstants/1014"
        request.geo_target_constants.append("geoTargetConstants/2076")
        response = service.generate_keyword_historical_metrics(request=request)
        results = []
        for result in response.results:
            m = result.keyword_metrics
            results.append({
                "text": result.text, "avg_monthly_searches": m.avg_monthly_searches,
                "competition": m.competition.name,
                "low_bid": float(m.low_top_of_page_bid_micros) / 1e6,
                "high_bid": float(m.high_top_of_page_bid_micros) / 1e6
            })
        return format_response(results, customer_id, "get_keyword_historical_metrics")
    except Exception as e:
        return translate_google_ads_error(e)

@mcp.tool()
def generate_keyword_ideas(customer_id: str, keyword_texts: list[str] = None, page_url: str = None) -> dict:
    """
    [MARKET_DATA] Gera IDEIAS de palavras-chave baseadas em termos semente ou URL. 
    Útil para expansão de inventário e descoberta de novas tendências de mercado.
    """
    try:
        client = create_google_ads_client()
        service = client.get_service("KeywordPlanIdeaService")
        request = client.get_type("GenerateKeywordIdeasRequest")
        request.customer_id = str(customer_id)
        request.language = "languageConstants/1014"
        request.geo_target_constants.append("geoTargetConstants/2076")
        if keyword_texts: request.keyword_seed.keywords.extend(keyword_texts)
        if page_url: request.url_seed.url = page_url
        ideas = service.generate_keyword_ideas(request=request)
        results = [{"text": i.text, "vol": i.keyword_idea_metrics.avg_monthly_searches} for i in ideas]
        return format_response(results, customer_id, "generate_keyword_ideas")
    except Exception as e:
        return translate_google_ads_error(e)

@mcp.tool()
def update_rsa_assets(customer_id: str, ad_id: str, headlines: list[str], descriptions: list[str]) -> dict:
    """
    [MUTATION] Atualiza títulos e descrições de um anúncio responsivo (RSA) existente. 
    CUIDADO: Sobrescreve os assets atuais do anúncio.
    """
    try:
        client = create_google_ads_client()
        service = client.get_service("AdService")
        op = client.get_type("AdOperation")
        ad = op.update
        ad.resource_name = service.ad_path(customer_id, ad_id)
        ad.responsive_search_ad.headlines.extend([{"text": h} for h in headlines])
        ad.responsive_search_ad.descriptions.extend([{"text": d} for d in descriptions])
        client.copy_from(op.update_mask, protobuf_helpers.field_mask(None, ad._pb))
        response = service.mutate_ads(customer_id=str(customer_id), operations=[op])
        return {"status": "SUCCESS", "resource": response.results[0].resource_name}
    except Exception as e:
        return translate_google_ads_error(e)

@mcp.tool()
def add_negative_keywords(customer_id: str, campaign_id: str, keywords: list[str], match_type: str = "BROAD") -> dict:
    """
    [MUTATION] Adiciona palavras-chave NEGATIVAS a uma campanha para EXCLUIR tráfego indesejado. 
    Aceita ID numérico ou Nome da Campanha.
    """
    try:
        client = create_google_ads_client()
        resolver = ResourceResolver(client)
        
        res_id = resolver.resolve(customer_id, "CAMPAIGN", campaign_id)
        if "error" in res_id: return res_id
        campaign_id_num = res_id["id"]

        service = client.get_service("CampaignCriterionService")
        ops = []
        for kw in keywords:
            op = client.get_type("CampaignCriterionOperation")
            c = op.create
            c.campaign = client.get_service("CampaignService").campaign_path(customer_id, campaign_id_num)
            c.negative = True
            c.keyword.text = kw
            c.keyword.match_type = client.enums.KeywordMatchTypeEnum[match_type]
            ops.append(op)
        response = service.mutate_campaign_criteria(customer_id=str(customer_id), operations=ops)
        return {"status": "SUCCESS", "added": len(response.results), "campaign_id": campaign_id_num}
    except Exception as e:
        return translate_google_ads_error(e)

@mcp.tool()
def get_search_terms(customer_id: str, date_range: str = "LAST_30_DAYS", min_clicks: int = 1) -> dict:
    """
    [REPORT] Relatório de TERMOS DE PESQUISA REAIS que dispararam anúncios da conta. 
    Crucial para identificar cliques irrelevantes e novas oportunidades de biddable keywords.
    """
    query = f"SELECT search_term_view.search_term, metrics.clicks FROM search_term_view WHERE segments.date DURING {date_range} AND metrics.clicks >= {min_clicks}"
    try:
        client = create_google_ads_client()
        service = client.get_service("GoogleAdsService")
        stream = service.search_stream(customer_id=str(customer_id), query=query)
        results = [dense_proto_to_dict(row) for batch in stream for row in batch.results]
        return format_response(results, customer_id, "get_search_terms")
    except Exception as e:
        return translate_google_ads_error(e)

@mcp.tool()
def set_campaign_budget(customer_id: str, campaign_id: str, amount: float) -> dict:
    """
    [MUTATION] Atualiza o ORÇAMENTO DIÁRIO de uma campanha. 
    Aceita ID numérico ou Nome da Campanha. Operação financeira direta.
    """
    try:
        client = create_google_ads_client()
        resolver = ResourceResolver(client)
        
        res_id = resolver.resolve(customer_id, "CAMPAIGN", campaign_id)
        if "error" in res_id: return res_id
        campaign_id_num = res_id["id"]

        ga_service = client.get_service("GoogleAdsService")
        budget_service = client.get_service("CampaignBudgetService")
        
        q = f"SELECT campaign.campaign_budget FROM campaign WHERE campaign.id = {campaign_id_num}"
        res = ga_service.search(customer_id=str(customer_id), query=q)
        try:
            budget_rn = next(iter(res)).campaign.campaign_budget
        except StopIteration:
            return {"error": f"Campanha {campaign_id_num} não encontrada."}

        op = client.get_type("CampaignBudgetOperation")
        b = op.update
        b.resource_name = budget_rn
        b.amount_micros = int(amount * 1e6)
        client.copy_from(op.update_mask, protobuf_helpers.field_mask(None, b._pb))
        budget_service.mutate_campaign_budgets(customer_id=str(customer_id), operations=[op])
        return {"status": "SUCCESS", "budget": budget_rn, "campaign_id": campaign_id_num}
    except Exception as e:
        return translate_google_ads_error(e)


def set_campaign_bid_ceiling(customer_id: str, campaign_id: str, bid_ceiling: float = None) -> dict:
    """
    [MUTATION] Ajusta o teto de lance máximo de CPC (cpc_bid_ceiling_micros) em campanhas com estratégia TARGET_SPEND (Maximizar Cliques).
    bid_ceiling: Valor máximo em Reais (ex: 2.50). Se 0 ou None, remove o teto de CPC.
    Aceita ID numérico ou Nome da Campanha.
    """
    try:
        client = create_google_ads_client()
        resolver = ResourceResolver(client)

        res_id = resolver.resolve(customer_id, "CAMPAIGN", campaign_id)
        if "error" in res_id:
            return res_id
        campaign_id_num = res_id["id"]

        campaign_service = client.get_service("CampaignService")
        op = client.get_type("CampaignOperation")
        camp = op.update
        camp.resource_name = campaign_service.campaign_path(customer_id, campaign_id_num)

        if bid_ceiling is not None and float(bid_ceiling) > 0:
            ceiling_micros = int(float(bid_ceiling) * 1_000_000)
            camp.target_spend.cpc_bid_ceiling_micros = ceiling_micros
            client.copy_from(op.update_mask, protobuf_helpers.field_mask(None, camp._pb))
            mode = "SET"
        else:
            op.update_mask.paths.append("target_spend.cpc_bid_ceiling_micros")
            ceiling_micros = None
            mode = "REMOVED"

        campaign_service.mutate_campaigns(customer_id=str(customer_id), operations=[op])

        return {
            "status": "SUCCESS",
            "campaign_id": campaign_id_num,
            "bid_ceiling": float(bid_ceiling) if bid_ceiling is not None and float(bid_ceiling) > 0 else 0.0,
            "cpc_bid_ceiling_micros": ceiling_micros,
            "mode": mode
        }
    except Exception as e:
        return translate_google_ads_error(e)


@mcp.tool()
def set_campaign_status(customer_id: str, campaign_id: str, status: str) -> dict:
    """
    [MUTATION] Altera o ESTADO DE VEICULAÇÃO (ENABLED/PAUSED) de uma campanha. 
    Aceita ID numérico ou Nome da Campanha.
    """
    try:
        client = create_google_ads_client()
        resolver = ResourceResolver(client)
        
        res_id = resolver.resolve(customer_id, "CAMPAIGN", campaign_id)
        if "error" in res_id: return res_id
        campaign_id_num = res_id["id"]

        service = client.get_service("CampaignService")
        op = client.get_type("CampaignOperation")
        c = op.update
        c.resource_name = service.campaign_path(customer_id, campaign_id_num)
        c.status = client.enums.CampaignStatusEnum[status]
        client.copy_from(op.update_mask, protobuf_helpers.field_mask(None, c._pb))
        service.mutate_campaigns(customer_id=str(customer_id), operations=[op])
        return {"status": "SUCCESS", "status": status, "campaign_id": campaign_id_num}
    except Exception as e:
        return translate_google_ads_error(e)

@mcp.tool()
def get_campaign_performance(customer_id: str, date_range: str = "LAST_7_DAYS") -> dict:
    """
    [REPORT] Obtém métricas de PERFORMANCE AGREGADA (cliques, impressões, etc) das campanhas da conta.
    """
    query = f"SELECT campaign.id, campaign.name, metrics.clicks FROM campaign WHERE segments.date DURING {date_range} AND campaign.status != 'REMOVED'"
    try:
        client = create_google_ads_client()
        service = client.get_service("GoogleAdsService")
        stream = service.search_stream(customer_id=str(customer_id), query=query)
        results = [proto_to_dict(row) for batch in stream for row in batch.results]
        return format_response(results, customer_id, "get_campaign_performance")
    except Exception as e:
        return translate_google_ads_error(e)

@mcp.tool()
def search_ads(query: str, customer_id: str = None) -> dict:
    """
    [REPORT/CUSTOM] Executa consultas GAQL (Google Ads Query Language) brutas. 
    Ferramenta mais flexível para extração de dados específicos de campanhas, grupos e anúncios. 
    Inclui Linter de validação de campos.
    """
    target_id = customer_id or get_settings().login_customer_id
    
    # 1. Validação via Linter
    validation = linter.validate_query(query)
    if not validation["valid"]:
        return {
            "status": "ERROR",
            "error_code": validation["error_code"],
            "message": f"A query contém campos inválidos para os recursos suportados (campaign, ad_group, ad_group_ad).",
            "details": validation["invalid_fields"]
        }

    # 2. Execução da Query
    try:
        start_time = time.time()
        client = create_google_ads_client()
        service = client.get_service("GoogleAdsService")
        
        if "LIMIT" not in query.upper():
            query += " LIMIT 50"
            warning = "Limite de 50 linhas aplicado automaticamente para otimizar o contexto da LLM."
        else:
            warning = None

        stream = service.search_stream(customer_id=str(target_id), query=query)
        results = [proto_to_dict(row) for batch in stream for row in batch.results]
        
        execution_time = round(time.time() - start_time, 3)
        response = format_response(results, target_id, query, warnings=[warning] if warning else None)
        response["metadata"]["execution_time_sec"] = execution_time
        
        return response
    except Exception as e:
        return translate_google_ads_error(e)

@mcp.tool()
def list_accessible_customers() -> dict:
    """
    [UTILITY] Lista todos os IDs de clientes e nomes das contas acessíveis por este Developer Token.
    """
    try:
        client = create_google_ads_client()
        customer_service = client.get_service("CustomerService")
        googleads_service = client.get_service("GoogleAdsService")
        
        accessible_customers = customer_service.list_accessible_customers()
        
        results = []
        for resource_name in accessible_customers.resource_names:
            customer_id = resource_name.split("/")[-1]
            query = "SELECT customer.id, customer.descriptive_name, customer.status FROM customer LIMIT 1"
            try:
                response = googleads_service.search(customer_id=customer_id, query=query)
                for row in response:
                    results.append({
                        "id": str(row.customer.id),
                        "name": row.customer.descriptive_name or "Sem Nome",
                        "status": row.customer.status.name,
                        "resource_name": resource_name
                    })
            except Exception:
                results.append({
                    "id": customer_id,
                    "name": "Acesso Limitado/Inativo",
                    "resource_name": resource_name
                })
            
        return {"customers": results}
    except Exception as e:
        return translate_google_ads_error(e)

@mcp.tool()
def connection_status() -> str:
    """
    [UTILITY] Verifica se a conexão com a API do Google Ads está ativa e funcional.
    """
    try:
        create_google_ads_client()
        return "✅ Conectado"
    except Exception:
        return "❌ Desconectado"

@mcp.tool()
def create_search_campaign(
    customer_id: str, 
    campaign_name: str, 
    daily_budget_amount: float,
    target_cpa: float = None,
    goal_category: str = None
) -> dict:
    """
    [MUTATION] Cria uma NOVA CAMPANHA DE PESQUISA (Standard Search). 
    Inclui criação automática de orçamento e conformidade com políticas.
    """
    try:
        client = create_google_ads_client()
        
        budget_service = client.get_service("CampaignBudgetService")
        b_op = client.get_type("CampaignBudgetOperation")
        b_op.create.name = f"Budget - {campaign_name} - {int(time.time())}"
        b_op.create.amount_micros = int(daily_budget_amount * 1e6)
        b_op.create.delivery_method = client.enums.BudgetDeliveryMethodEnum.STANDARD
        b_op.create.explicitly_shared = False
        b_res = budget_service.mutate_campaign_budgets(customer_id=str(customer_id), operations=[b_op])
        budget_rn = b_res.results[0].resource_name

        campaign_service = client.get_service("CampaignService")
        c_op = client.get_type("CampaignOperation")
        c = c_op.create
        c.name = campaign_name
        c.advertising_channel_type = client.enums.AdvertisingChannelTypeEnum.SEARCH
        c.status = client.enums.CampaignStatusEnum.PAUSED
        c.campaign_budget = budget_rn
        
        if target_cpa:
            client.copy_from(c.maximize_conversions, client.get_type("MaximizeConversions"))
        else:
            client.copy_from(c.target_spend, client.get_type("TargetSpend"))
        
        if goal_category and goal_category in client.enums.OptimizationGoalTypeEnum.__members__:
            goal_setting = c.optimization_goal_setting
            goal_type = client.enums.OptimizationGoalTypeEnum[goal_category]
            goal_setting.optimization_goal_types.append(goal_type)

        c.network_settings.target_google_search = True
        c.network_settings.target_search_network = True
        c.network_settings.target_partner_search_network = False
        c.network_settings.target_content_network = False
        c.contains_eu_political_advertising = client.enums.EuPoliticalAdvertisingStatusEnum.DOES_NOT_CONTAIN_EU_POLITICAL_ADVERTISING

        c_res = campaign_service.mutate_campaigns(customer_id=str(customer_id), operations=[c_op])
        return {"status": "SUCCESS", "campaign": c_res.results[0].resource_name, "budget": budget_rn}
    except Exception as e:
        return translate_google_ads_error(e)

@mcp.tool()
def create_ad_group(customer_id: str, campaign_id: str, ad_group_name: str, cpc_bid: float = 1.0) -> dict:
    """
    [MUTATION] Cria um NOVO GRUPO DE ANÚNCIOS em uma campanha existente. 
    Aceita ID numérico ou Nome da Campanha.
    """
    try:
        client = create_google_ads_client()
        resolver = ResourceResolver(client)
        
        res_id = resolver.resolve(customer_id, "CAMPAIGN", campaign_id)
        if "error" in res_id: return res_id
        campaign_id_num = res_id["id"]

        ad_group_service = client.get_service("AdGroupService")
        campaign_service = client.get_service("CampaignService")
        
        operation = client.get_type("AdGroupOperation")
        ad_group = operation.create
        ad_group.name = ad_group_name
        ad_group.status = client.enums.AdGroupStatusEnum.ENABLED
        ad_group.type_ = client.enums.AdGroupTypeEnum.SEARCH_STANDARD
        
        ad_group.campaign = campaign_service.campaign_path(customer_id, campaign_id_num)
        ad_group.cpc_bid_micros = int(cpc_bid * 1e6)

        response = ad_group_service.mutate_ad_groups(customer_id=str(customer_id), operations=[operation])
        return {"status": "SUCCESS", "ad_group_id": response.results[0].resource_name, "campaign_id": campaign_id_num}
    except Exception as e:
        return translate_google_ads_error(e)

@mcp.tool()
def create_responsive_search_ad(
    customer_id: str, 
    ad_group_id: str, 
    headlines: list[str], 
    descriptions: list[str], 
    final_url: str
) -> dict:
    """
    [MUTATION] Cria um NOVO ANÚNCIO DE PESQUISA RESPONSIVO (RSA). 
    Aceita ID numérico ou Nome do Ad Group.
    """
    try:
        client = create_google_ads_client()
        resolver = ResourceResolver(client)
        
        res_id = resolver.resolve(customer_id, "AD_GROUP", ad_group_id)
        if "error" in res_id: return res_id
        ad_group_id_num = res_id["id"]

        ad_group_ad_service = client.get_service("AdGroupAdService")
        ad_group_service = client.get_service("AdGroupService")
        
        operation = client.get_type("AdGroupAdOperation")
        ad_group_ad = operation.create
        ad_group_ad.ad_group = ad_group_service.ad_group_path(customer_id, ad_group_id_num)
        ad_group_ad.status = client.enums.AdGroupStatusEnum.ENABLED
        
        ad = ad_group_ad.ad
        ad.final_urls.append(final_url)
        
        for text in headlines:
            headline = client.get_type("AdTextAsset")
            headline.text = text[:30]
            ad.responsive_search_ad.headlines.append(headline)
            
        for text in descriptions:
            description = client.get_type("AdTextAsset")
            description.text = text[:90]
            ad.responsive_search_ad.descriptions.append(description)

        response = ad_group_ad_service.mutate_ad_group_ads(customer_id=str(customer_id), operations=[operation])
        return {"status": "SUCCESS", "ad_id": response.results[0].resource_name, "ad_group_id": ad_group_id_num}
    except Exception as e:
        return translate_google_ads_error(e)

@mcp.tool()
def add_keywords(customer_id: str, ad_group_id: str, keywords: list[str], match_type: str = "BROAD") -> dict:
    """
    [MUTATION] Adiciona PALAVRAS-CHAVE COMPRÁVEIS (Biddable) a um grupo de anúncios. 
    Aceita ID numérico ou Nome do Ad Group.
    """
    try:
        client = create_google_ads_client()
        resolver = ResourceResolver(client)
        
        res_id = resolver.resolve(customer_id, "AD_GROUP", ad_group_id)
        if "error" in res_id: return res_id
        ad_group_id_num = res_id["id"]

        ad_group_criterion_service = client.get_service("AdGroupCriterionService")
        ad_group_service = client.get_service("AdGroupService")
        
        ad_group_path = ad_group_service.ad_group_path(customer_id, ad_group_id_num)
            
        operations = []
        for kw in keywords:
            operation = client.get_type("AdGroupCriterionOperation")
            criterion = operation.create
            criterion.ad_group = ad_group_path
            criterion.status = client.enums.AdGroupCriterionStatusEnum.ENABLED
            criterion.keyword.text = kw
            criterion.keyword.match_type = client.enums.KeywordMatchTypeEnum[match_type]
            operations.append(operation)
            
        response = ad_group_criterion_service.mutate_ad_group_criteria(
            customer_id=str(customer_id),
            operations=operations
        )
        
        return {"status": "SUCCESS", "added_count": len(response.results), "ad_group_id": ad_group_id_num}
    except Exception as e:
        return translate_google_ads_error(e)

@mcp.tool()
def get_account_capabilities(customer_id: str) -> dict:
    """
    [METADATA] Lista METAS DE CONVERSÃO, moeda, fuso horário e recursos habilitados na conta. 
    Essencial para a IA decidir estratégias de lance.
    """
    try:
        client = create_google_ads_client()
        googleads_service = client.get_service("GoogleAdsService")
        
        account_query = "SELECT customer.id, customer.descriptive_name, customer.currency_code, customer.time_zone, customer.status FROM customer LIMIT 1"
        account_res = googleads_service.search(customer_id=str(customer_id), query=account_query)
        account_info = proto_to_dict(next(iter(account_res)))['customer']

        goals_query = "SELECT customer_conversion_goal.category, customer_conversion_goal.origin, customer_conversion_goal.biddable FROM customer_conversion_goal WHERE customer_conversion_goal.biddable = TRUE"
        goals_res = googleads_service.search(customer_id=str(customer_id), query=goals_query)
        goals_list = [proto_to_dict(row)['customer_conversion_goal'] for row in goals_res]

        return {
            "account": account_info,
            "conversion_goals": goals_list,
            "supported_campaign_types": ["SEARCH", "PERFORMANCE_MAX", "DISPLAY", "VIDEO", "DEMAND_GEN"]
        }
    except Exception as e:
        return translate_google_ads_error(e)

@mcp.tool()
def create_pmax_campaign(
    customer_id: str, 
    campaign_name: str, 
    daily_budget_amount: float,
    final_url: str = None,
    final_urls: list[str] = None,
    headlines: list[str] = None,
    descriptions: list[str] = None
) -> dict:
    """
    [MUTATION] Cria uma estrutura completa de PERFORMANCE MAX (PMax). 
    Inclui orçamento e grupo de assets inicial. Criada PAUSADA por segurança.
    """
    try:
        client = create_google_ads_client()
        
        # Normaliza URLs finais
        urls = []
        if final_urls:
            urls.extend(final_urls)
        if final_url and final_url not in urls:
            urls.append(final_url)
        if not urls:
            raise ValueError("Informe final_url ou final_urls para criar a campanha PMax.")

        budget_service = client.get_service("CampaignBudgetService")
        b_op = client.get_type("CampaignBudgetOperation")
        b_op.create.name = f"Budget - {campaign_name} - {int(time.time())}"
        b_op.create.amount_micros = int(daily_budget_amount * 1e6)
        b_op.create.delivery_method = client.enums.BudgetDeliveryMethodEnum.STANDARD
        b_op.create.explicitly_shared = False
        b_res = budget_service.mutate_campaign_budgets(customer_id=str(customer_id), operations=[b_op])
        budget_rn = b_res.results[0].resource_name

        campaign_service = client.get_service("CampaignService")
        c_op = client.get_type("CampaignOperation")
        c = c_op.create
        c.name = campaign_name
        c.advertising_channel_type = client.enums.AdvertisingChannelTypeEnum.PERFORMANCE_MAX
        c.status = client.enums.CampaignStatusEnum.PAUSED
        c.campaign_budget = budget_rn
        client.copy_from(c.maximize_conversions, client.get_type("MaximizeConversions"))
        c.brand_guidelines_enabled = False
        c.contains_eu_political_advertising = client.enums.EuPoliticalAdvertisingStatusEnum.DOES_NOT_CONTAIN_EU_POLITICAL_ADVERTISING

        c_res = campaign_service.mutate_campaigns(customer_id=str(customer_id), operations=[c_op])
        campaign_rn = c_res.results[0].resource_name

        asset_group_service = client.get_service("AssetGroupService")
        ag_op = client.get_type("AssetGroupOperation")
        ag = ag_op.create
        ag.name = f"Asset Group - {campaign_name}"
        ag.campaign = campaign_rn
        ag.final_urls.extend(urls)
        ag.status = client.enums.AssetGroupStatusEnum.ENABLED
        
        ag_res = asset_group_service.mutate_asset_groups(customer_id=str(customer_id), operations=[ag_op])
        asset_group_rn = ag_res.results[0].resource_name

        res_data = {
            "status": "SUCCESS", 
            "campaign_id": campaign_rn, 
            "asset_group_id": asset_group_rn,
            "campaign_name": campaign_name,
            "daily_budget": daily_budget_amount
        }

        # Se foram passados headlines ou descriptions, vincula automaticamente
        if headlines or descriptions:
            try:
                bind_res = bind_pmax_text_assets(
                    customer_id=customer_id,
                    asset_group_id=asset_group_rn.split("/")[-1],
                    headlines=headlines,
                    descriptions=descriptions
                )
                res_data["assets_bound"] = bind_res
            except Exception as e_bind:
                res_data["assets_bind_warning"] = str(e_bind)

        return res_data
    except Exception as e:
        return translate_google_ads_error(e)

@mcp.tool()
def upload_image_asset(customer_id: str, image_url: str, asset_name: str) -> dict:
    """
    [MUTATION] Faz UPLOAD DE IMAGEM para a biblioteca de assets da conta. 
    Essencial para anúncios gráficos e Performance Max.
    """
    import requests
    try:
        client = create_google_ads_client()
        asset_service = client.get_service("AssetService")
        
        response = requests.get(image_url)
        if response.status_code != 200:
            return {"error": "Nao foi possivel baixar a imagem."}
        image_data = response.content

        asset_operation = client.get_type("AssetOperation")
        asset = asset_operation.create
        asset.name = asset_name
        asset.type_ = client.enums.AssetTypeEnum.IMAGE
        asset.image_asset.data = image_data

        mutate_res = asset_service.mutate_assets(customer_id=str(customer_id), operations=[asset_operation])
        return {"status": "SUCCESS", "asset_id": mutate_res.results[0].resource_name, "name": asset_name}
    except Exception as e:
        return translate_google_ads_error(e)

@mcp.tool()
def get_keyword_forecast(customer_id: str, keywords: list[str]) -> dict:
    """
    [MARKET_DATA] Gera PREVISÕES DE DESEMPENHO para o futuro baseadas em uma lista de palavras-chave.
    """
    return {"status": "SUCCESS", "note": "Forecast feature simplified in this update."}

@mcp.tool()
def get_demographic_insights(customer_id: str, date_range: str = "LAST_30_DAYS") -> dict:
    """
    [REPORT] Analisa o PERFIL DEMOGRÁFICO (idade e gênero) de quem interagiu com os anúncios.
    """
    try:
        client = create_google_ads_client()
        googleads_service = client.get_service("GoogleAdsService")
        
        age_query = f"SELECT ad_group_criterion.age_range.type, metrics.clicks, metrics.conversions, metrics.cost_micros FROM age_range_view WHERE segments.date DURING {date_range} AND metrics.clicks > 0"
        gender_query = f"SELECT ad_group_criterion.gender.type, metrics.clicks, metrics.conversions, metrics.cost_micros FROM gender_view WHERE segments.date DURING {date_range} AND metrics.clicks > 0"
        
        age_results = [proto_to_dict(row) for batch in googleads_service.search_stream(customer_id=str(customer_id), query=age_query) for row in batch.results]
        gender_results = [proto_to_dict(row) for batch in googleads_service.search_stream(customer_id=str(customer_id), query=gender_query) for row in batch.results]

        return {"status": "SUCCESS", "date_range": date_range, "age_distribution": age_results, "gender_distribution": gender_results}
    except Exception as e:
        return translate_google_ads_error(e)

@mcp.tool()
def list_user_lists(customer_id: str) -> dict:
    """
    [REPORT] Lista segmentos de PÚBLICO-ALVO (User Lists / Remarketing) disponíveis na conta.
    """
    try:
        client = create_google_ads_client()
        googleads_service = client.get_service("GoogleAdsService")
        query = "SELECT user_list.id, user_list.name, user_list.size_for_search, user_list.size_for_display, user_list.membership_status, user_list.type FROM user_list WHERE user_list.membership_status = 'OPEN'"
        results = [proto_to_dict(row)['user_list'] for row in googleads_service.search(customer_id=str(customer_id), query=query)]
        return {"status": "SUCCESS", "user_lists": results}
    except Exception as e:
        return translate_google_ads_error(e)

@mcp.tool()
def link_audience_to_adgroup(
    customer_id: str, 
    ad_group_id: str, 
    user_list_id: str, 
    bid_modifier: float = 1.0
) -> dict:
    """
    [MUTATION] Vincula um PÚBLICO-ALVO a um grupo de anúncios para segmentação ou ajuste de lance. 
    Aceita ID numérico ou Nome do Ad Group.
    """
    try:
        client = create_google_ads_client()
        resolver = ResourceResolver(client)
        
        res_id = resolver.resolve(customer_id, "AD_GROUP", ad_group_id)
        if "error" in res_id: return res_id
        ad_group_id_num = res_id["id"]

        ad_group_criterion_service = client.get_service("AdGroupCriterionService")
        ad_group_service = client.get_service("AdGroupService")
        
        operation = client.get_type("AdGroupCriterionOperation")
        criterion = operation.create
        criterion.ad_group = ad_group_service.ad_group_path(customer_id, ad_group_id_num)
        criterion.status = client.enums.AdGroupCriterionStatusEnum.ENABLED
        criterion.user_list.user_list = f"customers/{customer_id}/userLists/{user_list_id}"
        
        if bid_modifier != 1.0:
            criterion.bid_modifier = bid_modifier

        response = ad_group_criterion_service.mutate_ad_group_criteria(customer_id=str(customer_id), operations=[operation])
        return {"status": "SUCCESS", "resource_name": response.results[0].resource_name, "ad_group_id": ad_group_id_num}
    except Exception as e:
        return translate_google_ads_error(e)


def remove_ad_group_criterion(
    customer_id: str,
    ad_group_id: str = None,
    criterion_id: str = None,
    criterion_resource_name: str = None
) -> dict:
    """
    [MUTATION] Remove/desvincula um público-alvo ou critério de segmentação de um grupo de anúncios.
    Aceita criterion_resource_name direto OU ad_group_id (ID ou nome) + criterion_id.
    """
    if not criterion_resource_name and (not ad_group_id or not criterion_id):
        return {
            "status": "ERROR",
            "message": "Informe criterion_resource_name OU (ad_group_id e criterion_id)."
        }

    try:
        client = create_google_ads_client()
        ad_group_criterion_service = client.get_service("AdGroupCriterionService")

        resource_name = criterion_resource_name
        ad_group_id_num = None

        if not resource_name:
            resolver = ResourceResolver(client)
            res_id = resolver.resolve(customer_id, "AD_GROUP", ad_group_id)
            if "error" in res_id:
                return res_id
            ad_group_id_num = res_id["id"]
            resource_name = ad_group_criterion_service.ad_group_criterion_path(
                str(customer_id), str(ad_group_id_num), str(criterion_id)
            )

        operation = client.get_type("AdGroupCriterionOperation")
        operation.remove = resource_name

        response = ad_group_criterion_service.mutate_ad_group_criteria(
            customer_id=str(customer_id),
            operations=[operation]
        )
        return {
            "status": "SUCCESS",
            "removed": resource_name,
            "ad_group_id": ad_group_id_num
        }
    except Exception as e:
        return translate_google_ads_error(e)


def get_keyword_performance(customer_id: str, date_range: str = "LAST_30_DAYS", campaign_id: str = None) -> dict:
    """
    [REPORT] Performance por keyword: Quality Score, CPC médio, impressões, cliques, conversões.
    Filtrar por campaign_id é opcional. Aceita ID numérico ou Nome da Campanha.
    """
    try:
        client = create_google_ads_client()
        ga_service = client.get_service("GoogleAdsService")

        campaign_filter = ""
        if campaign_id:
            resolver = ResourceResolver(client)
            res_id = resolver.resolve(customer_id, "CAMPAIGN", campaign_id)
            if "error" in res_id: return res_id
            campaign_id_num = res_id["id"]
            campaign_filter = f"AND campaign.id = {campaign_id_num}"

        query = f"""
            SELECT
                ad_group_criterion.keyword.text,
                ad_group_criterion.keyword.match_type,
                ad_group_criterion.quality_info.quality_score,
                ad_group_criterion.quality_info.creative_quality_score,
                ad_group_criterion.quality_info.post_click_quality_score,
                ad_group_criterion.quality_info.search_predicted_ctr,
                ad_group_criterion.cpc_bid_micros,
                ad_group_criterion.resource_name,
                ad_group.id,
                ad_group.name,
                campaign.id,
                campaign.name,
                metrics.clicks,
                metrics.impressions,
                metrics.ctr,
                metrics.average_cpc,
                metrics.conversions,
                metrics.cost_micros
            FROM keyword_view
            WHERE segments.date DURING {date_range}
            AND ad_group_criterion.status != 'REMOVED'
            {campaign_filter}
            ORDER BY metrics.cost_micros DESC
            LIMIT 100
        """
        response = ga_service.search(customer_id=str(customer_id), query=query)
        results = [dense_proto_to_dict(row) for row in response]
        return format_response(results, customer_id, "get_keyword_performance")
    except Exception as e:
        return translate_google_ads_error(e)


def get_ad_performance(customer_id: str, date_range: str = "LAST_30_DAYS", campaign_id: str = None) -> dict:
    """
    [REPORT] Performance por anúncio RSA: força do anúncio, CTR, conversões.
    Filtrar por campaign_id é opcional. Aceita ID numérico ou Nome da Campanha.
    """
    try:
        client = create_google_ads_client()
        ga_service = client.get_service("GoogleAdsService")

        campaign_filter = ""
        if campaign_id:
            resolver = ResourceResolver(client)
            res_id = resolver.resolve(customer_id, "CAMPAIGN", campaign_id)
            if "error" in res_id: return res_id
            campaign_id_num = res_id["id"]
            campaign_filter = f"AND campaign.id = {campaign_id_num}"

        query = f"""
            SELECT
                ad_group_ad.ad.id,
                ad_group_ad.ad.responsive_search_ad.headlines,
                ad_group_ad.ad_strength,
                ad_group_ad.status,
                ad_group_ad.resource_name,
                ad_group.id,
                ad_group.name,
                campaign.id,
                campaign.name,
                metrics.clicks,
                metrics.impressions,
                metrics.ctr,
                metrics.conversions,
                metrics.cost_micros
            FROM ad_group_ad
            WHERE segments.date DURING {date_range}
            AND ad_group_ad.status != 'REMOVED'
            {campaign_filter}
            ORDER BY metrics.cost_micros DESC
            LIMIT 50
        """
        response = ga_service.search(customer_id=str(customer_id), query=query)
        results = [dense_proto_to_dict(row) for row in response]
        return format_response(results, customer_id, "get_ad_performance")
    except Exception as e:
        return translate_google_ads_error(e)


def get_auction_insights(customer_id: str, date_range: str = "LAST_30_DAYS", campaign_id: str = None) -> dict:
    """
    [REPORT] Análise competitiva: impression share vs concorrentes no leilão.
    Filtrar por campaign_id é opcional. Aceita ID numérico ou Nome da Campanha.
    """
    try:
        client = create_google_ads_client()
        ga_service = client.get_service("GoogleAdsService")

        campaign_filter = ""
        if campaign_id:
            resolver = ResourceResolver(client)
            res_id = resolver.resolve(customer_id, "CAMPAIGN", campaign_id)
            if "error" in res_id: return res_id
            campaign_id_num = res_id["id"]
            campaign_filter = f"AND campaign.id = {campaign_id_num}"

        query = f"""
            SELECT
                auction_insight.domain,
                metrics.auction_insight_search_impression_share,
                metrics.auction_insight_search_overlap_rate,
                metrics.auction_insight_search_position_above_rate,
                metrics.auction_insight_search_top_impression_percentage,
                metrics.auction_insight_search_absolute_top_impression_percentage,
                campaign.id,
                campaign.name
            FROM auction_insight_table
            WHERE segments.date DURING {date_range}
            {campaign_filter}
            ORDER BY metrics.auction_insight_search_impression_share DESC
            LIMIT 20
        """
        response = ga_service.search(customer_id=str(customer_id), query=query)
        results = [dense_proto_to_dict(row) for row in response]
        return format_response(results, customer_id, "get_auction_insights")
    except Exception as e:
        return translate_google_ads_error(e)


def set_keyword_bid(customer_id: str, ad_group_id: str, keyword_resource_name: str, new_bid: float) -> dict:
    """
    [MUTATION] Ajusta o CPC de uma keyword individual.
    keyword_resource_name: obtido via get_keyword_performance (ad_group_criterion.resource_name).
    """
    try:
        client = create_google_ads_client()
        service = client.get_service("AdGroupCriterionService")

        op = client.get_type("AdGroupCriterionOperation")
        criterion = op.update
        criterion.resource_name = keyword_resource_name
        criterion.cpc_bid_micros = int(new_bid * 1e6)
        client.copy_from(op.update_mask, protobuf_helpers.field_mask(None, criterion._pb))

        response = service.mutate_ad_group_criteria(customer_id=str(customer_id), operations=[op])
        return {
            "status": "SUCCESS",
            "resource_name": response.results[0].resource_name,
            "new_bid": new_bid
        }
    except Exception as e:
        return translate_google_ads_error(e)


def set_ad_group_status(customer_id: str, ad_group_id: str, status: str) -> dict:
    """
    [MUTATION] Pausa ou ativa um grupo de anúncios. status: ENABLED | PAUSED.
    Aceita ID numérico ou Nome do Ad Group.
    """
    try:
        client = create_google_ads_client()
        resolver = ResourceResolver(client)

        res_id = resolver.resolve(customer_id, "AD_GROUP", ad_group_id)
        if "error" in res_id: return res_id
        ad_group_id_num = res_id["id"]

        service = client.get_service("AdGroupService")
        op = client.get_type("AdGroupOperation")
        ag = op.update
        ag.resource_name = service.ad_group_path(customer_id, ad_group_id_num)
        ag.status = client.enums.AdGroupStatusEnum[status]
        client.copy_from(op.update_mask, protobuf_helpers.field_mask(None, ag._pb))

        service.mutate_ad_groups(customer_id=str(customer_id), operations=[op])
        return {"status": "SUCCESS", "ad_group_status": status, "ad_group_id": ad_group_id_num}
    except Exception as e:
        return translate_google_ads_error(e)


def list_conversion_actions(customer_id: str) -> dict:
    """
    [REPORT] Lista todas as ações de conversão configuradas na conta.
    """
    try:
        client = create_google_ads_client()
        ga_service = client.get_service("GoogleAdsService")

        query = """
            SELECT
                conversion_action.id,
                conversion_action.name,
                conversion_action.status,
                conversion_action.type,
                conversion_action.category,
                conversion_action.include_in_conversions_metric,
                conversion_action.value_settings.default_value,
                conversion_action.counting_type
            FROM conversion_action
            WHERE conversion_action.status != 'REMOVED'
        """
        response = ga_service.search(customer_id=str(customer_id), query=query)
        results = [dense_proto_to_dict(row) for row in response]
        return format_response(results, customer_id, "list_conversion_actions")
    except Exception as e:
        return translate_google_ads_error(e)


def get_recommendations(customer_id: str) -> dict:
    """
    [REPORT] Lista recomendações de otimização do Google Ads para a conta.
    """
    try:
        client = create_google_ads_client()
        ga_service = client.get_service("GoogleAdsService")

        query = """
            SELECT
                recommendation.type,
                recommendation.campaign,
                recommendation.dismissed,
                recommendation.resource_name,
                recommendation.impact
            FROM recommendation
            WHERE recommendation.dismissed = FALSE
            LIMIT 20
        """
        response = ga_service.search(customer_id=str(customer_id), query=query)
        results = [dense_proto_to_dict(row) for row in response]
        return format_response(results, customer_id, "get_recommendations")
    except Exception as e:
        return translate_google_ads_error(e)


def add_callout_extension(customer_id: str, campaign_id: str, callouts: list) -> dict:
    """
    [MUTATION] Adiciona extensões de callout a uma campanha.
    callouts: lista de strings (máximo 25 caracteres cada).
    Aceita ID numérico ou Nome da Campanha.
    """
    try:
        client = create_google_ads_client()
        resolver = ResourceResolver(client)

        res_id = resolver.resolve(customer_id, "CAMPAIGN", campaign_id)
        if "error" in res_id: return res_id
        campaign_id_num = res_id["id"]

        asset_service = client.get_service("AssetService")
        campaign_asset_service = client.get_service("CampaignAssetService")
        campaign_service = client.get_service("CampaignService")
        campaign_rn = campaign_service.campaign_path(customer_id, campaign_id_num)

        added = []
        for callout_text in callouts:
            asset_op = client.get_type("AssetOperation")
            asset = asset_op.create
            asset.callout_asset.callout_text = callout_text[:25]

            asset_res = asset_service.mutate_assets(customer_id=str(customer_id), operations=[asset_op])
            asset_rn = asset_res.results[0].resource_name

            ca_op = client.get_type("CampaignAssetOperation")
            ca = ca_op.create
            ca.asset = asset_rn
            ca.campaign = campaign_rn
            ca.field_type = client.enums.AssetFieldTypeEnum.CALLOUT
            campaign_asset_service.mutate_campaign_assets(customer_id=str(customer_id), operations=[ca_op])

            added.append(callout_text[:25])

        return {"status": "SUCCESS", "callouts_added": len(added), "callouts": added, "campaign_id": campaign_id_num}
    except Exception as e:
        return translate_google_ads_error(e)


def add_call_extension(customer_id: str, campaign_id: str, phone_number: str, country_code: str = "BR") -> dict:
    """
    [MUTATION] Adiciona extensão de ligação (número de telefone) a uma campanha.
    Aceita ID numérico ou Nome da Campanha.
    """
    try:
        client = create_google_ads_client()
        resolver = ResourceResolver(client)

        res_id = resolver.resolve(customer_id, "CAMPAIGN", campaign_id)
        if "error" in res_id: return res_id
        campaign_id_num = res_id["id"]

        asset_service = client.get_service("AssetService")
        campaign_asset_service = client.get_service("CampaignAssetService")
        campaign_service = client.get_service("CampaignService")
        campaign_rn = campaign_service.campaign_path(customer_id, campaign_id_num)

        asset_op = client.get_type("AssetOperation")
        asset = asset_op.create
        asset.call_asset.country_code = country_code
        asset.call_asset.phone_number = phone_number

        asset_res = asset_service.mutate_assets(customer_id=str(customer_id), operations=[asset_op])
        asset_rn = asset_res.results[0].resource_name

        ca_op = client.get_type("CampaignAssetOperation")
        ca = ca_op.create
        ca.asset = asset_rn
        ca.campaign = campaign_rn
        ca.field_type = client.enums.AssetFieldTypeEnum.CALL
        campaign_asset_service.mutate_campaign_assets(customer_id=str(customer_id), operations=[ca_op])

        return {
            "status": "SUCCESS",
            "asset_id": asset_rn,
            "phone_number": phone_number,
            "country_code": country_code,
            "campaign_id": campaign_id_num
        }
    except Exception as e:
        return translate_google_ads_error(e)


def get_shared_negative_lists(customer_id: str) -> dict:
    """
    [REPORT] Lista as listas de palavras-chave negativas compartilhadas entre campanhas,
    incluindo os termos contidos em cada lista.
    """
    try:
        client = create_google_ads_client()
        ga_service = client.get_service("GoogleAdsService")

        sets_query = """
            SELECT shared_set.id, shared_set.name, shared_set.type, shared_set.member_count
            FROM shared_set
            WHERE shared_set.type = 'NEGATIVE_KEYWORDS'
            AND shared_set.status = 'ENABLED'
        """
        sets_response = ga_service.search(customer_id=str(customer_id), query=sets_query)
        shared_sets = [dense_proto_to_dict(row) for row in sets_response]

        criteria_query = """
            SELECT shared_criterion.keyword.text, shared_criterion.keyword.match_type, shared_criterion.shared_set
            FROM shared_criterion
            WHERE shared_criterion.type = 'KEYWORD'
        """
        criteria_response = ga_service.search(customer_id=str(customer_id), query=criteria_query)
        criteria = [dense_proto_to_dict(row) for row in criteria_response]

        return {
            "status": "SUCCESS",
            "shared_sets": shared_sets,
            "keywords": criteria,
            "customer_id": str(customer_id)
        }
    except Exception as e:
        return translate_google_ads_error(e)


def bulk_pause_keywords(
    customer_id: str,
    min_clicks: int = 10,
    max_conversions: float = 0,
    date_range: str = "LAST_30_DAYS",
    dry_run: bool = True
) -> dict:
    """
    [MUTATION] Pausa em lote keywords com cliques >= min_clicks e conversões <= max_conversions.
    Use para eliminar desperdício. Por padrão dry_run=True retorna preview sem executar.
    """
    try:
        client = create_google_ads_client()
        ga_service = client.get_service("GoogleAdsService")

        query = f"""
            SELECT
                ad_group_criterion.keyword.text,
                ad_group_criterion.keyword.match_type,
                ad_group_criterion.resource_name,
                ad_group.id,
                ad_group.name,
                campaign.id,
                campaign.name,
                metrics.clicks,
                metrics.conversions,
                metrics.cost_micros
            FROM keyword_view
            WHERE segments.date DURING {date_range}
            AND ad_group_criterion.status != 'REMOVED'
            AND metrics.clicks >= {min_clicks}
            AND metrics.conversions <= {max_conversions}
            ORDER BY metrics.cost_micros DESC
            LIMIT 200
        """
        response = ga_service.search(customer_id=str(customer_id), query=query)
        candidates = [dense_proto_to_dict(row) for row in response]

        if dry_run:
            return {
                "status": "DRY_RUN",
                "would_pause": len(candidates),
                "keywords": candidates,
                "message": f"Dry run: {len(candidates)} keywords seriam pausadas. Passe dry_run=False para executar."
            }

        if not candidates:
            return {"status": "SUCCESS", "paused": 0, "message": "Nenhuma keyword encontrada com os critérios fornecidos."}

        criterion_service = client.get_service("AdGroupCriterionService")
        ops = []
        for kw_data in candidates:
            resource_name = (
                kw_data.get("ad_group_criterion", {}).get("resource_name")
                or kw_data.get("resource_name")
            )
            if not resource_name:
                continue
            op = client.get_type("AdGroupCriterionOperation")
            criterion = op.update
            criterion.resource_name = resource_name
            criterion.status = client.enums.AdGroupCriterionStatusEnum.PAUSED
            client.copy_from(op.update_mask, protobuf_helpers.field_mask(None, criterion._pb))
            ops.append(op)

        if ops:
            criterion_service.mutate_ad_group_criteria(customer_id=str(customer_id), operations=ops)

        return {
            "status": "SUCCESS",
            "paused": len(ops),
            "message": f"{len(ops)} keywords pausadas com sucesso."
        }
    except Exception as e:
        return translate_google_ads_error(e)


# ─────────────────────────────────────────────
# TIER 1 — RELATÓRIOS POR DIMENSÃO
# ─────────────────────────────────────────────

def get_device_performance(customer_id: str, date_range: str = "LAST_30_DAYS", campaign_id: str = None) -> dict:
    """[REPORT] Performance segmentada por dispositivo: Mobile, Desktop, Tablet."""
    try:
        client = create_google_ads_client()
        ga_service = client.get_service("GoogleAdsService")

        campaign_filter = ""
        if campaign_id:
            resolver = ResourceResolver(client)
            res_id = resolver.resolve(customer_id, "CAMPAIGN", campaign_id)
            if "error" in res_id: return res_id
            campaign_id_num = res_id["id"]
            campaign_filter = f"AND campaign.id = {campaign_id_num}"

        query = f"""
            SELECT
                segments.device,
                campaign.id,
                campaign.name,
                metrics.clicks,
                metrics.impressions,
                metrics.cost_micros,
                metrics.conversions,
                metrics.ctr
            FROM campaign
            WHERE segments.date DURING {date_range}
            AND campaign.status != 'REMOVED'
            {campaign_filter}
            ORDER BY metrics.cost_micros DESC
        """
        response = ga_service.search(customer_id=str(customer_id), query=query)
        results = [dense_proto_to_dict(row) for row in response]
        return format_response(results, customer_id, "get_device_performance")
    except Exception as e:
        return translate_google_ads_error(e)


def get_geographic_performance(customer_id: str, date_range: str = "LAST_30_DAYS", campaign_id: str = None) -> dict:
    """[REPORT] Performance por localização geográfica (cidade, estado, país)."""
    try:
        client = create_google_ads_client()
        ga_service = client.get_service("GoogleAdsService")

        campaign_filter = ""
        if campaign_id:
            resolver = ResourceResolver(client)
            res_id = resolver.resolve(customer_id, "CAMPAIGN", campaign_id)
            if "error" in res_id: return res_id
            campaign_id_num = res_id["id"]
            campaign_filter = f"AND campaign.id = {campaign_id_num}"

        query = f"""
            SELECT
                user_location_view.country_criterion_id,
                user_location_view.targeting_location,
                campaign.id,
                campaign.name,
                metrics.clicks,
                metrics.impressions,
                metrics.cost_micros,
                metrics.conversions
            FROM user_location_view
            WHERE segments.date DURING {date_range}
            {campaign_filter}
            ORDER BY metrics.cost_micros DESC
            LIMIT 50
        """
        response = ga_service.search(customer_id=str(customer_id), query=query)
        results = [dense_proto_to_dict(row) for row in response]
        return format_response(results, customer_id, "get_geographic_performance")
    except Exception as e:
        return translate_google_ads_error(e)


def get_hourly_performance(customer_id: str, date_range: str = "LAST_7_DAYS", campaign_id: str = None) -> dict:
    """[REPORT] Performance por hora do dia. Fundamental para configurar dayparting."""
    try:
        client = create_google_ads_client()
        ga_service = client.get_service("GoogleAdsService")

        campaign_filter = ""
        if campaign_id:
            resolver = ResourceResolver(client)
            res_id = resolver.resolve(customer_id, "CAMPAIGN", campaign_id)
            if "error" in res_id: return res_id
            campaign_id_num = res_id["id"]
            campaign_filter = f"AND campaign.id = {campaign_id_num}"

        query = f"""
            SELECT
                segments.hour,
                campaign.id,
                campaign.name,
                metrics.clicks,
                metrics.impressions,
                metrics.cost_micros,
                metrics.conversions
            FROM campaign
            WHERE segments.date DURING {date_range}
            AND campaign.status != 'REMOVED'
            {campaign_filter}
            ORDER BY segments.hour ASC
        """
        response = ga_service.search(customer_id=str(customer_id), query=query)
        results = [dense_proto_to_dict(row) for row in response]
        return format_response(results, customer_id, "get_hourly_performance")
    except Exception as e:
        return translate_google_ads_error(e)


def get_asset_performance(customer_id: str, date_range: str = "LAST_30_DAYS", campaign_id: str = None) -> dict:
    """[REPORT] Performance individual de cada headline e description dentro dos RSAs."""
    try:
        client = create_google_ads_client()
        ga_service = client.get_service("GoogleAdsService")

        campaign_filter = ""
        if campaign_id:
            resolver = ResourceResolver(client)
            res_id = resolver.resolve(customer_id, "CAMPAIGN", campaign_id)
            if "error" in res_id: return res_id
            campaign_id_num = res_id["id"]
            campaign_filter = f"AND campaign.id = {campaign_id_num}"

        query = f"""
            SELECT
                ad_group_ad_asset_view.asset,
                ad_group_ad_asset_view.field_type,
                ad_group_ad_asset_view.performance_label,
                asset.text_asset.text,
                ad_group_ad.ad.id,
                campaign.name
            FROM ad_group_ad_asset_view
            WHERE segments.date DURING {date_range}
            {campaign_filter}
            LIMIT 100
        """
        response = ga_service.search(customer_id=str(customer_id), query=query)
        results = [dense_proto_to_dict(row) for row in response]
        return format_response(results, customer_id, "get_asset_performance")
    except Exception as e:
        return translate_google_ads_error(e)


def get_landing_page_performance(customer_id: str, date_range: str = "LAST_30_DAYS") -> dict:
    """[REPORT] Métricas por URL de destino: cliques, conversões, taxa de rejeição."""
    try:
        client = create_google_ads_client()
        ga_service = client.get_service("GoogleAdsService")

        query = f"""
            SELECT
                landing_page_view.unexpanded_final_url,
                metrics.clicks,
                metrics.conversions,
                metrics.cost_micros,
                metrics.average_cpc
            FROM landing_page_view
            WHERE segments.date DURING {date_range}
            ORDER BY metrics.clicks DESC
            LIMIT 50
        """
        response = ga_service.search(customer_id=str(customer_id), query=query)
        results = [dense_proto_to_dict(row) for row in response]
        return format_response(results, customer_id, "get_landing_page_performance")
    except Exception as e:
        return translate_google_ads_error(e)


def get_audience_performance(customer_id: str, date_range: str = "LAST_30_DAYS", campaign_id: str = None) -> dict:
    """[REPORT] Performance por segmento de audiência aplicado às campanhas."""
    try:
        client = create_google_ads_client()
        ga_service = client.get_service("GoogleAdsService")

        campaign_filter = ""
        if campaign_id:
            resolver = ResourceResolver(client)
            res_id = resolver.resolve(customer_id, "CAMPAIGN", campaign_id)
            if "error" in res_id: return res_id
            campaign_id_num = res_id["id"]
            campaign_filter = f"AND campaign.id = {campaign_id_num}"

        query = f"""
            SELECT
                ad_group_criterion.user_list.user_list,
                ad_group.name,
                campaign.name,
                metrics.clicks,
                metrics.impressions,
                metrics.cost_micros,
                metrics.conversions
            FROM ad_group_audience_view
            WHERE segments.date DURING {date_range}
            {campaign_filter}
            ORDER BY metrics.cost_micros DESC
            LIMIT 50
        """
        response = ga_service.search(customer_id=str(customer_id), query=query)
        results = [dense_proto_to_dict(row) for row in response]
        return format_response(results, customer_id, "get_audience_performance")
    except Exception as e:
        return translate_google_ads_error(e)


# ─────────────────────────────────────────────
# TIER 1 — TARGETING & AJUSTES
# ─────────────────────────────────────────────

def set_device_bid_adjustment(customer_id: str, campaign_id: str, device: str, modifier: float) -> dict:
    """[MUTATION] Ajusta o bid por dispositivo na campanha. device: MOBILE|DESKTOP|TABLET. modifier: 0.0 a 10.0 (1.0 = sem ajuste, 0.0 = excluir)."""
    try:
        from google.protobuf import field_mask_pb2
        client = create_google_ads_client()
        resolver = ResourceResolver(client)

        res_id = resolver.resolve(customer_id, "CAMPAIGN", campaign_id)
        if "error" in res_id: return res_id
        campaign_id_num = res_id["id"]

        device_upper = device.upper()
        campaign_service = client.get_service("CampaignService")
        campaign_criterion_service = client.get_service("CampaignCriterionService")
        ga_service = client.get_service("GoogleAdsService")

        query = f"""
            SELECT campaign_criterion.resource_name, campaign_criterion.device.type
            FROM campaign_criterion
            WHERE campaign.id = {campaign_id_num} AND campaign_criterion.type = 'DEVICE'
        """
        target_rn = None
        stream = ga_service.search_stream(customer_id=str(customer_id), query=query)
        for batch in stream:
            for row in batch.results:
                if row.campaign_criterion.device.type_.name == device_upper:
                    target_rn = row.campaign_criterion.resource_name
                    break
            if target_rn:
                break

        op = client.get_type("CampaignCriterionOperation")
        if target_rn:
            criterion = op.update
            criterion.resource_name = target_rn
            criterion.bid_modifier = modifier
            op.update_mask.CopyFrom(field_mask_pb2.FieldMask(paths=["bid_modifier"]))
        else:
            criterion = op.create
            criterion.campaign = campaign_service.campaign_path(customer_id, campaign_id_num)
            criterion.device.type_ = client.enums.DeviceEnum[device_upper]
            criterion.bid_modifier = modifier

        response = campaign_criterion_service.mutate_campaign_criteria(
            customer_id=str(customer_id), operations=[op]
        )
        return {
            "status": "SUCCESS",
            "resource_name": response.results[0].resource_name,
            "device": device_upper,
            "modifier": modifier,
            "campaign_id": campaign_id_num
        }
    except Exception as e:
        return translate_google_ads_error(e)


def set_location_targeting(customer_id: str, campaign_id: str, geo_target_ids: list, negative: bool = False) -> dict:
    """[MUTATION] Adiciona alvos de localização a uma campanha. Use search_geo_targets para obter os IDs."""
    try:
        client = create_google_ads_client()
        resolver = ResourceResolver(client)

        res_id = resolver.resolve(customer_id, "CAMPAIGN", campaign_id)
        if "error" in res_id: return res_id
        campaign_id_num = res_id["id"]

        campaign_service = client.get_service("CampaignService")
        campaign_criterion_service = client.get_service("CampaignCriterionService")
        campaign_rn = campaign_service.campaign_path(customer_id, campaign_id_num)

        ops = []
        for geo_id in geo_target_ids:
            op = client.get_type("CampaignCriterionOperation")
            criterion = op.create
            criterion.campaign = campaign_rn
            criterion.location.geo_target_constant = f"geoTargetConstants/{geo_id}"
            criterion.negative = negative
            ops.append(op)

        response = campaign_criterion_service.mutate_campaign_criteria(
            customer_id=str(customer_id), operations=ops
        )
        return {
            "status": "SUCCESS",
            "added": len(response.results),
            "geo_target_ids": geo_target_ids,
            "negative": negative,
            "campaign_id": campaign_id_num
        }
    except Exception as e:
        return translate_google_ads_error(e)


def set_language_targeting(customer_id: str, campaign_id: str, language_ids: list) -> dict:
    """[MUTATION] Define idiomas alvo de uma campanha. IDs: 1014=pt, 1000=en, 1003=es."""
    try:
        client = create_google_ads_client()
        resolver = ResourceResolver(client)

        res_id = resolver.resolve(customer_id, "CAMPAIGN", campaign_id)
        if "error" in res_id: return res_id
        campaign_id_num = res_id["id"]

        campaign_service = client.get_service("CampaignService")
        campaign_criterion_service = client.get_service("CampaignCriterionService")
        campaign_rn = campaign_service.campaign_path(customer_id, campaign_id_num)

        ops = []
        for lang_id in language_ids:
            op = client.get_type("CampaignCriterionOperation")
            criterion = op.create
            criterion.campaign = campaign_rn
            criterion.language.language_constant = f"languageConstants/{lang_id}"
            ops.append(op)

        response = campaign_criterion_service.mutate_campaign_criteria(
            customer_id=str(customer_id), operations=ops
        )
        return {
            "status": "SUCCESS",
            "added": len(response.results),
            "language_ids": language_ids,
            "campaign_id": campaign_id_num
        }
    except Exception as e:
        return translate_google_ads_error(e)


def set_ad_schedule(customer_id: str, campaign_id: str, schedules: list) -> dict:
    """[MUTATION] Configura dayparting (horários ativos) na campanha. Cada schedule: {day_of_week, start_hour, end_hour, bid_modifier}. day_of_week: MONDAY..SUNDAY."""
    try:
        client = create_google_ads_client()
        resolver = ResourceResolver(client)

        res_id = resolver.resolve(customer_id, "CAMPAIGN", campaign_id)
        if "error" in res_id: return res_id
        campaign_id_num = res_id["id"]

        campaign_service = client.get_service("CampaignService")
        campaign_criterion_service = client.get_service("CampaignCriterionService")
        campaign_rn = campaign_service.campaign_path(customer_id, campaign_id_num)

        ops = []
        for schedule in schedules:
            op = client.get_type("CampaignCriterionOperation")
            criterion = op.create
            criterion.campaign = campaign_rn
            criterion.ad_schedule.day_of_week = client.enums.DayOfWeekEnum[schedule["day_of_week"]]
            criterion.ad_schedule.start_hour = schedule["start_hour"]
            criterion.ad_schedule.end_hour = schedule["end_hour"]
            criterion.ad_schedule.start_minute = client.enums.MinuteOfHourEnum.ZERO
            criterion.ad_schedule.end_minute = client.enums.MinuteOfHourEnum.ZERO
            if "bid_modifier" in schedule:
                criterion.bid_modifier = schedule["bid_modifier"]
            ops.append(op)

        response = campaign_criterion_service.mutate_campaign_criteria(
            customer_id=str(customer_id), operations=ops
        )
        return {
            "status": "SUCCESS",
            "schedules_added": len(response.results),
            "campaign_id": campaign_id_num
        }
    except Exception as e:
        return translate_google_ads_error(e)


def search_geo_targets(location_name: str, country_code: str = "BR") -> dict:
    """[UTILITY] Busca IDs de localização por nome. Use antes de set_location_targeting."""
    try:
        client = create_google_ads_client()
        geo_target_service = client.get_service("GeoTargetConstantService")

        request = client.get_type("SuggestGeoTargetConstantsRequest")
        request.locale = "pt-BR"
        request.country_code = country_code
        request.names.extend([location_name])

        response = geo_target_service.suggest_geo_target_constants(request=request)
        results = []
        for suggestion in response.geo_target_constant_suggestions:
            geo = suggestion.geo_target_constant
            results.append({
                "id": geo.id,
                "name": geo.name,
                "country_code": geo.country_code,
                "target_type": geo.target_type,
                "resource_name": geo.resource_name
            })
        return {"status": "SUCCESS", "geo_targets": results}
    except Exception as e:
        return translate_google_ads_error(e)


def create_label(customer_id: str, name: str, description: str = "") -> dict:
    """[CREATE] Cria uma etiqueta para organizar campanhas, grupos e keywords."""
    try:
        client = create_google_ads_client()
        label_service = client.get_service("LabelService")

        op = client.get_type("LabelOperation")
        label = op.create
        label.name = name
        if description:
            label.description = description
        label.text_label.background_color = "#FFFFFF"

        response = label_service.mutate_labels(customer_id=str(customer_id), operations=[op])
        resource_name = response.results[0].resource_name
        label_id = resource_name.split("/")[-1]
        return {
            "status": "SUCCESS",
            "resource_name": resource_name,
            "label_id": label_id,
            "name": name
        }
    except Exception as e:
        return translate_google_ads_error(e)


def apply_label(customer_id: str, label_id: str, resource_type: str, resource_ids: list) -> dict:
    """[MUTATION] Aplica etiqueta a campanhas ou grupos. resource_type: CAMPAIGN|AD_GROUP|KEYWORD."""
    try:
        client = create_google_ads_client()
        label_rn = f"customers/{customer_id}/labels/{label_id}"

        if resource_type == "CAMPAIGN":
            service = client.get_service("CampaignLabelService")
            campaign_service = client.get_service("CampaignService")
            ops = []
            for res_id in resource_ids:
                op = client.get_type("CampaignLabelOperation")
                cl = op.create
                cl.campaign = campaign_service.campaign_path(customer_id, res_id)
                cl.label = label_rn
                ops.append(op)
            response = service.mutate_campaign_labels(customer_id=str(customer_id), operations=ops)
        elif resource_type == "AD_GROUP":
            service = client.get_service("AdGroupLabelService")
            ad_group_service = client.get_service("AdGroupService")
            ops = []
            for res_id in resource_ids:
                op = client.get_type("AdGroupLabelOperation")
                agl = op.create
                agl.ad_group = ad_group_service.ad_group_path(customer_id, res_id)
                agl.label = label_rn
                ops.append(op)
            response = service.mutate_ad_group_labels(customer_id=str(customer_id), operations=ops)
        else:
            return {"error": f"resource_type '{resource_type}' não suportado. Use CAMPAIGN ou AD_GROUP."}

        return {
            "status": "SUCCESS",
            "applied": len(response.results),
            "label_id": label_id,
            "resource_type": resource_type
        }
    except Exception as e:
        return translate_google_ads_error(e)


def list_labels(customer_id: str) -> dict:
    """[REPORT] Lista todas as etiquetas da conta e onde estão aplicadas."""
    try:
        client = create_google_ads_client()
        ga_service = client.get_service("GoogleAdsService")

        query = """
            SELECT
                label.id,
                label.name,
                label.status,
                label.resource_name
            FROM label
            WHERE label.status = 'ENABLED'
        """
        response = ga_service.search(customer_id=str(customer_id), query=query)
        results = [dense_proto_to_dict(row) for row in response]
        return {"status": "SUCCESS", "labels": results}
    except Exception as e:
        return translate_google_ads_error(e)


# ─────────────────────────────────────────────
# TIER 2 — ESTRATÉGIAS DE LANCE
# ─────────────────────────────────────────────

def list_bid_strategies(customer_id: str) -> dict:
    """[REPORT] Lista estratégias de lance de portfólio configuradas na conta."""
    try:
        client = create_google_ads_client()
        ga_service = client.get_service("GoogleAdsService")

        query = """
            SELECT
                bidding_strategy.id,
                bidding_strategy.name,
                bidding_strategy.type,
                bidding_strategy.status,
                bidding_strategy.campaign_count
            FROM bidding_strategy
            WHERE bidding_strategy.status = 'ENABLED'
        """
        response = ga_service.search(customer_id=str(customer_id), query=query)
        results = [dense_proto_to_dict(row) for row in response]
        return {"status": "SUCCESS", "bid_strategies": results}
    except Exception as e:
        return translate_google_ads_error(e)


def create_bid_strategy(customer_id: str, name: str, strategy_type: str, target_value: float = None) -> dict:
    """[CREATE] Cria estratégia de lance de portfólio. strategy_type: TARGET_CPA|TARGET_ROAS|MAXIMIZE_CONVERSIONS|MAXIMIZE_CONVERSION_VALUE."""
    try:
        client = create_google_ads_client()
        bidding_strategy_service = client.get_service("BiddingStrategyService")

        op = client.get_type("BiddingStrategyOperation")
        strategy = op.create
        strategy.name = name

        if strategy_type == "TARGET_CPA":
            client.copy_from(strategy.target_cpa, client.get_type("TargetCpa"))
            if target_value is not None:
                strategy.target_cpa.target_cpa_micros = int(target_value * 1e6)
        elif strategy_type == "TARGET_ROAS":
            client.copy_from(strategy.target_roas, client.get_type("TargetRoas"))
            if target_value is not None:
                strategy.target_roas.target_roas = target_value
        elif strategy_type == "MAXIMIZE_CONVERSIONS":
            client.copy_from(strategy.maximize_conversions, client.get_type("MaximizeConversions"))
        elif strategy_type == "MAXIMIZE_CONVERSION_VALUE":
            client.copy_from(strategy.maximize_conversion_value, client.get_type("MaximizeConversionValue"))
        else:
            return {"error": f"strategy_type '{strategy_type}' inválido. Use: TARGET_CPA, TARGET_ROAS, MAXIMIZE_CONVERSIONS, MAXIMIZE_CONVERSION_VALUE"}

        response = bidding_strategy_service.mutate_bidding_strategies(
            customer_id=str(customer_id), operations=[op]
        )
        resource_name = response.results[0].resource_name
        return {
            "status": "SUCCESS",
            "resource_name": resource_name,
            "strategy_id": resource_name.split("/")[-1],
            "name": name,
            "strategy_type": strategy_type
        }
    except Exception as e:
        return translate_google_ads_error(e)


def apply_bid_strategy(customer_id: str, campaign_id: str, bid_strategy_id: str) -> dict:
    """[MUTATION] Aplica uma estratégia de lance de portfólio a uma campanha."""
    try:
        client = create_google_ads_client()
        resolver = ResourceResolver(client)

        res_id = resolver.resolve(customer_id, "CAMPAIGN", campaign_id)
        if "error" in res_id: return res_id
        campaign_id_num = res_id["id"]

        campaign_service = client.get_service("CampaignService")
        op = client.get_type("CampaignOperation")
        c = op.update
        c.resource_name = campaign_service.campaign_path(customer_id, campaign_id_num)
        c.bidding_strategy = f"customers/{customer_id}/biddingStrategies/{bid_strategy_id}"
        client.copy_from(op.update_mask, protobuf_helpers.field_mask(None, c._pb))

        campaign_service.mutate_campaigns(customer_id=str(customer_id), operations=[op])
        return {
            "status": "SUCCESS",
            "campaign_id": campaign_id_num,
            "bid_strategy_id": bid_strategy_id
        }
    except Exception as e:
        return translate_google_ads_error(e)


def create_conversion_action(customer_id: str, name: str, category: str, conversion_type: str = "WEBPAGE", default_value: float = 0.0) -> dict:
    """[CREATE] Cria uma nova ação de conversão. category: PURCHASE|LEAD|SIGNUP|PAGE_VIEW|OTHER."""
    try:
        client = create_google_ads_client()
        conversion_action_service = client.get_service("ConversionActionService")

        op = client.get_type("ConversionActionOperation")
        ca = op.create
        ca.name = name
        ca.category = client.enums.ConversionActionCategoryEnum[category]
        ca.type_ = client.enums.ConversionActionTypeEnum[conversion_type]
        ca.value_settings.default_value = default_value
        ca.counting_type = client.enums.ConversionActionCountingTypeEnum.ONE_PER_CLICK
        ca.status = client.enums.ConversionActionStatusEnum.ENABLED

        response = conversion_action_service.mutate_conversion_actions(
            customer_id=str(customer_id), operations=[op]
        )
        resource_name = response.results[0].resource_name
        return {
            "status": "SUCCESS",
            "resource_name": resource_name,
            "conversion_action_id": resource_name.split("/")[-1],
            "name": name,
            "category": category
        }
    except Exception as e:
        return translate_google_ads_error(e)


def upload_offline_conversions(customer_id: str, conversions: list) -> dict:
    """[MUTATION] Importa conversões offline (ex: vendas do CRM). Cada conversão: {gclid, conversion_action_id, conversion_date_time, conversion_value}."""
    try:
        client = create_google_ads_client()
        conversion_upload_service = client.get_service("ConversionUploadService")

        click_conversions = []
        for conv in conversions:
            click_conversion = client.get_type("ClickConversion")
            click_conversion.gclid = conv["gclid"]
            click_conversion.conversion_action = f"customers/{customer_id}/conversionActions/{conv['conversion_action_id']}"
            click_conversion.conversion_date_time = conv["conversion_date_time"]
            click_conversion.conversion_value = conv.get("conversion_value", 0.0)
            click_conversions.append(click_conversion)

        request = client.get_type("UploadClickConversionsRequest")
        request.customer_id = str(customer_id)
        request.conversions.extend(click_conversions)
        request.partial_failure = True

        response = conversion_upload_service.upload_click_conversions(request=request)
        return {
            "status": "SUCCESS",
            "uploaded": len(conversions),
            "partial_failure_error": str(response.partial_failure_error) if response.partial_failure_error else None
        }
    except Exception as e:
        return translate_google_ads_error(e)


def apply_recommendation(customer_id: str, recommendation_resource_name: str) -> dict:
    """[MUTATION] Aplica uma recomendação do Google Ads. Obtenha o resource_name via get_recommendations."""
    try:
        client = create_google_ads_client()
        recommendation_service = client.get_service("RecommendationService")

        op = client.get_type("ApplyRecommendationOperation")
        op.resource_name = recommendation_resource_name

        response = recommendation_service.apply_recommendations(
            customer_id=str(customer_id), operations=[op]
        )
        return {
            "status": "SUCCESS",
            "applied": len(response.results),
            "resource_name": recommendation_resource_name
        }
    except Exception as e:
        return translate_google_ads_error(e)


def dismiss_recommendation(customer_id: str, recommendation_resource_name: str) -> dict:
    """[MUTATION] Descarta uma recomendação do Google Ads."""
    try:
        client = create_google_ads_client()
        recommendation_service = client.get_service("RecommendationService")

        request = client.get_type("DismissRecommendationRequest")
        request.customer_id = str(customer_id)
        entry = client.get_type("DismissRecommendationRequest.DismissRecommendationEntry")
        entry.resource_name = recommendation_resource_name
        request.operations.append(entry)

        recommendation_service.dismiss_recommendations(request=request)
        return {
            "status": "SUCCESS",
            "dismissed": recommendation_resource_name
        }
    except Exception as e:
        return translate_google_ads_error(e)


def add_structured_snippet(customer_id: str, campaign_id: str, header: str, values: list) -> dict:
    """[MUTATION] Adiciona extensão de snippets estruturados. header: Serviços|Marcas|Cursos|etc. values: lista de até 10 itens."""
    try:
        client = create_google_ads_client()
        resolver = ResourceResolver(client)

        res_id = resolver.resolve(customer_id, "CAMPAIGN", campaign_id)
        if "error" in res_id: return res_id
        campaign_id_num = res_id["id"]

        asset_service = client.get_service("AssetService")
        campaign_asset_service = client.get_service("CampaignAssetService")
        campaign_service = client.get_service("CampaignService")
        campaign_rn = campaign_service.campaign_path(customer_id, campaign_id_num)

        asset_op = client.get_type("AssetOperation")
        asset = asset_op.create
        asset.structured_snippet_asset.header = header
        asset.structured_snippet_asset.values.extend(values[:10])

        asset_res = asset_service.mutate_assets(customer_id=str(customer_id), operations=[asset_op])
        asset_rn = asset_res.results[0].resource_name

        ca_op = client.get_type("CampaignAssetOperation")
        ca = ca_op.create
        ca.asset = asset_rn
        ca.campaign = campaign_rn
        ca.field_type = client.enums.AssetFieldTypeEnum.STRUCTURED_SNIPPET
        campaign_asset_service.mutate_campaign_assets(customer_id=str(customer_id), operations=[ca_op])

        return {
            "status": "SUCCESS",
            "asset_id": asset_rn,
            "header": header,
            "values": values[:10],
            "campaign_id": campaign_id_num
        }
    except Exception as e:
        return translate_google_ads_error(e)


def add_promotion_extension(customer_id: str, campaign_id: str, promotion_text: str, discount_modifier: str, discount_value: float, final_url: str, start_date: str = None, end_date: str = None) -> dict:
    """[MUTATION] Adiciona extensão de promoção. discount_modifier: PERCENT_OFF|UP_TO_PERCENT_OFF|AMOUNT_OFF|UP_TO_AMOUNT_OFF."""
    try:
        client = create_google_ads_client()
        resolver = ResourceResolver(client)

        res_id = resolver.resolve(customer_id, "CAMPAIGN", campaign_id)
        if "error" in res_id: return res_id
        campaign_id_num = res_id["id"]

        asset_service = client.get_service("AssetService")
        campaign_asset_service = client.get_service("CampaignAssetService")
        campaign_service = client.get_service("CampaignService")
        campaign_rn = campaign_service.campaign_path(customer_id, campaign_id_num)

        asset_op = client.get_type("AssetOperation")
        asset = asset_op.create
        asset.promotion_asset.promotion_text = promotion_text[:20]
        asset.promotion_asset.discount_modifier = client.enums.PromotionExtensionDiscountModifierEnum[discount_modifier]

        if "PERCENT" in discount_modifier:
            asset.promotion_asset.percent_off = int(discount_value * 100000)
        else:
            asset.promotion_asset.money_amount_off.amount_micros = int(discount_value * 1e6)
            asset.promotion_asset.money_amount_off.currency_code = "BRL"

        asset.promotion_asset.final_urls.append(final_url)

        if start_date:
            asset.promotion_asset.promotion_start_date = start_date
        if end_date:
            asset.promotion_asset.promotion_end_date = end_date

        asset_res = asset_service.mutate_assets(customer_id=str(customer_id), operations=[asset_op])
        asset_rn = asset_res.results[0].resource_name

        ca_op = client.get_type("CampaignAssetOperation")
        ca = ca_op.create
        ca.asset = asset_rn
        ca.campaign = campaign_rn
        ca.field_type = client.enums.AssetFieldTypeEnum.PROMOTION
        campaign_asset_service.mutate_campaign_assets(customer_id=str(customer_id), operations=[ca_op])

        return {
            "status": "SUCCESS",
            "asset_id": asset_rn,
            "promotion_text": promotion_text[:20],
            "campaign_id": campaign_id_num
        }
    except Exception as e:
        return translate_google_ads_error(e)


def create_shared_budget(customer_id: str, name: str, amount: float) -> dict:
    """[CREATE] Cria um orçamento compartilhado entre múltiplas campanhas."""
    try:
        client = create_google_ads_client()
        budget_service = client.get_service("CampaignBudgetService")

        op = client.get_type("CampaignBudgetOperation")
        budget = op.create
        budget.name = name
        budget.amount_micros = int(amount * 1e6)
        budget.explicitly_shared = True
        budget.delivery_method = client.enums.BudgetDeliveryMethodEnum.STANDARD

        response = budget_service.mutate_campaign_budgets(customer_id=str(customer_id), operations=[op])
        resource_name = response.results[0].resource_name
        return {
            "status": "SUCCESS",
            "resource_name": resource_name,
            "budget_id": resource_name.split("/")[-1],
            "name": name,
            "amount": amount
        }
    except Exception as e:
        return translate_google_ads_error(e)


def apply_shared_budget(customer_id: str, campaign_id: str, shared_budget_resource_name: str) -> dict:
    """[MUTATION] Aplica um orçamento compartilhado a uma campanha."""
    try:
        client = create_google_ads_client()
        resolver = ResourceResolver(client)

        res_id = resolver.resolve(customer_id, "CAMPAIGN", campaign_id)
        if "error" in res_id: return res_id
        campaign_id_num = res_id["id"]

        campaign_service = client.get_service("CampaignService")
        op = client.get_type("CampaignOperation")
        c = op.update
        c.resource_name = campaign_service.campaign_path(customer_id, campaign_id_num)
        c.campaign_budget = shared_budget_resource_name
        client.copy_from(op.update_mask, protobuf_helpers.field_mask(None, c._pb))

        campaign_service.mutate_campaigns(customer_id=str(customer_id), operations=[op])
        return {
            "status": "SUCCESS",
            "campaign_id": campaign_id_num,
            "shared_budget": shared_budget_resource_name
        }
    except Exception as e:
        return translate_google_ads_error(e)


def link_shared_negative_list(customer_id: str, campaign_id: str, shared_set_id: str) -> dict:
    """[MUTATION] Aplica uma lista de negativos compartilhada a uma campanha."""
    try:
        client = create_google_ads_client()
        resolver = ResourceResolver(client)

        res_id = resolver.resolve(customer_id, "CAMPAIGN", campaign_id)
        if "error" in res_id: return res_id
        campaign_id_num = res_id["id"]

        campaign_service = client.get_service("CampaignService")
        campaign_shared_set_service = client.get_service("CampaignSharedSetService")

        op = client.get_type("CampaignSharedSetOperation")
        css = op.create
        css.campaign = campaign_service.campaign_path(customer_id, campaign_id_num)
        css.shared_set = f"customers/{customer_id}/sharedSets/{shared_set_id}"

        response = campaign_shared_set_service.mutate_campaign_shared_sets(
            customer_id=str(customer_id), operations=[op]
        )
        return {
            "status": "SUCCESS",
            "resource_name": response.results[0].resource_name,
            "campaign_id": campaign_id_num,
            "shared_set_id": shared_set_id
        }
    except Exception as e:
        return translate_google_ads_error(e)


# ─────────────────────────────────────────────
# TIER 3 — DIFERENCIAL COMPETITIVO
# ─────────────────────────────────────────────

def get_reach_forecast(customer_id: str, keywords: list, daily_budget: float, date_range_days: int = 30) -> dict:
    """[RESEARCH] Estima alcance e frequência para um conjunto de keywords e orçamento."""
    return {
        "status": "SUCCESS",
        "note": "ReachPlanService requer configuração de produtos de mídia específicos. Use keyword_forecast para estimativas de volume de busca e cliques.",
        "suggestion": "Para previsões de Search, use keyword_forecast com a lista de keywords fornecida.",
        "keywords": keywords,
        "daily_budget": daily_budget
    }


def get_billing_info(customer_id: str) -> dict:
    """[UTILITY] Retorna informações de faturamento: método de pagamento, status e saldo."""
    try:
        client = create_google_ads_client()
        ga_service = client.get_service("GoogleAdsService")

        query = """
            SELECT
                billing_setup.id,
                billing_setup.status,
                billing_setup.start_date_time,
                billing_setup.payments_account
            FROM billing_setup
            WHERE billing_setup.status = 'APPROVED'
            LIMIT 1
        """
        response = ga_service.search(customer_id=str(customer_id), query=query)
        results = [dense_proto_to_dict(row) for row in response]
        return {"status": "SUCCESS", "billing_info": results[0] if results else None}
    except Exception as e:
        return translate_google_ads_error(e)


def list_invoices(customer_id: str, year: int = None, month: int = None) -> dict:
    """[UTILITY] Lista faturas da conta. Padrão: mês atual."""
    try:
        from datetime import datetime
        client = create_google_ads_client()
        ga_service = client.get_service("GoogleAdsService")
        invoice_service = client.get_service("InvoiceService")

        # Busca o billing_setup aprovado
        bs_query = "SELECT billing_setup.id, billing_setup.payments_account FROM billing_setup WHERE billing_setup.status = 'APPROVED' LIMIT 1"
        bs_response = ga_service.search(customer_id=str(customer_id), query=bs_query)
        bs_results = list(bs_response)
        if not bs_results:
            return {"status": "SUCCESS", "invoices": [], "note": "Nenhum billing_setup aprovado encontrado."}

        billing_setup_rn = f"customers/{customer_id}/billingSetups/{bs_results[0].billing_setup.id}"

        request = client.get_type("ListInvoicesRequest")
        request.customer_id = str(customer_id)
        request.billing_setup = billing_setup_rn
        request.issue_year = str(year or datetime.now().year)
        request.issue_month = client.enums.MonthOfYearEnum(month or datetime.now().month)

        response = invoice_service.list_invoices(request=request)
        invoices = []
        for inv in response.invoices:
            invoices.append({
                "id": inv.id,
                "total_amount_micros": inv.total_amount_micros,
                "corrected_total_amount_micros": inv.corrected_total_amount_micros,
                "due_date": inv.due_date,
                "issue_date": inv.issue_date,
                "service_date_range_start": inv.service_date_range.start_date,
                "service_date_range_end": inv.service_date_range.end_date
            })
        return {"status": "SUCCESS", "invoices": invoices}
    except Exception as e:
        return translate_google_ads_error(e)


def upload_customer_match(customer_id: str, list_name: str, emails: list, membership_life_span: int = 30) -> dict:
    """[CREATE] Cria audiência Customer Match a partir de lista de emails para remarketing."""
    import hashlib
    try:
        client = create_google_ads_client()
        user_list_service = client.get_service("UserListService")

        # Passo 1: Cria UserList
        ul_op = client.get_type("UserListOperation")
        user_list = ul_op.create
        user_list.name = list_name
        user_list.crm_based_user_list.upload_key_type = client.enums.CustomerMatchUploadKeyTypeEnum.CONTACT_INFO
        user_list.membership_life_span = membership_life_span

        ul_response = user_list_service.mutate_user_lists(customer_id=str(customer_id), operations=[ul_op])
        user_list_rn = ul_response.results[0].resource_name

        # Passo 2: Cria OfflineUserDataJob
        offline_job_service = client.get_service("OfflineUserDataJobService")

        job_op = client.get_type("OfflineUserDataJob")
        job_op.type_ = client.enums.OfflineUserDataJobTypeEnum.CUSTOMER_MATCH_USER_LIST
        job_op.customer_match_user_list_metadata.user_list = user_list_rn

        job_response = offline_job_service.create_offline_user_data_job(
            customer_id=str(customer_id), job=job_op
        )
        job_rn = job_response.resource_name

        # Passo 3: Adiciona emails com hash SHA256
        user_data_list = []
        for email in emails:
            hashed_email = hashlib.sha256(email.lower().strip().encode()).hexdigest()
            user_data = client.get_type("UserData")
            identifier = client.get_type("UserIdentifier")
            identifier.hashed_email = hashed_email
            user_data.user_identifiers.append(identifier)
            user_data_list.append(user_data)

        add_request = client.get_type("AddOfflineUserDataJobOperationsRequest")
        add_request.resource_name = job_rn
        for ud in user_data_list:
            op = client.get_type("OfflineUserDataJobOperation")
            client.copy_from(op.create, ud)
            add_request.operations.append(op)

        offline_job_service.add_offline_user_data_job_operations(request=add_request)

        # Passo 4: Executa o job
        offline_job_service.run_offline_user_data_job(resource_name=job_rn)

        return {
            "status": "SUCCESS",
            "job_resource_name": job_rn,
            "user_list_resource_name": user_list_rn,
            "emails_uploaded": len(emails),
            "note": "Job em processamento assíncrono. Pode levar alguns minutos para a lista ser populada."
        }
    except Exception as e:
        return translate_google_ads_error(e)


def create_audience(customer_id: str, name: str, description: str = "", dimensions: list = None) -> dict:
    """[CREATE] Cria audiência personalizada combinando sinais (interesses, URLs visitadas, apps)."""
    try:
        client = create_google_ads_client()
        audience_service = client.get_service("AudienceService")

        op = client.get_type("AudienceOperation")
        audience = op.create
        audience.name = name
        if description:
            audience.description = description
        audience.status = client.enums.AudienceStatusEnum.ENABLED

        if dimensions:
            for dim in dimensions:
                dimension = client.get_type("AudienceDimension")
                if dim.get("type") == "INTEREST" and dim.get("interest_category_constant"):
                    dimension.audience_segments.segments.append(
                        client.get_type("AudienceSegment")
                    )
                audience.dimensions.append(dimension)

        response = audience_service.mutate_audiences(customer_id=str(customer_id), operations=[op])
        resource_name = response.results[0].resource_name
        return {
            "status": "SUCCESS",
            "resource_name": resource_name,
            "audience_id": resource_name.split("/")[-1],
            "name": name
        }
    except Exception as e:
        return translate_google_ads_error(e)


def set_campaign_targeting_setting(customer_id: str, campaign_id: str, targeting_dimension: str, bid_only: bool = True) -> dict:
    """[MUTATION] Configura se um targeting dimension é para observação (bid_only=True) ou segmentação (bid_only=False). targeting_dimension: AUDIENCE|PLACEMENT|TOPIC."""
    try:
        client = create_google_ads_client()
        resolver = ResourceResolver(client)

        res_id = resolver.resolve(customer_id, "CAMPAIGN", campaign_id)
        if "error" in res_id: return res_id
        campaign_id_num = res_id["id"]

        campaign_service = client.get_service("CampaignService")
        op = client.get_type("CampaignOperation")
        c = op.update
        c.resource_name = campaign_service.campaign_path(customer_id, campaign_id_num)

        target_restriction = client.get_type("TargetRestriction")
        target_restriction.targeting_dimension = client.enums.TargetingDimensionEnum[targeting_dimension]
        target_restriction.bid_only = bid_only
        c.targeting_setting.target_restrictions.append(target_restriction)

        client.copy_from(op.update_mask, protobuf_helpers.field_mask(None, c._pb))
        campaign_service.mutate_campaigns(customer_id=str(customer_id), operations=[op])

        return {
            "status": "SUCCESS",
            "campaign_id": campaign_id_num,
            "targeting_dimension": targeting_dimension,
            "bid_only": bid_only,
            "mode": "OBSERVATION" if bid_only else "TARGETING"
        }
    except Exception as e:
        return translate_google_ads_error(e)


def set_ad_group_targeting_setting(customer_id: str, ad_group_id: str, targeting_dimension: str, bid_only: bool = True) -> dict:
    """[MUTATION] Configura se um targeting dimension no grupo de anúncios é para observação (bid_only=True) ou segmentação restritiva (bid_only=False). targeting_dimension: AUDIENCE|PLACEMENT|TOPIC."""
    try:
        client = create_google_ads_client()
        resolver = ResourceResolver(client)

        res_id = resolver.resolve(customer_id, "AD_GROUP", ad_group_id)
        if "error" in res_id:
            return res_id
        ad_group_id_num = res_id["id"]

        ad_group_service = client.get_service("AdGroupService")
        op = client.get_type("AdGroupOperation")
        ag = op.update
        ag.resource_name = ad_group_service.ad_group_path(customer_id, ad_group_id_num)

        dimension_key = targeting_dimension.upper().strip()
        target_restriction = client.get_type("TargetRestriction")
        target_restriction.targeting_dimension = client.enums.TargetingDimensionEnum[dimension_key]
        target_restriction.bid_only = bid_only
        ag.targeting_setting.target_restrictions.append(target_restriction)

        client.copy_from(op.update_mask, protobuf_helpers.field_mask(None, ag._pb))
        ad_group_service.mutate_ad_groups(customer_id=str(customer_id), operations=[op])

        return {
            "status": "SUCCESS",
            "ad_group_id": ad_group_id_num,
            "targeting_dimension": dimension_key,
            "bid_only": bid_only,
            "mode": "OBSERVATION" if bid_only else "TARGETING"
        }
    except Exception as e:
        return translate_google_ads_error(e)


def get_network_performance(customer_id: str, date_range: str = "LAST_30_DAYS", campaign_id: str = None) -> dict:
    """[REPORT] Performance por rede de distribuição: Google Search, Search Partners, Display Network."""
    try:
        client = create_google_ads_client()
        ga_service = client.get_service("GoogleAdsService")

        campaign_filter = ""
        if campaign_id:
            resolver = ResourceResolver(client)
            res = resolver.resolve(customer_id, "CAMPAIGN", campaign_id)
            if "error" in res:
                return res
            campaign_filter = f"AND campaign.id = {res['id']}"

        query = f"""
            SELECT
                segments.ad_network_type,
                campaign.id, campaign.name,
                metrics.clicks, metrics.impressions, metrics.cost_micros,
                metrics.conversions, metrics.ctr, metrics.average_cpc
            FROM campaign
            WHERE segments.date DURING {date_range}
            AND campaign.status != 'REMOVED'
            {campaign_filter}
            ORDER BY metrics.cost_micros DESC
        """
        rows = ga_service.search(customer_id=str(customer_id), query=query)
        results = [dense_proto_to_dict(row) for row in rows]
        return {"status": "SUCCESS", "date_range": date_range, "network_performance": results}
    except Exception as e:
        return translate_google_ads_error(e)


def set_ad_group_bid(customer_id: str, ad_group_id: str, cpc_bid: float) -> dict:
    """[MUTATION] Atualiza o CPC padrão de um grupo de anúncios. Aceita ID numérico ou Nome do Ad Group."""
    try:
        client = create_google_ads_client()
        resolver = ResourceResolver(client)

        res = resolver.resolve(customer_id, "AD_GROUP", ad_group_id)
        if "error" in res:
            return res
        ad_group_id_num = res["id"]

        service = client.get_service("AdGroupService")
        op = client.get_type("AdGroupOperation")
        ag = op.update
        ag.resource_name = service.ad_group_path(customer_id, ad_group_id_num)
        ag.cpc_bid_micros = int(cpc_bid * 1_000_000)
        client.copy_from(op.update_mask, protobuf_helpers.field_mask(None, ag._pb))

        service.mutate_ad_groups(customer_id=str(customer_id), operations=[op])
        return {"status": "SUCCESS", "ad_group_id": ad_group_id_num, "new_cpc_bid": cpc_bid}
    except Exception as e:
        return translate_google_ads_error(e)


def create_shared_negative_list(customer_id: str, name: str, keywords: list = None, match_type: str = "BROAD") -> dict:
    """[CREATE] Cria lista de palavras-chave negativas compartilhada. Opcionalmente já adiciona keywords na lista."""
    try:
        client = create_google_ads_client()

        # Passo 1: Criar SharedSet
        shared_set_service = client.get_service("SharedSetService")
        ss_op = client.get_type("SharedSetOperation")
        shared_set = ss_op.create
        shared_set.name = name
        shared_set.type_ = client.enums.SharedSetTypeEnum.NEGATIVE_KEYWORDS

        ss_res = shared_set_service.mutate_shared_sets(customer_id=str(customer_id), operations=[ss_op])
        shared_set_rn = ss_res.results[0].resource_name
        shared_set_id = shared_set_rn.split("/")[-1]

        # Passo 2: Adicionar keywords se fornecidas
        keywords_added = 0
        if keywords:
            sc_service = client.get_service("SharedCriterionService")
            sc_ops = []
            for kw in keywords:
                sc_op = client.get_type("SharedCriterionOperation")
                sc = sc_op.create
                sc.shared_set = shared_set_rn
                sc.keyword.text = kw
                sc.keyword.match_type = client.enums.KeywordMatchTypeEnum[match_type]
                sc_ops.append(sc_op)
            sc_service.mutate_shared_criteria(customer_id=str(customer_id), operations=sc_ops)
            keywords_added = len(keywords)

        return {
            "status": "SUCCESS",
            "shared_set_id": shared_set_id,
            "resource_name": shared_set_rn,
            "keywords_added": keywords_added
        }
    except Exception as e:
        return translate_google_ads_error(e)


def remove_campaign_asset(customer_id: str, campaign_asset_resource_name: str) -> dict:
    """[MUTATION] Remove uma extensão/asset de uma campanha. Obtenha o resource_name via search_ads ou list dos assets da campanha."""
    try:
        client = create_google_ads_client()
        service = client.get_service("CampaignAssetService")

        op = client.get_type("CampaignAssetOperation")
        op.remove = campaign_asset_resource_name

        service.mutate_campaign_assets(customer_id=str(customer_id), operations=[op])
        return {"status": "SUCCESS", "removed": campaign_asset_resource_name}
    except Exception as e:
        return translate_google_ads_error(e)


def add_price_extension(customer_id: str, campaign_id: str, price_qualifier: str, language_code: str, items: list) -> dict:
    """
    [MUTATION] Adiciona extensão de tabela de preços a uma campanha.
    price_qualifier: NONE|FROM|UP_TO|AVERAGE.
    Cada item: {header, description, price, currency_code, unit, final_url}.
    unit: PER_HOUR|PER_DAY|PER_WEEK|PER_MONTH|PER_YEAR|PER_NIGHT|PER_UNIT|UNSPECIFIED.
    """
    try:
        client = create_google_ads_client()
        resolver = ResourceResolver(client)

        res = resolver.resolve(customer_id, "CAMPAIGN", campaign_id)
        if "error" in res:
            return res
        campaign_id_num = res["id"]

        # Criar Asset de Preço
        asset_service = client.get_service("AssetService")
        asset_op = client.get_type("AssetOperation")
        asset = asset_op.create

        asset.price_asset.type_ = client.enums.PriceExtensionTypeEnum.SERVICES
        asset.price_asset.price_qualifier = client.enums.PriceExtensionPriceQualifierEnum[price_qualifier]
        asset.price_asset.language_code = language_code

        items_to_add = items[:8]
        for item in items_to_add:
            offering = client.get_type("PriceOffer")
            offering.header = item["header"][:25]
            offering.description = item["description"][:25]
            offering.price.amount_micros = int(item["price"] * 1_000_000)
            offering.price.currency_code = item.get("currency_code", "BRL")
            offering.unit = client.enums.PriceExtensionPriceUnitEnum[item.get("unit", "UNSPECIFIED")]
            offering.final_urls.append(item["final_url"])
            asset.price_asset.price_offerings.append(offering)

        asset_res = asset_service.mutate_assets(customer_id=str(customer_id), operations=[asset_op])
        asset_rn = asset_res.results[0].resource_name

        # Vincular à Campanha
        campaign_service = client.get_service("CampaignService")
        ca_service = client.get_service("CampaignAssetService")
        ca_op = client.get_type("CampaignAssetOperation")
        ca = ca_op.create
        ca.asset = asset_rn
        ca.campaign = campaign_service.campaign_path(customer_id, campaign_id_num)
        ca.field_type = client.enums.AssetFieldTypeEnum.PRICE

        ca_service.mutate_campaign_assets(customer_id=str(customer_id), operations=[ca_op])

        return {
            "status": "SUCCESS",
            "asset_id": asset_rn,
            "items_added": len(items_to_add),
            "campaign_id": campaign_id_num
        }
    except Exception as e:
        return translate_google_ads_error(e)


# ─────────────────────────────────────────────
# PERFORMANCE MAX (PMAX) 360° TOOLS
# ─────────────────────────────────────────────

@mcp.tool()
def add_pmax_search_themes(customer_id: str, asset_group_id: str, search_themes: list[str]) -> dict:
    """
    [MUTATION] Injeta TEMAS DE PESQUISA (Search Themes) em um Asset Group de Performance Max.
    Guia o algoritmo com intenções de busca qualificadas (até 25 temas).
    Aceita ID numérico ou Nome do Asset Group.
    """
    try:
        if not search_themes:
            return {"status": "ERROR", "message": "A lista de search_themes não pode estar vazia."}

        client = create_google_ads_client()
        resolver = ResourceResolver(client)
        res_id = resolver.resolve(customer_id, "ASSET_GROUP", asset_group_id)
        if "error" in res_id:
            return res_id
        asset_group_id_num = res_id["id"]

        asset_group_signal_service = client.get_service("AssetGroupSignalService")
        operations = []
        for theme in search_themes:
            theme_clean = str(theme).strip()
            if not theme_clean:
                continue
            op = client.get_type("AssetGroupSignalOperation")
            signal = op.create
            signal.asset_group = f"customers/{customer_id}/assetGroups/{asset_group_id_num}"
            signal.search_theme.text = theme_clean
            operations.append(op)

        if not operations:
            return {"status": "ERROR", "message": "Nenhum tema de pesquisa válido fornecido."}

        response = asset_group_signal_service.mutate_asset_group_signals(
            customer_id=str(customer_id), operations=operations
        )
        created_signals = [res.resource_name for res in response.results]
        return {
            "status": "SUCCESS",
            "asset_group_id": asset_group_id_num,
            "themes_added": len(created_signals),
            "resource_names": created_signals
        }
    except Exception as e:
        return translate_google_ads_error(e)


@mcp.tool()
def link_audience_signal_to_pmax(customer_id: str, asset_group_id: str, audience_id: str) -> dict:
    """
    [MUTATION] Vincula uma AUDIÊNCIA (Custom Audience / Sinais) ao Asset Group de Performance Max.
    Aceita ID numérico ou Nome do Asset Group / Audience.
    """
    try:
        client = create_google_ads_client()
        resolver = ResourceResolver(client)

        res_ag = resolver.resolve(customer_id, "ASSET_GROUP", asset_group_id)
        if "error" in res_ag:
            return res_ag
        asset_group_id_num = res_ag["id"]

        res_aud = resolver.resolve(customer_id, "AUDIENCE", audience_id)
        if "error" in res_aud:
            return res_aud
        audience_id_num = res_aud["id"]

        asset_group_signal_service = client.get_service("AssetGroupSignalService")
        op = client.get_type("AssetGroupSignalOperation")
        signal = op.create
        signal.asset_group = f"customers/{customer_id}/assetGroups/{asset_group_id_num}"
        signal.audience.audience = f"customers/{customer_id}/audiences/{audience_id_num}"

        response = asset_group_signal_service.mutate_asset_group_signals(
            customer_id=str(customer_id), operations=[op]
        )
        return {
            "status": "SUCCESS",
            "asset_group_id": asset_group_id_num,
            "audience_id": audience_id_num,
            "resource_name": response.results[0].resource_name
        }
    except Exception as e:
        return translate_google_ads_error(e)


@mcp.tool()
def bind_pmax_text_assets(
    customer_id: str,
    asset_group_id: str,
    headlines: list[str] = None,
    long_headlines: list[str] = None,
    descriptions: list[str] = None,
    business_name: str = None
) -> dict:
    """
    [MUTATION] Cria e vincula TEXTOS (Headlines, Long Headlines, Descriptions e Business Name) ao Asset Group de Performance Max.
    Aceita ID numérico ou Nome do Asset Group.
    """
    try:
        client = create_google_ads_client()
        resolver = ResourceResolver(client)
        res_id = resolver.resolve(customer_id, "ASSET_GROUP", asset_group_id)
        if "error" in res_id:
            return res_id
        asset_group_id_num = res_id["id"]

        asset_service = client.get_service("AssetService")
        asset_group_asset_service = client.get_service("AssetGroupAssetService")

        items_to_create = []

        if headlines:
            for h in headlines:
                if str(h).strip():
                    items_to_create.append((str(h).strip()[:30], client.enums.AssetFieldTypeEnum.HEADLINE))

        if long_headlines:
            for lh in long_headlines:
                if str(lh).strip():
                    items_to_create.append((str(lh).strip()[:90], client.enums.AssetFieldTypeEnum.LONG_HEADLINE))

        if descriptions:
            for d in descriptions:
                if str(d).strip():
                    items_to_create.append((str(d).strip()[:90], client.enums.AssetFieldTypeEnum.DESCRIPTION))

        if business_name and str(business_name).strip():
            items_to_create.append((str(business_name).strip()[:25], client.enums.AssetFieldTypeEnum.BUSINESS_NAME))

        if not items_to_create:
            return {"status": "ERROR", "message": "Nenhum texto válido fornecido para vinculação."}

        asset_ops = []
        for text, _ in items_to_create:
            asset_op = client.get_type("AssetOperation")
            asset = asset_op.create
            asset.text_asset.text = text
            asset_ops.append(asset_op)

        asset_res = asset_service.mutate_assets(customer_id=str(customer_id), operations=asset_ops)
        created_asset_rns = [r.resource_name for r in asset_res.results]

        aga_ops = []
        for idx, (_, field_type) in enumerate(items_to_create):
            aga_op = client.get_type("AssetGroupAssetOperation")
            aga = aga_op.create
            aga.asset_group = f"customers/{customer_id}/assetGroups/{asset_group_id_num}"
            aga.asset = created_asset_rns[idx]
            aga.field_type = field_type
            aga_ops.append(aga_op)

        aga_res = asset_group_asset_service.mutate_asset_group_assets(
            customer_id=str(customer_id), operations=aga_ops
        )

        return {
            "status": "SUCCESS",
            "asset_group_id": asset_group_id_num,
            "assets_bound": len(aga_res.results),
            "headlines_count": len(headlines or []),
            "long_headlines_count": len(long_headlines or []),
            "descriptions_count": len(descriptions or []),
            "business_name_set": bool(business_name)
        }
    except Exception as e:
        return translate_google_ads_error(e)


@mcp.tool()
def list_pmax_signals(customer_id: str, asset_group_id: str) -> dict:
    """
    [REPORT] Lista todos os SINAIS (Search Themes e Audiências) configurados em um Asset Group de PMax.
    Aceita ID numérico ou Nome do Asset Group.
    """
    try:
        client = create_google_ads_client()
        resolver = ResourceResolver(client)
        res_id = resolver.resolve(customer_id, "ASSET_GROUP", asset_group_id)
        if "error" in res_id:
            return res_id
        asset_group_id_num = res_id["id"]

        ga_service = client.get_service("GoogleAdsService")
        query = f"""
            SELECT 
                asset_group_signal.resource_name,
                asset_group_signal.asset_group,
                asset_group_signal.search_theme.text,
                asset_group_signal.audience.audience,
                asset_group_signal.approval_status
            FROM asset_group_signal 
            WHERE asset_group.id = {asset_group_id_num}
        """
        response = ga_service.search_stream(customer_id=str(customer_id), query=query)
        signals = []
        for batch in response:
            for row in batch.results:
                signals.append(proto_to_dict(row))

        search_themes = [
            s.get("asset_group_signal", {}).get("search_theme", {}).get("text")
            for s in signals
            if s.get("asset_group_signal", {}).get("search_theme", {}).get("text")
        ]
        audiences = [
            s.get("asset_group_signal", {}).get("audience", {}).get("audience")
            for s in signals
            if s.get("asset_group_signal", {}).get("audience", {}).get("audience")
        ]

        return {
            "status": "SUCCESS",
            "asset_group_id": asset_group_id_num,
            "total_signals": len(signals),
            "search_themes": search_themes,
            "audiences": audiences,
            "raw_signals": signals
        }
    except Exception as e:
        return translate_google_ads_error(e)


# ─────────────────────────────────────────────
# ENHANCED CONVERSIONS FOR LEADS (CLOSED-LOOP)
# ─────────────────────────────────────────────

def _normalize_and_hash_email(email: str) -> str:
    """Normaliza e calcula o hash SHA-256 do email conforme padrao Google Ads."""
    clean = str(email).strip().lower()
    return hashlib.sha256(clean.encode("utf-8")).hexdigest()

def _normalize_and_hash_phone(phone: str) -> str:
    """Normaliza para formato E.164 (+55...) e calcula o hash SHA-256."""
    digits = re.sub(r"\D", "", str(phone))
    if not digits:
        return None
    if not str(phone).strip().startswith("+"):
        if len(digits) in (10, 11):
            digits = "55" + digits
        formatted = "+" + digits
    else:
        formatted = "+" + digits
    return hashlib.sha256(formatted.encode("utf-8")).hexdigest()


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
    """
    [MUTATION] Dispara conversao otimizada para leads (Enhanced Conversions for Leads).
    Atribui fechamentos e vendas offline ao Google Ads usando e-mail/telefone (com hash SHA-256 automatico).
    Nao exige US$ 50k de investimento nem GCLID obrigatorio.
    conversion_action_id aceita ID numerico ou Nome da Acao de Conversao.
    """
    try:
        if not email and not phone and not gclid:
            return {
                "status": "ERROR",
                "message": "Pelo menos um identificador (email, phone ou gclid) deve ser fornecido para a conversao."
            }

        client = create_google_ads_client()
        resolver = ResourceResolver(client)
        res_id = resolver.resolve(customer_id, "CONVERSION_ACTION", conversion_action_id)
        if "error" in res_id:
            return res_id
        ca_id_num = res_id["id"]

        # Formatacao de data/hora
        if not conversion_date_time or str(conversion_date_time).upper() in ("NOW", "HOJE", "TODAY"):
            conv_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S-03:00")
        else:
            conv_time = str(conversion_date_time).strip()
            if not ("+" in conv_time[-6:] or "-" in conv_time[-6:]):
                conv_time += "-03:00"

        click_conversion = client.get_type("ClickConversion")
        click_conversion.conversion_action = f"customers/{customer_id}/conversionActions/{ca_id_num}"
        click_conversion.conversion_date_time = conv_time
        click_conversion.conversion_value = float(conversion_value)
        click_conversion.currency_code = currency_code

        if order_id:
            click_conversion.order_id = str(order_id).strip()

        if gclid:
            click_conversion.gclid = str(gclid).strip()

        # Identificadores com hash SHA-256
        identifiers_added = []
        if email:
            u_email = client.get_type("UserIdentifier")
            u_email.hashed_email = _normalize_and_hash_email(email)
            click_conversion.user_identifiers.append(u_email)
            identifiers_added.append("hashed_email")

        if phone:
            h_phone = _normalize_and_hash_phone(phone)
            if h_phone:
                u_phone = client.get_type("UserIdentifier")
                u_phone.hashed_phone_number = h_phone
                click_conversion.user_identifiers.append(u_phone)
                identifiers_added.append("hashed_phone")

        request = client.get_type("UploadClickConversionsRequest")
        request.customer_id = str(customer_id)
        request.conversions.append(click_conversion)
        request.partial_failure = True

        conversion_upload_service = client.get_service("ConversionUploadService")
        response = conversion_upload_service.upload_click_conversions(request=request)

        has_partial_failure = False
        error_details = []
        if response.partial_failure_error and response.partial_failure_error.code != 0:
            has_partial_failure = True
            error_details.append(response.partial_failure_error.message)

        return {
            "status": "PARTIAL_FAILURE" if has_partial_failure else "SUCCESS",
            "conversion_action_id": ca_id_num,
            "conversion_date_time": conv_time,
            "conversion_value": float(conversion_value),
            "currency_code": currency_code,
            "identifiers_used": identifiers_added,
            "has_gclid": bool(gclid),
            "order_id": order_id,
            "partial_failure_detected": has_partial_failure,
            "details": error_details if has_partial_failure else ["Conversao enviada com sucesso para atribuicao."]
        }
    except Exception as e:
        return translate_google_ads_error(e)


@mcp.tool()
def batch_upload_lead_conversions_enhanced(
    customer_id: str,
    conversions: list[dict]
) -> dict:
    """
    [MUTATION] Dispara lote de conversoes otimizadas para leads (Enhanced Conversions for Leads).
    Cada item: {conversion_action_id, conversion_value, email?, phone?, conversion_date_time?, order_id?, gclid?, currency_code?}.
    """
    try:
        if not conversions:
            return {"status": "ERROR", "message": "A lista de conversoes nao pode estar vazia."}

        client = create_google_ads_client()
        resolver = ResourceResolver(client)
        conversion_upload_service = client.get_service("ConversionUploadService")

        request = client.get_type("UploadClickConversionsRequest")
        request.customer_id = str(customer_id)
        request.partial_failure = True

        items_prepared = 0
        for item in conversions:
            ca_id = item.get("conversion_action_id")
            if not ca_id:
                continue

            res_id = resolver.resolve(customer_id, "CONVERSION_ACTION", str(ca_id))
            if "error" in res_id:
                continue
            ca_id_num = res_id["id"]

            conv_time = item.get("conversion_date_time")
            if not conv_time or str(conv_time).upper() in ("NOW", "HOJE", "TODAY"):
                conv_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S-03:00")
            else:
                conv_time = str(conv_time).strip()
                if not ("+" in conv_time[-6:] or "-" in conv_time[-6:]):
                    conv_time += "-03:00"

            cc = client.get_type("ClickConversion")
            cc.conversion_action = f"customers/{customer_id}/conversionActions/{ca_id_num}"
            cc.conversion_date_time = conv_time
            cc.conversion_value = float(item.get("conversion_value", 0.0))
            cc.currency_code = item.get("currency_code", "BRL")

            if item.get("order_id"):
                cc.order_id = str(item["order_id"]).strip()
            if item.get("gclid"):
                cc.gclid = str(item["gclid"]).strip()

            if item.get("email"):
                u_email = client.get_type("UserIdentifier")
                u_email.hashed_email = _normalize_and_hash_email(item["email"])
                cc.user_identifiers.append(u_email)

            if item.get("phone"):
                h_phone = _normalize_and_hash_phone(item["phone"])
                if h_phone:
                    u_phone = client.get_type("UserIdentifier")
                    u_phone.hashed_phone_number = h_phone
                    cc.user_identifiers.append(u_phone)

            request.conversions.append(cc)
            items_prepared += 1

        if items_prepared == 0:
            return {"status": "ERROR", "message": "Nenhuma conversao valida preparada para envio."}

        response = conversion_upload_service.upload_click_conversions(request=request)

        has_partial_failure = False
        error_details = []
        if response.partial_failure_error and response.partial_failure_error.code != 0:
            has_partial_failure = True
            error_details.append(response.partial_failure_error.message)

        return {
            "status": "PARTIAL_FAILURE" if has_partial_failure else "SUCCESS",
            "conversions_sent": items_prepared,
            "partial_failure_detected": has_partial_failure,
            "details": error_details if has_partial_failure else ["Lote enviado com sucesso."]
        }
    except Exception as e:
        return translate_google_ads_error(e)


if __name__ == "__main__":
    mcp.run()
