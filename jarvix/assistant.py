from __future__ import annotations

import os

from openai import OpenAI


SYSTEM_PROMPT = """
Você é Jarvix, um assistente pessoal em português do Brasil.
Seja direto, gentil e útil. Responda em no máximo quatro frases, exceto quando
o usuário pedir detalhes. Use a memória sincronizada somente como contexto do
cliente atual. Nunca afirme que executou uma automação que ainda não foi
confirmada pela plataforma.
""".strip()


def answer(message: str, memory_context: str = "") -> dict[str, str]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return {
            "text": (
                "O painel está funcionando, mas a inteligência ainda não foi ativada. "
                "Adicione OPENAI_API_KEY nas variáveis de ambiente do servidor."
            ),
            "mode": "setup",
        }

    instructions = SYSTEM_PROMPT
    if memory_context:
        instructions = f"{SYSTEM_PROMPT}\n\nMemória sincronizada deste cliente:\n{memory_context}"

    client = OpenAI(api_key=api_key)
    response = client.responses.create(
        model=os.getenv("OPENAI_MODEL", "gpt-5-mini"),
        instructions=instructions,
        input=message,
    )
    return {"text": response.output_text, "mode": "ai"}
