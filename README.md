# Jarvix Backend

API do assistente Jarvix, construída com FastAPI, SQLite e OpenAI Responses API.

## Desenvolvimento

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python run_server.py
```

A API fica em `http://127.0.0.1:8765` e a documentação em
`http://127.0.0.1:8765/docs`.

## Configuração

- `OPENAI_API_KEY`: chave usada somente no servidor.
- `OPENAI_MODEL`: modelo da Responses API.
- `JARVIX_DATABASE`: caminho do SQLite.
- `JARVIX_ALLOWED_ORIGINS`: URLs autorizadas a consumir a API.

O protótipo original foi preservado em `legacy/main.py`. Ele é apenas referência
e não faz parte da inicialização da API.

## Aplicativo desktop sincronizado

O agente em `desktop/jarvix_desktop.py` baixa periodicamente `/api/sync/snapshot`
e mantém uma memória offline em `%LOCALAPPDATA%\Jarvix\memory.json`. Alertas,
rotinas, dispositivos e biblioteca musical cadastrados no site passam a fazer
parte do contexto do assistente.

Para gerar o aplicativo:

```powershell
cd desktop
pip install -r requirements-desktop.txt
$env:JARVIX_ICON="C:\caminho\jarvis.ico"
powershell -ExecutionPolicy Bypass -File .\build.ps1
```

O executável abre a interface em um servidor local (`127.0.0.1`) no navegador
padrão. Essa arquitetura não depende de `pythonnet/.NET` e funciona com Python
3.13.

Executáveis PyInstaller sem certificado são exibidos como desconhecidos pelo
Microsoft SmartScreen. Uma distribuição comercial deve assinar o instalador e
o `.exe` com certificado de assinatura de código e timestamp.
