from __future__ import annotations

from html import unescape
import os
import re

from openai import OpenAI
import requests


SYSTEM_PROMPT = """
Voce e Jarvix, um assistente pessoal em portugues do Brasil.
Seja direto, gentil e util. Responda em no maximo quatro frases, exceto quando
o usuario pedir detalhes. Use a memoria sincronizada somente como contexto do
cliente atual. Nunca afirme que executou uma automacao que ainda nao foi
confirmada pela plataforma.
Quando houver contexto de pesquisa na internet, use esse contexto para responder
perguntas sobre fatos atuais, placares, noticias, populacao, clima, precos e
informacoes que possam mudar com o tempo. Se o contexto nao for suficiente,
diga que nao encontrou certeza suficiente.
""".strip()


WEB_QUERY_HINTS = (
    "hoje",
    "ontem",
    "agora",
    "atual",
    "recente",
    "noticia",
    "noticias",
    "placar",
    "jogo",
    "resultado",
    "quanto foi",
    "quantas pessoas",
    "populacao",
    "internet",
    "pesquise",
    "procure",
)


def answer(message: str, memory_context: str = "") -> dict[str, str]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return {
            "text": (
                "O painel esta funcionando, mas a inteligencia ainda nao foi ativada. "
                "Adicione OPENAI_API_KEY nas variaveis de ambiente do servidor."
            ),
            "mode": "setup",
        }

    client = OpenAI(api_key=api_key)
    needs_web = should_search_web(message)
    if needs_web:
        web_answer = answer_with_openai_web_search(client, message, memory_context)
        if web_answer:
            return {"text": web_answer, "mode": "ai_openai_web"}

    web_context = web_search_context(message)
    extra_context = []
    if memory_context:
        extra_context.append(f"Memoria sincronizada deste cliente:\n{memory_context}")
    if web_context:
        extra_context.append(f"Pesquisa recente na internet:\n{web_context}")

    instructions = SYSTEM_PROMPT
    if extra_context:
        instructions = f"{SYSTEM_PROMPT}\n\n" + "\n\n".join(extra_context)

    response = client.responses.create(
        model=os.getenv("OPENAI_MODEL", "gpt-5-mini"),
        instructions=instructions,
        input=message,
    )
    return {"text": response.output_text, "mode": "ai_web" if web_context else "ai"}


def answer_with_openai_web_search(client: OpenAI, message: str, memory_context: str = "") -> str:
    extra_context = []
    if memory_context:
        extra_context.append(f"Memoria sincronizada deste cliente:\n{memory_context}")
    instructions = (
        f"{SYSTEM_PROMPT}\n\n"
        "Para perguntas sobre fatos atuais, placares, noticias, datas recentes ou dados variaveis, "
        "pesquise na web imediatamente. Nao pergunte ao usuario se deve pesquisar; pesquise e responda. "
        "Se encontrar fontes conflitantes, diga a incerteza de forma direta."
    )
    if extra_context:
        instructions += "\n\n" + "\n\n".join(extra_context)

    try:
        response = client.responses.create(
            model=os.getenv("OPENAI_WEB_MODEL", os.getenv("OPENAI_MODEL", "gpt-5-mini")),
            instructions=instructions,
            input=message,
            tools=[{"type": "web_search_preview"}],
        )
        return response.output_text.strip()
    except Exception:
        return ""


def web_search_context(message: str) -> str:
    if os.getenv("JARVIX_WEB_SEARCH", "1").lower() in {"0", "false", "no"}:
        return ""
    if not should_search_web(message):
        return ""
    try:
        response = requests.get(
            "https://duckduckgo.com/html/",
            params={"q": message, "kl": "br-pt"},
            headers={"User-Agent": "Mozilla/5.0 Jarvix/0.2"},
            timeout=12,
        )
        response.raise_for_status()
        return parse_duckduckgo_results(response.text)
    except Exception:
        return ""


def should_search_web(message: str) -> bool:
    text = message.lower()
    return "?" in text or any(hint in text for hint in WEB_QUERY_HINTS)


def parse_duckduckgo_results(html: str) -> str:
    items: list[str] = []
    pattern = re.compile(
        r'class="result__a"[^>]*>(?P<title>.*?)</a>.*?class="result__snippet"[^>]*>(?P<snippet>.*?)</a>',
        re.IGNORECASE | re.DOTALL,
    )
    for match in pattern.finditer(html):
        title = clean_html(match.group("title"))
        snippet = clean_html(match.group("snippet"))
        if title and snippet:
            items.append(f"- {title}: {snippet}")
        if len(items) >= 5:
            break
    return "\n".join(items)


def clean_html(value: str) -> str:
    text = re.sub(r"<.*?>", " ", value)
    text = unescape(text)
    return re.sub(r"\s+", " ", text).strip()
