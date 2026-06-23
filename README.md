# Jarvix Backend

API do assistente Jarvix, construída com FastAPI, PostgreSQL/SQLite e OpenAI Responses API.

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
- `DATABASE_URL`: conexão PostgreSQL em produção, normalmente criada pelo Render Postgres.
- `JARVIX_SECRET_KEY`: chave longa e aleatória usada para assinar os tokens de login.
- `JARVIX_DATABASE`: caminho do SQLite local, usado apenas quando `DATABASE_URL` não existe.
- `JARVIX_ALLOWED_ORIGINS`: URLs autorizadas a consumir a API.

## Deploy na Render com PostgreSQL

Crie um serviço PostgreSQL na Render e conecte-o ao Web Service do backend. A Render
deve expor a variável `DATABASE_URL` automaticamente ou permitir copiar a Internal
Database URL para as variáveis do backend.

Variáveis recomendadas no backend:

```env
DATABASE_URL=postgresql://...
JARVIX_SECRET_KEY=uma-chave-grande-e-aleatoria
OPENAI_API_KEY=sua-chave-openai
OPENAI_MODEL=gpt-5-mini
JARVIX_ALLOWED_ORIGINS=https://seu-frontend.onrender.com,http://localhost:5173
```

O backend cria as tabelas automaticamente no primeiro boot.

## Multiusuário

O Jarvix usa login com token Bearer. Cada cliente possui seus próprios registros
em dispositivos, alertas, rotinas, integrações e biblioteca musical. O isolamento
é feito por `user_id`, que é o padrão mais seguro e simples para SaaS; assim não é
necessário criar uma tabela física para cada cliente.

## Aplicativo desktop sincronizado

O agente em `desktop/jarvix_desktop.py` baixa periodicamente `/api/sync/snapshot`
e mantém uma memória offline em `%LOCALAPPDATA%\Jarvix\memory.json`. Com a API
multiusuário, o app desktop também precisa enviar o token do cliente para acessar
a memória correta.

Para gerar o aplicativo:

```powershell
cd desktop
pip install -r requirements-desktop.txt
$env:JARVIX_ICON="C:\caminho\jarvis.ico"
powershell -ExecutionPolicy Bypass -File .\build.ps1
```

O build gera um executável único `Jarvix.exe`, que abre em uma janela nativa
embutida e não força o navegador.

Executáveis PyInstaller sem certificado são exibidos como desconhecidos pelo
Microsoft SmartScreen. Uma distribuição comercial deve assinar o instalador e o
`.exe` com certificado de assinatura de código e timestamp.
