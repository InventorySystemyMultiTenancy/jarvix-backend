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
