# Google Ads Expert MCP Server

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white)](https://python.org)
[![FastMCP](https://img.shields.io/badge/MCP-FastMCP-purple)](https://github.com/modelcontextprotocol)
[![Google Ads API](https://img.shields.io/badge/Google%20Ads%20API-v23-green?logo=google-ads&logoColor=white)](https://developers.google.com/google-ads/api)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?logo=docker&logoColor=white)](https://docker.com)
[![Coolify](https://img.shields.io/badge/Deploy-Coolify-blueviolet)](https://coolify.io)
[![Status](https://img.shields.io/badge/Status-Production%20Hardened-success)](#)

Servidor **Model Context Protocol (MCP)** de nível empresarial para gestão autônoma de contas do Google Ads via Inteligência Artificial (Antigravity, Cursor, Claude Code, Claude Desktop e agentes autônomos).

Integra diretamente com a **Google Ads API (v23)** disponibilizando **92 ferramentas atômicas e de inteligência operacional**, cobrindo desde auditorias 360° com diagnóstico preventivo de suspensão até criação completa de campanhas PMax/Search, controle de orçamentos, inteligência competitiva e conversões otimizadas para leads (Enhanced Conversions).

---

## 🚀 Destaques da Versão Atual (92 Tools)

* **🛡️ Blindagem & Diagnóstico 360° de Conta:** Detecção proativa de **Verificação de Identidade do Anunciante** (deadlines, risco de pausa e URL de ação), alertas críticos de faturamento, suspensão e motivos de bloqueio de veiculação (`campaign.primary_status_reasons`).
* **📊 Pacing Financeiro & Run Rate:** Ferramenta dedicada para monitorar a velocidade de consumo da verba no mês corrente (`THIS_MONTH`), projeção de fechamento (*burn rate*) e cálculo do orçamento diário ideal para evitar estouros ou sub-investimento.
* **🎯 Performance Max (PMax) 360°:** Criação completa de PMax, injeção de **Search Themes**, vinculação de sinais de audiência (*Audience Signals*) e binding automatizado de assets de texto (Headlines, Long Headlines, Descriptions).
* **🔍 Radar Competitivo no Leilão:** Comparação temporal automática (últimos 7 dias vs. últimos 30 dias) para identificar novos concorrentes no leilão (`NEW_ENTRANT`) e concorrentes com alta agressiva de lances (`SURGING_AGGRESSIVE`).
* **⚖️ Raio-X de Políticas & Recursos:** Auditoria cirúrgica de anúncios reprovados (`DISAPPROVED`), limitados (`APPROVED_LIMITED`) e em análise de recurso (`UNDER_APPEAL`), mapeando tópicos de política violados.
* **⚡ Closed-Loop & Enhanced Conversions:** Atribuição offline e Enhanced Conversions for Leads com normalização e hashing **SHA-256 nativo** de e-mails/telefones (individual ou em lote).
* **🌐 Hardened Cloud Deployment:** Pronto para operar 24/7 na nuvem via **Coolify** / Docker com transporte duplo: **Streamable HTTP** (`POST /mcp` com SSE chunked) e **SSE legado** (`GET /sse`), rate limiting in-memory e proteção anti-indexing.

---

## 🏛️ Arquitetura do Sistema

```
  Agentes de IA (Antigravity / Claude / Cursor)
                        │
                        │  Protocolo MCP (Streamable HTTP / SSE)
                        ▼
┌──────────────────────────────────────────────────────────┐
│         Hardened Worker Engine (start_worker.py)         │
│  • Rate Limiting (120 req/60s)  • Token Bearer Auth       │
│  • FastMCP Service Hub          • Healthcheck (/health)   │
└───────────────────────────┬──────────────────────────────┘
                            │ 92 Tools Expostas
                            ▼
┌──────────────────────────────────────────────────────────┐
│              MCP Server Layer (logic.py)                 │
│  • ResourceResolver (ID numérico ou Nome amigável)       │
│  • GAQL Linter & Dense Protobuf Serializer               │
│  • Lógica de Negócio, Pacing & Diagnósticos              │
└───────────────────────────┬──────────────────────────────┘
                            │ Google Ads API Client (v23)
                            ▼
               Google Ads API / Sua Conta MCC
```

---

## 🛠️ Catálogo Completo das 92 Ferramentas

### 1. Diagnóstico, Saúde da Conta & Políticas (7 tools)
| Ferramenta | Tipo | Descrição |
| :--- | :---: | :--- |
| `get_advertiser_verification_status` | REPORT | Status da Verificação de Identidade do Anunciante, deadlines e URL oficial para envio de documentos. |
| `get_account_alerts_and_notices` | REPORT | Diagnóstico 360° consolidando status da conta, billing, verificação e bloqueios operacionais. |
| `get_policy_violations_and_appeals` | REPORT | Detalha anúncios reprovados, limitados e em recurso (`UNDER_APPEAL`) com os tópicos de política. |
| `get_account_snapshot` | REPORT | Visão consolidada da conta: custo, cliques, conversões, ROAS e status das campanhas. |
| `get_account_capabilities` | REPORT | Audita recursos e recursos habilitados para a conta no Google Ads. |
| `get_change_history` | REPORT | Auditoria de histórico de alterações nos últimos N dias (quem alterou e o quê). |
| `get_recommendations` | REPORT | Lista recomendações oficiais do Google Ads com métricas de impacto estimadas. |

### 2. Gestão Financeira, Orçamento & Pacing (8 tools)
| Ferramenta | Tipo | Descrição |
| :--- | :---: | :--- |
| `get_budget_pacing_and_exhaustion` | REPORT | Análise de queima de verba mensal, projeção final e orçamento diário ideal sugerido. |
| `set_campaign_budget` | MUTATION | Atualiza o orçamento diário de uma campanha (em Reais). |
| `set_campaign_bid_ceiling` | MUTATION | Ajusta ou remove o teto de lance máximo de CPC em campanhas Maximizar Cliques (`TARGET_SPEND`). |
| `create_shared_budget` | MUTATION | Cria um orçamento compartilhado entre múltiplas campanhas. |
| `apply_shared_budget` | MUTATION | Aplica um orçamento compartilhado a uma campanha existente. |
| `create_bid_strategy` | MUTATION | Cria estratégia de lances de portfólio (Target CPA, Target ROAS, Max Conversions). |
| `apply_bid_strategy` | MUTATION | Vincula uma estratégia de portfólio a uma campanha. |
| `list_bid_strategies` | REPORT | Lista todas as estratégias de lance de portfólio cadastradas na conta. |

### 3. Concorrência & Inteligência de Leilão (2 tools)
| Ferramenta | Tipo | Descrição |
| :--- | :---: | :--- |
| `get_auction_competitor_drift` | REPORT | Radar comparativo de leilão (7d vs 30d): detecta novos concorrentes e subida de lances. |
| `get_auction_insights` | REPORT | Relatório clássico de informações de leilão (impression share, overlap rate, outranking share). |

### 4. Rastreamento, Conversões & Closed-Loop (6 tools)
| Ferramenta | Tipo | Descrição |
| :--- | :---: | :--- |
| `get_conversion_tracking_health` | REPORT | Audita integridade das tags de conversão; alerta ações primárias inativas ou sem disparos. |
| `list_conversion_actions` | REPORT | Lista todas as ações de conversão configuradas e status de contagem. |
| `create_conversion_action` | MUTATION | Cria uma nova ação de conversão na conta. |
| `upload_lead_conversion_enhanced` | MUTATION | Dispara conversão otimizada de leads (Enhanced Conversions) com hash SHA-256 nativo de dados pessoais. |
| `batch_upload_lead_conversions_enhanced` | MUTATION | Envio em lote de Enhanced Conversions para leads fechados offline. |
| `upload_offline_conversions` | MUTATION | Upload tradicional de conversões offline via GCLID. |

### 5. Performance Max (PMax) 360° (5 tools)
| Ferramenta | Tipo | Descrição |
| :--- | :---: | :--- |
| `create_pmax_campaign` | CREATE | Cria estrutura completa de campanha Performance Max. |
| `add_pmax_search_themes` | MUTATION | Injeta até 25 temas de pesquisa (*Search Themes*) em um Asset Group de PMax. |
| `link_audience_signal_to_pmax` | MUTATION | Vincula sinal de público-alvo (*Audience Signal*) ao Asset Group de PMax. |
| `bind_pmax_text_assets` | MUTATION | Vincula headlines, descrições e nome comercial ao Asset Group de PMax. |
| `list_pmax_signals` | REPORT | Lista todos os sinais (Search Themes e Audiências) configurados no Asset Group. |

### 6. Criação & Estrutura de Campanhas (5 tools)
| Ferramenta | Tipo | Descrição |
| :--- | :---: | :--- |
| `create_search_campaign` | CREATE | Cria campanha de Rede de Pesquisa padrão (criada pausada por segurança). |
| `create_full_campaign` | CREATE | Cria campanha, orçamento, grupo de anúncios, keywords e RSA em uma única chamada. |
| `create_campaign_structure` | CREATE | Gera estrutura completa de múltiplos grupos de anúncios e keywords. |
| `create_ad_group` | CREATE | Adiciona um novo grupo de anúncios a uma campanha. |
| `set_campaign_status` | MUTATION | Altera estado de veiculação da campanha (`ENABLED`, `PAUSED`, `REMOVED`). |

### 7. Anúncios, RSA & Criativos (3 tools)
| Ferramenta | Tipo | Descrição |
| :--- | :---: | :--- |
| `create_responsive_search_ad` | CREATE | Cria anúncio responsivo de pesquisa (RSA) com headlines e descrições. |
| `update_rsa_assets` | MUTATION | Atualiza textos e títulos de um RSA existente. |
| `upload_image_asset` | CREATE | Faz upload de imagem para a biblioteca de assets da conta. |

### 8. Palavras-Chave & Pesquisa de Demanda (9 tools)
| Ferramenta | Tipo | Descrição |
| :--- | :---: | :--- |
| `keyword_ideas` | RESEARCH | Gera ideias de palavras-chave com volume de buscas e concorrência via Keyword Planner. |
| `keyword_volume` | RESEARCH | Consulta volume de buscas histórico para uma lista específica de keywords. |
| `keyword_forecast` | RESEARCH | Previsão de cliques, impressões e custo para lista de keywords. |
| `get_reach_forecast` | RESEARCH | Estimativa rápida de alcance para keywords e orçamento diário. |
| `add_keywords` | MUTATION | Adiciona palavras-chave compráveis a um grupo de anúncios (Broad, Phrase, Exact). |
| `set_keyword_bid` | MUTATION | Ajusta o CPC individual de uma palavra-chave. |
| `bulk_pause_keywords` | MUTATION | Pausa em lote keywords de baixa performance (possui modo `dry_run` de segurança). |
| `replace_keywords_exact` | MUTATION | Substitui keywords de correspondência ampla para exata. |
| `get_search_terms` | REPORT | Relatório de termos reais de pesquisa acionados pelos usuários. |

### 9. Palavras-Chave Negativas (4 tools)
| Ferramenta | Tipo | Descrição |
| :--- | :---: | :--- |
| `add_negative_keywords` | MUTATION | Adiciona negativas diretamente a uma campanha. |
| `create_shared_negative_list` | CREATE | Cria lista de palavras-chave negativas compartilhada na conta. |
| `link_shared_negative_list` | MUTATION | Vincula lista compartilhada de negativas a uma campanha. |
| `get_shared_negative_lists` | REPORT | Lista todas as listas de negativas compartilhadas existentes. |

### 10. Audiências & Segmentação de Públicos (6 tools)
| Ferramenta | Tipo | Descrição |
| :--- | :---: | :--- |
| `list_user_lists` | REPORT | Lista públicos-alvo e listas de remarketing da conta. |
| `create_audience` | CREATE | Cria audiência personalizada combinando sinais de interesse e intenção. |
| `upload_customer_match` | CREATE | Cria audiência Customer Match a partir de lista de e-mails com hash SHA-256. |
| `link_audience_to_adgroup` | MUTATION | Vincula público-alvo a um grupo de anúncios com ajuste de lance opcional. |
| `remove_ad_group_criterion` | MUTATION | Desvincula/remove público-alvo ou critério restritivo de um grupo de anúncios. |
| `set_ad_group_targeting_setting` | MUTATION | Configura dimensão no grupo para **Observação** (`bid_only=True`) ou **Segmentação** (`bid_only=False`). |

### 11. Segmentação Geográfica, Dispositivos & Horários (6 tools)
| Ferramenta | Tipo | Descrição |
| :--- | :---: | :--- |
| `set_campaign_targeting_setting` | MUTATION | Configura dimensão na campanha para observação ou segmentação. |
| `set_location_targeting` | MUTATION | Define segmentação geográfica da campanha (inclusão e exclusão de locais). |
| `search_geo_targets` | UTILITY | Busca códigos de cidades, estados e países aceitos pela API do Google Ads. |
| `set_device_bid_adjustment` | MUTATION | Ajusta lances por dispositivo (Mobile, Desktop, Tablet). |
| `set_ad_schedule` | MUTATION | Configura horários e dias da semana para veiculação dos anúncios. |
| `set_language_targeting` | MUTATION | Configura os idiomas alvo da campanha. |

### 12. Extensões de Anúncio / Assets (7 tools)
| Ferramenta | Tipo | Descrição |
| :--- | :---: | :--- |
| `add_campaign_sitelinks` | MUTATION | Adiciona sitelinks com URLs e descrições a uma campanha. |
| `add_callout_extension` | MUTATION | Adiciona extensões de frase de destaque (callouts). |
| `add_structured_snippet` | MUTATION | Adiciona extensões de snippets estruturados (marcas, serviços, tipos). |
| `add_call_extension` | MUTATION | Adiciona extensão de chamada com número de telefone. |
| `add_price_extension` | MUTATION | Adiciona extensão de tabela de preços e produtos/serviços. |
| `add_promotion_extension` | MUTATION | Adiciona extensão de promoção com descontos e datas. |
| `remove_campaign_asset` | MUTATION | Remove uma extensão/asset vinculada a uma campanha. |

### 13. Relatórios Dimensionais & Análises (10 tools)
| Ferramenta | Tipo | Descrição |
| :--- | :---: | :--- |
| `get_campaign_performance` | REPORT | Performance comparativa detalhada por campanha. |
| `get_keyword_performance` | REPORT | Quality Score, CPC médio, CTR e conversões por palavra-chave. |
| `get_ad_performance` | REPORT | Performance individual de anúncios e títulos mais eficientes. |
| `get_asset_performance` | REPORT | Performance e índice de força dos assets criativos. |
| `get_device_performance` | REPORT | Segmentação de métricas por dispositivo (Computadores vs Celulares). |
| `get_geographic_performance` | REPORT | Performance por localização geográfica real dos usuários. |
| `get_hourly_performance` | REPORT | Distribuição de impressões, cliques e custo por hora do dia. |
| `get_network_performance` | REPORT | Comparativo de distribuição: Google Search vs Search Partners vs Display. |
| `get_landing_page_performance` | REPORT | Métricas de conversão e custo por URL de destino. |
| `get_demographic_insights` | REPORT | Desempenho segmentado por idade e gênero. |

### 14. Organização, Faturamento & Sistema (9 tools)
| Ferramenta | Tipo | Descrição |
| :--- | :---: | :--- |
| `check_connection` | UTILITY | Valida autenticação e prontidão operacional do servidor com a API. |
| `list_accounts` | UTILITY | Lista todas as contas acessíveis sob o MCC ou autenticação direta. |
| `run_setup` | SETUP | Inicia fluxo OAuth2 local para geração do refresh token. |
| `search_ads` | CUSTOM | Executa queries GAQL customizadas com linter integrado (escape hatch seguro). |
| `apply_recommendation` | MUTATION | Aplica uma recomendação automática do Google Ads via resource_name. |
| `dismiss_recommendation` | MUTATION | Descarta uma recomendação do painel do Google Ads. |
| `create_label` / `apply_label` / `list_labels` | MUTATION | Cria, aplica e lista etiquetas para categorização de entidades. |
| `get_billing_info` / `list_invoices` | UTILITY | Consulta faturas, métodos de pagamento e status da conta de faturamento. |

---

## ⚙️ Conexão nos Clientes MCP

O servidor pode ser consumido em dois modos:
1. **Modo Remoto (Recomendado):** Servidor hospedado na nuvem (Coolify ou Docker) ou rodando localmente via `start_worker.py` (transporte HTTP Streamable ou SSE).
2. **Modo Local (stdio):** Execução direta via Python gerenciada pelo próprio cliente MCP.

---

### 1. Claude Desktop

Abra o arquivo de configuração do Claude Desktop:
* **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
* **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

#### Opção A: Servidor Remoto (Coolify / SSE)
```json
{
  "mcpServers": {
    "google-ads": {
      "url": "https://SEU-DOMINIO/sse?token=SEU_MCP_AUTH_TOKEN"
    }
  }
}
```

#### Opção B: Execução Local Direta (stdio)
```json
{
  "mcpServers": {
    "google-ads": {
      "command": "python",
      "args": ["-m", "src.mcp_server.worker"],
      "env": {
        "GOOGLE_ADS_DEVELOPER_TOKEN": "SEU_DEVELOPER_TOKEN",
        "GOOGLE_ADS_CLIENT_ID": "SEU_CLIENT_ID",
        "GOOGLE_ADS_CLIENT_SECRET": "SEU_CLIENT_SECRET",
        "GOOGLE_ADS_REFRESH_TOKEN": "SEU_REFRESH_TOKEN",
        "GOOGLE_ADS_LOGIN_CUSTOMER_ID": "SEU_LOGIN_CUSTOMER_ID"
      }
    }
  }
}
```

---

### 2. Cursor

No Cursor, você pode configurar via interface visual ou via arquivo no workspace:

#### Via Interface (Settings):
1. Acesse **Settings** > **Features** > **MCP Servers**.
2. Clique em **Add New MCP Server**.
3. Preencha:
   * **Name:** `google-ads`
   * **Type:** `sse` (ou `command` para execução local)
   * **URL:** `https://SEU-DOMINIO/sse?token=SEU_MCP_AUTH_TOKEN` (ou `http://127.0.0.1:8765/sse` se local)

#### Via Arquivo `.cursor/mcp.json` no Workspace:

**Conexão Remota (HTTP / SSE):**
```json
{
  "mcpServers": {
    "google-ads": {
      "type": "http",
      "url": "https://SEU-DOMINIO/mcp",
      "headers": {
        "Authorization": "Bearer SEU_MCP_AUTH_TOKEN"
      }
    }
  }
}
```

**Conexão Local (stdio):**
```json
{
  "mcpServers": {
    "google-ads": {
      "command": "python",
      "args": ["-m", "src.mcp_server.worker"],
      "env": {
        "GOOGLE_ADS_DEVELOPER_TOKEN": "SEU_DEVELOPER_TOKEN",
        "GOOGLE_ADS_CLIENT_ID": "SEU_CLIENT_ID",
        "GOOGLE_ADS_CLIENT_SECRET": "SEU_CLIENT_SECRET",
        "GOOGLE_ADS_REFRESH_TOKEN": "SEU_REFRESH_TOKEN",
        "GOOGLE_ADS_LOGIN_CUSTOMER_ID": "SEU_LOGIN_CUSTOMER_ID"
      }
    }
  }
}
```

---

### 3. Antigravity e Claude Code

No arquivo `mcp_config.json` ou `~/.claude.json`:
```json
{
  "mcpServers": {
    "google-ads": {
      "type": "http",
      "url": "https://SEU-DOMINIO/mcp",
      "headers": {
        "Authorization": "Bearer SEU_MCP_AUTH_TOKEN"
      }
    }
  }
}
```

---

## 🚢 Deploy & Execução

### Opção 1: Nuvem 24/7 com Coolify (Recomendado)

O repositório já possui configuração completa com Dockerfile otimizado:
1. Conecte o repositório `https://github.com/octadigitalia/google-ads-mcp` no Coolify.
2. Defina as variáveis de ambiente privadas no painel do Coolify:
   * `MCP_AUTH_TOKEN`: Token seguro para autenticação Bearer.
   * `GOOGLE_ADS_DEVELOPER_TOKEN`: Seu developer token do Google Ads.
   * `GOOGLE_ADS_CLIENT_ID` e `GOOGLE_ADS_CLIENT_SECRET`: Credenciais OAuth do Google Cloud.
   * `GOOGLE_ADS_REFRESH_TOKEN`: Refresh token gerado via setup.
   * `GOOGLE_ADS_LOGIN_CUSTOMER_ID`: ID da conta administradora (MCC) sem traços.
3. Clique em **Deploy**. O Coolify expõe automaticamente os endpoints com SSL Let's Encrypt gratuito e health check nativo em `/health`.

### Opção 2: Local via Python

```bash
# 1. Clonar repositório
git clone https://github.com/octadigitalia/google-ads-mcp.git
cd google-ads-mcp

# 2. Criar e ativar venv
python -m venv .venv
.\.venv\Scripts\activate  # Windows
# source .venv/bin/activate  # Linux/macOS

# 3. Instalar dependências
pip install -r requirements.txt

# 4. Configurar variáveis de ambiente
cp .env.example .env
# Preencha suas credenciais no arquivo .env

# 5. Iniciar servidor worker
python start_worker.py
```

---

## 🧪 Validação & Healthcheck

Após iniciar o servidor:
* **Healthcheck HTTP:** `curl http://localhost:8765/health` (retorna `{"status": "healthy"}`)
* **Validação MCP:** No cliente de IA (Claude, Cursor ou Antigravity), execute a ferramenta `check_connection` para validar a prontidão da conexão com a Google Ads API.

---

## 🔒 Princípios de Segurança e Governança

1. **Prevenção contra Gastos Acidentais:** Campanhas criadas via IA entram com status `PAUSED` por padrão.
2. **Segurança em Massa:** Comandos de pausa em massa (`bulk_pause_keywords`) exigem confirmação ou operam com `dry_run=True` por padrão.
3. **Resolução Amigável de Nomes:** Todas as tools aceitam tanto o ID numérico quanto o **Nome da Campanha / Grupo de Anúncios**, resolvendo automaticamente via `ResourceResolver`.
4. **Isolamento de Credenciais:** Nenhuma chave ou token é versionado no Git; todas as credenciais residem no `.env` local ou no cofre de variáveis de ambiente do Coolify.

---

## 📄 Licença

Distribuído sob a licença MIT. Desenvolvido pela equipe **OctaDigital**.
