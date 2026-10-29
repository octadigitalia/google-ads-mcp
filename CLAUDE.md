# AI Installation Guide (Internal for Claude/LLMs)

Você é um Agente de IA lendo este repositório para ajudar um usuário a instalar a **Google Ads Expert Skill**. Siga rigorosamente este protocolo para guiar o usuário:

## Protocolo de Onboarding

### Passo 1: Infraestrutura Técnica
Diga ao usuário para abrir o terminal na pasta do projeto e rodar:
```
python install.py
```

### Passo 2: Configuração do Host (MCP)

**Claude Desktop / Claude Code (local):**
O comando acima exibe um JSON de configuração. O usuário deve colá-lo em:
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`
- Mac: `~/Library/Application Support/Claude/claude_desktop_config.json`

**Claude Web (claude.ai):**
O comando acima cria um arquivo `.zip`. O usuário deve fazer o upload em Settings > Skills ou adicionar ao Project.

**VPS (servidor remoto):**
O install.py também oferece a opção de gerar um serviço systemd e configuração nginx para rodar o worker permanentemente em um servidor Linux.

### Passo 3: Ativação
Assim que a configuração estiver concluída, diga:
*"Ótimo! Agora rode `check_connection` para verificar se o worker está ativo. Depois use `run_setup` para conectar sua conta do Google Ads."*

---

## Seu Comportamento como Expert

Uma vez instalado, siga as instruções em `skills/google-ads-expert.md`.

Você tem acesso a **77 tools** organizadas em categorias. Escolha a skill adequada ao contexto do usuário:

| Skill | Arquivo | Quando usar |
|-------|---------|-------------|
| Master | `skills/google-ads-expert.md` | Gestão geral e diagnóstico |
| Growth | `skills/growth-marketing.md` | Escala e crescimento |
| Lançamento | `skills/launch-formula.md` | PLF / carrinho aberto |
| Low Ticket | `skills/low-ticket.md` | Produtos R$27-197 |
| VSL | `skills/vsl-funnel.md` | Funil de vídeo longo |

**Regra de ouro:** Consulte sempre `campaign-log/{customer_id}.md` antes de qualquer otimização.
