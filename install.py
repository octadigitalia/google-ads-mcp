import os
import sys
import subprocess
import json
import zipfile
import platform
from pathlib import Path

SKILLS = {
    "1": {
        "name": "Google Ads Expert (Master)",
        "files": ["skills/google-ads-expert.md", "skills/audit-workflow.md", "skills/google-ads-expert.json", "README.md"],
        "zip": "google-ads-expert-skill.zip",
        "description": "Gestao geral — 77 tools, auditoria completa, log de acoes"
    },
    "2": {
        "name": "Growth Marketing",
        "files": ["skills/growth-marketing.md", "skills/google-ads-expert.json", "README.md"],
        "zip": "growth-marketing-skill.zip",
        "description": "Escala de negocios, CAC/LTV, alocacao de budget por ICE Score"
    },
    "3": {
        "name": "Formula de Lancamento",
        "files": ["skills/launch-formula.md", "skills/google-ads-expert.json", "README.md"],
        "zip": "launch-formula-skill.zip",
        "description": "PLF, pre-lancamento, carrinho aberto/fechado"
    },
    "4": {
        "name": "Low Ticket",
        "files": ["skills/low-ticket.md", "skills/google-ads-expert.json", "README.md"],
        "zip": "low-ticket-skill.zip",
        "description": "Produtos R$27-197, volume, CPA baixo, PMax"
    },
    "5": {
        "name": "Funil VSL",
        "files": ["skills/vsl-funnel.md", "skills/google-ads-expert.json", "README.md"],
        "zip": "vsl-funnel-skill.zip",
        "description": "VSL, retargeting em camadas por profundidade de video"
    },
    "6": {
        "name": "Bundle Completo (todas as skills)",
        "files": [
            "skills/google-ads-expert.md", "skills/audit-workflow.md",
            "skills/growth-marketing.md", "skills/launch-formula.md",
            "skills/low-ticket.md", "skills/vsl-funnel.md",
            "skills/google-ads-expert.json", "README.md"
        ],
        "zip": "google-ads-all-skills.zip",
        "description": "Todas as skills em um unico pacote"
    }
}


def print_banner():
    print("\n" + "=" * 62)
    print("  Google Ads Expert AI Skill — Installer v4.0")
    print("=" * 62 + "\n")


def install_dependencies():
    print("Instalando dependencias Python...")
    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "-r", "requirements.txt"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        print("  OK\n")
        return True
    except Exception as e:
        print(f"  Erro: {e}\n")
        return False


def create_zip(skill_info: dict) -> str | None:
    zip_name = skill_info["zip"]
    try:
        with zipfile.ZipFile(zip_name, "w") as zipf:
            for file in skill_info["files"]:
                if os.path.exists(file):
                    zipf.write(file)
        return zip_name
    except Exception as e:
        print(f"  Erro ao criar ZIP: {e}")
        return None


def ensure_campaign_log_dir():
    Path("campaign-log").mkdir(exist_ok=True)
    gitkeep = Path("campaign-log/.gitkeep")
    if not gitkeep.exists():
        gitkeep.touch()


def select_mode() -> str:
    print("Onde voce vai rodar o worker?\n")
    print("  [1] Local (minha maquina — Claude Desktop ou Claude Code)")
    print("  [2] VPS / Servidor Linux (acesso remoto)\n")
    return input("Escolha (1/2): ").strip()


def select_skill() -> dict:
    print("\nQual skill deseja empacotar para Claude Web?\n")
    for key, skill in SKILLS.items():
        print(f"  [{key}] {skill['name']}")
        print(f"      {skill['description']}\n")
    choice = input("Escolha (1-6): ").strip()
    return SKILLS.get(choice, SKILLS["1"])


# ─────────────────────────────────────────────
# LOCAL INSTALL
# ─────────────────────────────────────────────

def install_local():
    project_path = str(Path(__file__).parent.absolute()).replace("\\", "/")

    mcp_config = {
        "mcpServers": {
            "google-ads-expert": {
                "type": "sse",
                "url": "http://127.0.0.1:8765/sse"
            }
        }
    }

    skill = select_skill()
    print(f"\nEmpacotando: {skill['name']}...")
    zip_file = create_zip(skill)

    print("\n" + "=" * 62)
    print("  INSTALACAO LOCAL CONCLUIDA")
    print("=" * 62)

    print("\n1. INICIAR O WORKER (em um terminal separado):")
    print("     python start_worker.py")

    print("\n2. CLAUDE DESKTOP — cole em claude_desktop_config.json:")
    print(json.dumps(mcp_config, indent=4))

    print("\n3. CLAUDE CODE (CLI) — cole em ~/.claude.json:")
    print(json.dumps({"mcpServers": mcp_config["mcpServers"]}, indent=4))

    if zip_file:
        print(f"\n4. CLAUDE WEB — faca upload de: {zip_file}")
        print("   Settings > Skills ou adicione ao seu Project.")

    print("\nPROXIMO PASSO: No chat, diga 'check_connection'")
    print("=" * 62 + "\n")


# ─────────────────────────────────────────────
# VPS INSTALL
# ─────────────────────────────────────────────

def install_vps():
    print("\nConfiguracao para VPS Linux\n")
    host = input("IP ou dominio do servidor (ex: 1.2.3.4 ou meusite.com): ").strip()
    port = input("Porta do worker [8765]: ").strip() or "8765"
    use_nginx = input("Configurar nginx como proxy reverso? (s/n) [s]: ").strip().lower()
    use_nginx = use_nginx != "n"
    use_https = False
    domain = host
    if use_nginx:
        use_https = input("Usar HTTPS? (necessita certificado SSL) (s/n) [n]: ").strip().lower() == "s"
        if use_https:
            domain = input("Dominio para SSL (ex: ads.meusite.com): ").strip() or host

    project_path = input("\nCaminho do projeto no servidor (ex: /opt/google-ads-mcp): ").strip()
    python_path = input("Caminho do Python no servidor [python3]: ").strip() or "python3"
    user = input("Usuario do sistema para o servico [www-data]: ").strip() or "www-data"

    public_url = f"https://{domain}/sse" if use_https else f"http://{host}:{port}/sse"

    # systemd service
    service_content = f"""[Unit]
Description=Google Ads Expert MCP Worker
After=network.target

[Service]
Type=simple
User={user}
WorkingDirectory={project_path}
Environment=MCP_TRANSPORT=sse
Environment=MCP_PORT={port}
Environment=PYTHONPATH={project_path}
ExecStart={python_path} {project_path}/start_worker.py
Restart=on-failure
RestartSec=5s
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
"""

    service_file = "google-ads-mcp.service"
    with open(service_file, "w") as f:
        f.write(service_content)

    # nginx config
    nginx_content = ""
    if use_nginx:
        if use_https:
            nginx_content = f"""server {{
    listen 80;
    server_name {domain};
    return 301 https://$host$request_uri;
}}

server {{
    listen 443 ssl;
    server_name {domain};

    ssl_certificate /etc/letsencrypt/live/{domain}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/{domain}/privkey.pem;

    location / {{
        proxy_pass http://127.0.0.1:{port};
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection keep-alive;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 86400;
    }}
}}
"""
        else:
            nginx_content = f"""server {{
    listen 80;
    server_name {host};

    location / {{
        proxy_pass http://127.0.0.1:{port};
        proxy_http_version 1.1;
        proxy_set_header Connection keep-alive;
        proxy_set_header Host $host;
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 86400;
    }}
}}
"""
        nginx_file = "google-ads-mcp-nginx.conf"
        with open(nginx_file, "w") as f:
            f.write(nginx_content)

    mcp_config = {
        "mcpServers": {
            "google-ads-expert": {
                "type": "sse",
                "url": public_url
            }
        }
    }

    print("\n" + "=" * 62)
    print("  ARQUIVOS GERADOS")
    print("=" * 62)

    print(f"\n  {service_file} — servico systemd")
    if use_nginx:
        print(f"  {nginx_file} — configuracao nginx")

    print("\n" + "=" * 62)
    print("  PASSOS NO SERVIDOR VPS")
    print("=" * 62)

    print(f"""
1. Copie o projeto para o servidor:
     scp -r . {user}@{host}:{project_path}

2. No servidor, instale as dependencias:
     cd {project_path}
     pip3 install -r requirements.txt

3. Configure as credenciais:
     cp google-ads.yaml.example google-ads.yaml
     # edite com suas credenciais

4. Instale e inicie o servico:
     sudo cp {service_file} /etc/systemd/system/
     sudo systemctl daemon-reload
     sudo systemctl enable google-ads-mcp
     sudo systemctl start google-ads-mcp
     sudo systemctl status google-ads-mcp
""")

    if use_nginx:
        print(f"""5. Configure o nginx:
     sudo cp {nginx_file} /etc/nginx/sites-available/google-ads-mcp
     sudo ln -s /etc/nginx/sites-available/google-ads-mcp /etc/nginx/sites-enabled/
     sudo nginx -t && sudo systemctl reload nginx
""")
        if use_https:
            print(f"""6. Obtenha o certificado SSL:
     sudo certbot --nginx -d {domain}
""")

    print("CONFIGURACAO DO CLIENTE (cole no Claude Desktop / Claude Code):")
    print(json.dumps(mcp_config, indent=4))
    print("\nURL publica do worker:", public_url)
    print("=" * 62 + "\n")


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    print_banner()
    install_dependencies()
    ensure_campaign_log_dir()

    mode = select_mode()
    if mode == "2":
        install_vps()
    else:
        install_local()


if __name__ == "__main__":
    main()
