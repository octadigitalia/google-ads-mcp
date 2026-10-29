# Audit Workflow - Referência Rápida

> Este arquivo é uma referência de consulta. A lógica completa de orquestração está em `google-ads-expert.md`.

## Auditoria Completa (ordem recomendada)

```
1. get_account_snapshot(customer_id)           → saúde geral e top 5 campanhas
2. get_campaign_performance(LAST_30_DAYS)       → ranking de performance
3. get_keyword_performance(customer_id)         → Quality Scores e CPC
4. get_search_terms(customer_id, min_clicks=5)  → desperdício
5. get_auction_insights(customer_id)            → posição vs concorrentes
6. get_device_performance(customer_id)          → mobile vs desktop
7. get_ad_performance(customer_id)              → força dos RSAs
8. get_recommendations(customer_id)             → sugestões do Google
```

## Diagnóstico por Sintoma

| Sintoma | Tools para investigar |
|---------|----------------------|
| CPA subindo | get_search_terms + get_keyword_performance |
| ROAS caindo | get_auction_insights + get_device_performance |
| Impressões caindo | get_keyword_performance (QS) + get_recommendations |
| Budget esgotando rápido | get_search_terms + get_hourly_performance |
| Sem conversões | get_landing_page_performance + get_ad_performance |
| Alta variação dia a dia | get_hourly_performance + get_change_history |

## Regras Operacionais

1. **Name-to-ID**: Passe nomes de campanha diretamente - o servidor resolve o ID
2. **Ambiguidade**: Se houver múltiplas campanhas com o mesmo nome, peça o ID numérico
3. **Confirmação**: Nunca execute mutações sem mostrar os dados e pedir confirmação
4. **Log**: Registre toda mutação em `campaign-log/{customer_id}.md`
