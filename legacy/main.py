from openai import OpenAI
from dotenv import load_dotenv
from datetime import datetime
from difflib import get_close_matches
from urllib.parse import quote_plus, quote
import os
import subprocess
import requests
import chromadb
import speech_recognition as sr
import edge_tts
import asyncio
import tempfile
import pygame
import threading
import time
import webbrowser
import uuid
import json
import re

try:
    import audioop
except ImportError:
    import audioop_lts as audioop

# =========================
# CONFIGURAÇÕES
# =========================

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

PASTA_PROJETOS = r"C:\JarvisProjects"
PASTA_MEMORIA = r"C:\JarvisMemory"
PASTA_DADOS_JARVIS = r"C:\JarvisData"

ARQUIVO_LEMBRETES = os.path.join(PASTA_DADOS_JARVIS, "lembretes.json")
ARQUIVO_ANOTACOES = os.path.join(PASTA_DADOS_JARVIS, "anotacoes.json")

os.makedirs(PASTA_PROJETOS, exist_ok=True)
os.makedirs(PASTA_MEMORIA, exist_ok=True)
os.makedirs(PASTA_DADOS_JARVIS, exist_ok=True)

if not GITHUB_TOKEN:
    print("Aviso: GITHUB_TOKEN não encontrado no arquivo. Funções do GitHub não funcionarão.")

if not OPENAI_API_KEY:
    raise RuntimeError("Defina OPENAI_API_KEY no arquivo .env antes de iniciar o Jarvis legado.")

client = OpenAI(api_key=OPENAI_API_KEY)

# =========================
# LOG / DEBUG
# =========================

ARQUIVO_LOG = os.path.join(PASTA_DADOS_JARVIS, "jarvis_erros.log")


def registrar_erro(origem, erro):
    try:
        with open(ARQUIVO_LOG, "a", encoding="utf-8") as arquivo:
            arquivo.write(f"[{datetime.now().strftime('%d/%m/%Y %H:%M:%S')}] {origem}: {erro}\n")
    except Exception:
        pass


# =========================
# GITHUB
# =========================

def github_headers():
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json"
    }


def obter_usuario_github():
    if not GITHUB_TOKEN:
        return None

    try:
        response = requests.get(
            "https://api.github.com/user",
            headers=github_headers(),
            timeout=20
        )

        if response.status_code != 200:
            print("Erro ao obter usuário do GitHub.")
            print(response.text)
            return None

        dados = response.json()
        return dados["login"]

    except Exception as erro:
        registrar_erro("obter_usuario_github", erro)
        print("Erro ao conectar no GitHub:", erro)
        return None


GITHUB_USER = obter_usuario_github()

if GITHUB_USER:
    print(f"Usuário GitHub conectado: {GITHUB_USER}")
else:
    print("GitHub não conectado. Verifique seu token.")


def buscar_repositorios_github():
    if not GITHUB_TOKEN:
        return []

    repos = []
    pagina = 1

    while True:
        try:
            url = (
                "https://api.github.com/user/repos"
                f"?per_page=100&page={pagina}"
                "&visibility=all"
                "&affiliation=owner,collaborator,organization_member"
                "&sort=updated"
            )

            response = requests.get(url, headers=github_headers(), timeout=30)

            if response.status_code != 200:
                print("Erro GitHub:", response.text)
                break

            dados = response.json()

            if not dados:
                break

            repos.extend(dados)
            pagina += 1

        except Exception as erro:
            registrar_erro("buscar_repositorios_github", erro)
            print("Erro GitHub:", erro)
            break

    return repos


def normalizar_nome(texto):
    return (
        str(texto)
        .lower()
        .replace("-", "")
        .replace("_", "")
        .replace(" ", "")
        .replace(".", "")
        .replace("/", "")
    )


def encontrar_repo_semelhante(nome_digitado):
    nome_digitado = str(nome_digitado).strip()

    if not nome_digitado:
        return None

    nome_digitado_normalizado = normalizar_nome(nome_digitado)
    repos = buscar_repositorios_github()

    if not repos:
        return None

    # 1. Exato normalizado
    for repo in repos:
        if normalizar_nome(repo["name"]) == nome_digitado_normalizado:
            return repo

    # 2. Contém normalizado
    for repo in repos:
        nome_repo_normalizado = normalizar_nome(repo["name"])

        if nome_digitado_normalizado in nome_repo_normalizado:
            return repo

        if nome_repo_normalizado in nome_digitado_normalizado:
            return repo

    # 3. Também tenta com owner/repo
    for repo in repos:
        owner = repo.get("owner", {}).get("login", "")
        full_name = f"{owner}/{repo['name']}"
        if normalizar_nome(full_name) == nome_digitado_normalizado:
            return repo

    # 4. Aproximação
    mapa_normalizado = {
        normalizar_nome(repo["name"]): repo
        for repo in repos
    }

    semelhantes = get_close_matches(
        nome_digitado_normalizado,
        list(mapa_normalizado.keys()),
        n=1,
        cutoff=0.20
    )

    if semelhantes:
        return mapa_normalizado[semelhantes[0]]

    return None


def listar_repositorios():
    repos = buscar_repositorios_github()

    if not repos:
        return "Nenhum repositório encontrado ou GitHub não conectado."

    nomes = []

    for repo in repos:
        owner = repo.get("owner", {}).get("login", "")
        nome = repo["name"]
        privado = "privado" if repo.get("private") else "público"
        nomes.append(f"{owner}/{nome} ({privado})")

    return "\n".join(nomes)


def clonar_repositorio(nome_repo):
    if not GITHUB_TOKEN:
        return "GitHub não conectado."

    repo_encontrado = encontrar_repo_semelhante(nome_repo)

    if not repo_encontrado:
        return f"Não encontrei nenhum repositório parecido com: {nome_repo}"

    nome_real = repo_encontrado["name"]
    clone_url = repo_encontrado["clone_url"]
    caminho_repo = os.path.join(PASTA_PROJETOS, nome_real)

    if os.path.exists(caminho_repo):
        return f"O projeto {nome_real} já foi clonado."

    token_seguro = quote(GITHUB_TOKEN, safe="")
    clone_url_com_token = clone_url.replace(
        "https://",
        f"https://x-access-token:{token_seguro}@"
    )

    resultado = subprocess.run(
        f'git clone "{clone_url_com_token}" "{caminho_repo}"',
        shell=True,
        capture_output=True,
        text=True
    )

    if resultado.returncode == 0:
        return f"Projeto {nome_real} clonado com sucesso."

    return f"Erro ao clonar {nome_real}:\n{resultado.stderr}"


def abrir_ou_clonar_repositorio(nome_repo):
    repo_encontrado = encontrar_repo_semelhante(nome_repo)

    if not repo_encontrado:
        return f"Não encontrei nenhum repositório parecido com: {nome_repo}"

    nome_real = repo_encontrado["name"]
    caminho_repo = os.path.join(PASTA_PROJETOS, nome_real)

    if not os.path.exists(caminho_repo):
        resultado_clone = clonar_repositorio(nome_real)

        if "erro" in resultado_clone.lower() or "não encontrei" in resultado_clone.lower():
            return resultado_clone

    if not os.path.exists(caminho_repo):
        return f"Tentei clonar {nome_real}, mas a pasta não foi criada em {caminho_repo}"

    caminhos_vscode = [
        r"C:\Users\FOTOGRAFIA\AppData\Local\Programs\Microsoft VS Code\Code.exe",
        r"C:\Program Files\Microsoft VS Code\Code.exe",
        r"C:\Program Files (x86)\Microsoft VS Code\Code.exe"
    ]

    for caminho_code in caminhos_vscode:
        if os.path.exists(caminho_code):
            subprocess.Popen([caminho_code, caminho_repo])
            return f"Abri o projeto {nome_real} no VS Code."

    try:
        subprocess.Popen(f'code "{caminho_repo}"', shell=True)
        return f"Abri o projeto {nome_real} no VS Code."
    except Exception as erro:
        return f"Encontrei o projeto {nome_real}, mas não consegui abrir no VS Code. Erro: {erro}"


def resolver_nome_repo(nome_repo):
    repo_encontrado = encontrar_repo_semelhante(nome_repo)

    if not repo_encontrado:
        return None

    return repo_encontrado["name"]


def atualizar_repositorio(nome_repo):
    nome_real = resolver_nome_repo(nome_repo)

    if not nome_real:
        return f"Não encontrei nenhum projeto parecido com: {nome_repo}"

    caminho_repo = os.path.join(PASTA_PROJETOS, nome_real)

    if not os.path.exists(caminho_repo):
        return f"Encontrei {nome_real}, mas ele ainda não foi clonado. Use: abrir o repositório {nome_real}"

    resultado = subprocess.run(
        "git pull",
        shell=True,
        capture_output=True,
        text=True,
        cwd=caminho_repo
    )

    if resultado.returncode == 0:
        return f"Projeto {nome_real} atualizado."

    return f"Erro ao atualizar:\n{resultado.stderr}"


# =========================
# ARQUIVOS DOS PROJETOS
# =========================

EXTENSOES_PERMITIDAS = [
    ".py", ".js", ".jsx", ".ts", ".tsx", ".json", ".html", ".css", ".md", ".txt",
    ".sql", ".env.example", ".yml", ".yaml"
]


def caminho_do_repo(nome_repo):
    nome_real = resolver_nome_repo(nome_repo)

    if not nome_real:
        return None, None

    return nome_real, os.path.join(PASTA_PROJETOS, nome_real)


def listar_arquivos_projeto(nome_repo):
    nome_real, caminho_repo = caminho_do_repo(nome_repo)

    if not nome_real:
        return f"Não encontrei nenhum projeto parecido com: {nome_repo}"

    if not os.path.exists(caminho_repo):
        return f"Encontrei {nome_real}, mas ele ainda não foi clonado. Peça para eu abrir o repositório {nome_real} primeiro."

    arquivos = []

    for raiz, pastas, nomes_arquivos in os.walk(caminho_repo):
        if any(ignorar in raiz for ignorar in [".git", "node_modules", ".venv", "dist", "build", "__pycache__"]):
            continue

        for arquivo in nomes_arquivos:
            extensao = os.path.splitext(arquivo)[1]

            if extensao in EXTENSOES_PERMITIDAS or arquivo.endswith(".env.example"):
                caminho_completo = os.path.join(raiz, arquivo)
                caminho_relativo = os.path.relpath(caminho_completo, caminho_repo)
                arquivos.append(caminho_relativo)

    if not arquivos:
        return "Nenhum arquivo relevante encontrado."

    return "\n".join(arquivos[:200])


def procurar_no_projeto(nome_repo, termo):
    nome_real, caminho_repo = caminho_do_repo(nome_repo)

    if not nome_real:
        return f"Não encontrei nenhum projeto parecido com: {nome_repo}"

    if not os.path.exists(caminho_repo):
        return f"Encontrei {nome_real}, mas ele ainda não foi clonado. Peça para eu abrir o repositório {nome_real} primeiro."

    resultados = []

    for raiz, pastas, arquivos in os.walk(caminho_repo):
        if any(ignorar in raiz for ignorar in [".git", "node_modules", ".venv", "dist", "build", "__pycache__"]):
            continue

        for arquivo in arquivos:
            extensao = os.path.splitext(arquivo)[1]

            if extensao not in EXTENSOES_PERMITIDAS:
                continue

            caminho_completo = os.path.join(raiz, arquivo)

            try:
                with open(caminho_completo, "r", encoding="utf-8", errors="ignore") as f:
                    linhas = f.readlines()

                for numero, linha in enumerate(linhas, start=1):
                    if termo.lower() in linha.lower():
                        relativo = os.path.relpath(caminho_completo, caminho_repo)
                        resultados.append(f"{relativo} - linha {numero}: {linha.strip()}")

            except Exception:
                pass

    if not resultados:
        return f"Não encontrei o termo '{termo}' no projeto {nome_real}."

    return "\n".join(resultados[:100])


def encontrar_arquivo_semelhante(nome_repo, caminho_arquivo):
    nome_real, caminho_repo = caminho_do_repo(nome_repo)

    if not nome_real or not os.path.exists(caminho_repo):
        return None, None

    arquivos_encontrados = []

    for raiz, pastas, arquivos in os.walk(caminho_repo):
        if any(ignorar in raiz for ignorar in [".git", "node_modules", ".venv", "dist", "build", "__pycache__"]):
            continue

        for arquivo in arquivos:
            extensao = os.path.splitext(arquivo)[1]

            if extensao in EXTENSOES_PERMITIDAS or arquivo.endswith(".env.example"):
                caminho_completo = os.path.join(raiz, arquivo)
                caminho_relativo = os.path.relpath(caminho_completo, caminho_repo)
                arquivos_encontrados.append(caminho_relativo)

    for arquivo in arquivos_encontrados:
        if arquivo.lower() == caminho_arquivo.lower():
            return nome_real, arquivo

    semelhantes = get_close_matches(
        caminho_arquivo.lower(),
        [a.lower() for a in arquivos_encontrados],
        n=1,
        cutoff=0.35
    )

    if semelhantes:
        for arquivo in arquivos_encontrados:
            if arquivo.lower() == semelhantes[0]:
                return nome_real, arquivo

    return nome_real, None


def ler_arquivo(nome_repo, caminho_arquivo):
    nome_real, arquivo_encontrado = encontrar_arquivo_semelhante(nome_repo, caminho_arquivo)

    if not nome_real:
        return f"Não encontrei nenhum projeto parecido com: {nome_repo}"

    if not arquivo_encontrado:
        return f"Arquivo não encontrado no projeto {nome_real}: {caminho_arquivo}"

    caminho_completo = os.path.join(PASTA_PROJETOS, nome_real, arquivo_encontrado)

    try:
        with open(caminho_completo, "r", encoding="utf-8", errors="ignore") as f:
            conteudo = f.read()

        return conteudo[:12000]

    except Exception as erro:
        return f"Erro ao ler arquivo: {erro}"


def explicar_arquivo(nome_repo, caminho_arquivo):
    nome_real, arquivo_encontrado = encontrar_arquivo_semelhante(nome_repo, caminho_arquivo)

    if not nome_real:
        return f"Não encontrei nenhum projeto parecido com: {nome_repo}"

    if not arquivo_encontrado:
        return f"Arquivo não encontrado no projeto {nome_real}: {caminho_arquivo}"

    conteudo = ler_arquivo(nome_real, arquivo_encontrado)

    if conteudo.startswith("Arquivo não encontrado") or conteudo.startswith("Erro"):
        return conteudo

    resposta = client.responses.create(
        model="gpt-4.1-mini",
        instructions=f"""
Você é o Jarvis, assistente técnico do Mateus.
Explique o arquivo {arquivo_encontrado} do projeto {nome_real} de forma simples, objetiva e prática.
Diga:
1. O que esse arquivo faz
2. Quais partes são mais importantes
3. Se existe algum possível problema
4. O que poderia ser melhorado
""",
        input=conteudo
    )

    return resposta.output_text


# =========================
# AGENDA LOCAL
# =========================

def carregar_json(caminho):
    if not os.path.exists(caminho):
        return []

    try:
        with open(caminho, "r", encoding="utf-8") as arquivo:
            return json.load(arquivo)
    except Exception:
        return []


def salvar_json(caminho, dados):
    with open(caminho, "w", encoding="utf-8") as arquivo:
        json.dump(dados, arquivo, ensure_ascii=False, indent=4)


def criar_anotacao(titulo, conteudo):
    anotacoes = carregar_json(ARQUIVO_ANOTACOES)

    anotacao = {
        "id": str(uuid.uuid4()),
        "titulo": titulo,
        "conteudo": conteudo,
        "criado_em": datetime.now().strftime("%d/%m/%Y %H:%M")
    }

    anotacoes.append(anotacao)
    salvar_json(ARQUIVO_ANOTACOES, anotacoes)

    return f"Anotação salva: {titulo}"


def listar_anotacoes():
    anotacoes = carregar_json(ARQUIVO_ANOTACOES)

    if not anotacoes:
        return "Você ainda não tem anotações salvas."

    texto = "Suas últimas anotações:\n"

    for item in anotacoes[-10:]:
        texto += f"- {item['titulo']}: {item['conteudo']}\n"

    return texto


def criar_lembrete(titulo, data_hora, descricao=""):
    lembretes = carregar_json(ARQUIVO_LEMBRETES)

    lembrete = {
        "id": str(uuid.uuid4()),
        "titulo": titulo,
        "descricao": descricao,
        "data_hora": data_hora,
        "avisado": False
    }

    lembretes.append(lembrete)
    salvar_json(ARQUIVO_LEMBRETES, lembretes)

    return f"Lembrete criado: {titulo} em {data_hora}"


def listar_lembretes():
    lembretes = carregar_json(ARQUIVO_LEMBRETES)

    if not lembretes:
        return "Você não tem lembretes salvos."

    texto = "Seus lembretes:\n"

    for item in lembretes:
        status = "avisado" if item.get("avisado") else "pendente"
        texto += f"- {item['titulo']} em {item['data_hora']} ({status})\n"

    return texto


def monitorar_lembretes():
    while True:
        lembretes = carregar_json(ARQUIVO_LEMBRETES)
        agora = datetime.now()
        alterou = False

        for lembrete in lembretes:
            if lembrete.get("avisado"):
                continue

            try:
                data_lembrete = datetime.strptime(lembrete["data_hora"], "%d/%m/%Y %H:%M")
            except Exception:
                continue

            if agora >= data_lembrete:
                lembrete["avisado"] = True
                alterou = True

                mensagem = f"Lembrete: {lembrete['titulo']}"

                if lembrete.get("descricao"):
                    mensagem += f". {lembrete['descricao']}"

                falar_em_thread(mensagem)

        if alterou:
            salvar_json(ARQUIVO_LEMBRETES, lembretes)

        time.sleep(20)


# =========================
# MEMÓRIA VETORIAL
# =========================

chroma_client = chromadb.PersistentClient(path=PASTA_MEMORIA)


def nome_collection(nome_repo):
    nome = nome_repo.lower().replace("-", "_").replace(" ", "_").replace(".", "_")
    nome = re.sub(r"[^a-z0-9_]", "_", nome)

    if len(nome) < 3:
        nome = nome + "_repo"

    return nome[:60]


def gerar_embedding(texto):
    resposta = client.embeddings.create(
        model="text-embedding-3-small",
        input=texto
    )

    return resposta.data[0].embedding


def dividir_texto(texto, tamanho=3000):
    partes = []

    for i in range(0, len(texto), tamanho):
        partes.append(texto[i:i + tamanho])

    return partes


def indexar_projeto(nome_repo):
    nome_real, caminho_repo = caminho_do_repo(nome_repo)

    if not nome_real:
        return f"Não encontrei nenhum projeto parecido com: {nome_repo}"

    if not os.path.exists(caminho_repo):
        return f"Encontrei {nome_real}, mas ele ainda não foi clonado. Peça para eu abrir o repositório {nome_real} primeiro."

    collection = chroma_client.get_or_create_collection(
        name=nome_collection(nome_real)
    )

    total = 0

    for raiz, pastas, arquivos in os.walk(caminho_repo):
        if any(ignorar in raiz for ignorar in [".git", "node_modules", ".venv", "dist", "build", "__pycache__"]):
            continue

        for arquivo in arquivos:
            extensao = os.path.splitext(arquivo)[1]

            if extensao not in EXTENSOES_PERMITIDAS:
                continue

            caminho_completo = os.path.join(raiz, arquivo)
            caminho_relativo = os.path.relpath(caminho_completo, caminho_repo)

            try:
                with open(caminho_completo, "r", encoding="utf-8", errors="ignore") as f:
                    conteudo = f.read()

                partes = dividir_texto(conteudo)

                for indice, parte in enumerate(partes):
                    if len(parte.strip()) < 50:
                        continue

                    id_documento = f"{nome_real}_{caminho_relativo}_{indice}"
                    id_documento = re.sub(r"[^a-zA-Z0-9_.-]", "_", id_documento)

                    embedding = gerar_embedding(parte)

                    collection.upsert(
                        ids=[id_documento],
                        documents=[parte],
                        embeddings=[embedding],
                        metadatas=[{
                            "projeto": nome_real,
                            "arquivo": caminho_relativo,
                            "parte": indice
                        }]
                    )

                    total += 1

            except Exception as erro:
                print(f"Erro ao indexar {caminho_relativo}: {erro}")

    return f"Projeto {nome_real} indexado com sucesso. Partes salvas na memória: {total}"


def perguntar_projeto(nome_repo, pergunta):
    nome_real = resolver_nome_repo(nome_repo)

    if not nome_real:
        return f"Não encontrei nenhum projeto parecido com: {nome_repo}"

    collection_name = nome_collection(nome_real)

    try:
        collection = chroma_client.get_collection(name=collection_name)
    except Exception:
        return f"Esse projeto ainda não foi indexado. Use: indexar projeto {nome_real}"

    embedding_pergunta = gerar_embedding(pergunta)

    resultados = collection.query(
        query_embeddings=[embedding_pergunta],
        n_results=5
    )

    documentos = resultados["documents"][0]
    metadados = resultados["metadatas"][0]

    if not documentos:
        return "Não encontrei nada relevante na memória desse projeto."

    contexto = ""

    for i in range(len(documentos)):
        arquivo = metadados[i]["arquivo"]
        contexto += f"\n\nArquivo: {arquivo}\n"
        contexto += documentos[i]

    resposta = client.responses.create(
        model="gpt-4.1-mini",
        instructions=f"""
Você é o Jarvis, assistente técnico do Mateus.
Responda baseado apenas no contexto encontrado no projeto {nome_real}.
Se a informação não estiver clara no contexto, diga que não encontrou certeza suficiente.
Sempre cite os nomes dos arquivos usados na resposta.
""",
        input=f"""
Pergunta do Mateus:
{pergunta}

Contexto encontrado no projeto:
{contexto}
"""
    )

    return resposta.output_text


# =========================
# NAVEGADOR E MÚSICA
# =========================

def abrir_site(url_ou_pesquisa):
    texto = url_ou_pesquisa.strip()

    if not texto.startswith("http"):
        if "." in texto and " " not in texto:
            texto = "https://" + texto
        else:
            texto = "https://www.google.com/search?q=" + quote_plus(texto)

    webbrowser.open(texto)
    return f"Abri no navegador: {url_ou_pesquisa}"


def tocar_musica_youtube_music(musica):
    musica = musica.strip()

    if not musica:
        return "Você precisa me dizer o nome da música."

    url = "https://music.youtube.com/search?q=" + quote_plus(musica)
    webbrowser.open(url)

    return f"Abri o YouTube Music procurando por: {musica}"


# =========================
# TOOL CALLING
# =========================

historico_conversa = []

tools = [
    {
        "type": "function",
        "name": "abrir_ou_clonar_repositorio",
        "description": "Procura um repositório no GitHub por nome aproximado, clona se necessário e abre no VS Code. Use sempre que o usuário pedir para abrir ou clonar projeto/repositório.",
        "parameters": {
            "type": "object",
            "properties": {
                "nome_repo": {
                    "type": "string",
                    "description": "Nome aproximado do repositório."
                }
            },
            "required": ["nome_repo"]
        }
    },
    {
        "type": "function",
        "name": "listar_repositorios",
        "description": "Lista todos os repositórios do GitHub do Mateus, incluindo privados e organizações acessíveis pelo token.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "type": "function",
        "name": "atualizar_repositorio",
        "description": "Atualiza um projeto local usando git pull.",
        "parameters": {
            "type": "object",
            "properties": {
                "nome_repo": {"type": "string"}
            },
            "required": ["nome_repo"]
        }
    },
    {
        "type": "function",
        "name": "listar_arquivos_projeto",
        "description": "Lista arquivos relevantes de um projeto local.",
        "parameters": {
            "type": "object",
            "properties": {
                "nome_repo": {"type": "string"}
            },
            "required": ["nome_repo"]
        }
    },
    {
        "type": "function",
        "name": "procurar_no_projeto",
        "description": "Procura um termo dentro dos arquivos de um projeto local.",
        "parameters": {
            "type": "object",
            "properties": {
                "nome_repo": {"type": "string"},
                "termo": {"type": "string"}
            },
            "required": ["nome_repo", "termo"]
        }
    },
    {
        "type": "function",
        "name": "ler_arquivo",
        "description": "Lê o conteúdo de um arquivo específico de um projeto.",
        "parameters": {
            "type": "object",
            "properties": {
                "nome_repo": {"type": "string"},
                "caminho_arquivo": {"type": "string"}
            },
            "required": ["nome_repo", "caminho_arquivo"]
        }
    },
    {
        "type": "function",
        "name": "explicar_arquivo",
        "description": "Explica um arquivo específico de um projeto.",
        "parameters": {
            "type": "object",
            "properties": {
                "nome_repo": {"type": "string"},
                "caminho_arquivo": {"type": "string"}
            },
            "required": ["nome_repo", "caminho_arquivo"]
        }
    },
    {
        "type": "function",
        "name": "indexar_projeto",
        "description": "Indexa um projeto local na memória vetorial.",
        "parameters": {
            "type": "object",
            "properties": {
                "nome_repo": {"type": "string"}
            },
            "required": ["nome_repo"]
        }
    },
    {
        "type": "function",
        "name": "perguntar_projeto",
        "description": "Responde perguntas sobre um projeto já indexado na memória vetorial.",
        "parameters": {
            "type": "object",
            "properties": {
                "nome_repo": {"type": "string"},
                "pergunta": {"type": "string"}
            },
            "required": ["nome_repo", "pergunta"]
        }
    },
    {
        "type": "function",
        "name": "abrir_site",
        "description": "Abre qualquer site, link, aba, página ou pesquisa no navegador.",
        "parameters": {
            "type": "object",
            "properties": {
                "url_ou_pesquisa": {"type": "string"}
            },
            "required": ["url_ou_pesquisa"]
        }
    },
    {
        "type": "function",
        "name": "tocar_musica_youtube_music",
        "description": "Abre o YouTube Music no navegador procurando uma música, artista ou playlist.",
        "parameters": {
            "type": "object",
            "properties": {
                "musica": {"type": "string"}
            },
            "required": ["musica"]
        }
    },
    {
        "type": "function",
        "name": "criar_anotacao",
        "description": "Cria uma anotação local na agenda/memória do Jarvis.",
        "parameters": {
            "type": "object",
            "properties": {
                "titulo": {"type": "string"},
                "conteudo": {"type": "string"}
            },
            "required": ["titulo", "conteudo"]
        }
    },
    {
        "type": "function",
        "name": "listar_anotacoes",
        "description": "Lista as anotações salvas localmente.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "type": "function",
        "name": "criar_lembrete",
        "description": "Cria um lembrete local. A data deve estar no formato dd/mm/aaaa hh:mm.",
        "parameters": {
            "type": "object",
            "properties": {
                "titulo": {"type": "string"},
                "data_hora": {"type": "string"},
                "descricao": {"type": "string"}
            },
            "required": ["titulo", "data_hora"]
        }
    },
    {
        "type": "function",
        "name": "listar_lembretes",
        "description": "Lista os lembretes salvos.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    }
]

funcoes_disponiveis = {
    "abrir_ou_clonar_repositorio": abrir_ou_clonar_repositorio,
    "listar_repositorios": listar_repositorios,
    "atualizar_repositorio": atualizar_repositorio,
    "listar_arquivos_projeto": listar_arquivos_projeto,
    "procurar_no_projeto": procurar_no_projeto,
    "ler_arquivo": ler_arquivo,
    "explicar_arquivo": explicar_arquivo,
    "indexar_projeto": indexar_projeto,
    "perguntar_projeto": perguntar_projeto,
    "abrir_site": abrir_site,
    "tocar_musica_youtube_music": tocar_musica_youtube_music,
    "criar_anotacao": criar_anotacao,
    "listar_anotacoes": listar_anotacoes,
    "criar_lembrete": criar_lembrete,
    "listar_lembretes": listar_lembretes
}


def executar_jarvis(mensagem):
    global historico_conversa

    data_atual = datetime.now().strftime("%d/%m/%Y")
    hora_atual = datetime.now().strftime("%H:%M")

    contexto = f"""
Você é o Jarvis, assistente pessoal e técnico do Mateus, inspirado no Jarvis do Homem de Ferro.

Data atual: {data_atual}
Hora atual: {hora_atual}
GitHub conectado: {GITHUB_USER}

Você possui ferramentas reais para acessar GitHub, projetos locais, arquivos, memória vetorial, navegador, YouTube Music, anotações e lembretes.

Regras:
- Use ferramentas sempre que o pedido envolver GitHub, repositório, projeto, código, arquivo, clone, VS Code, indexação, busca, navegador, música, anotação ou lembrete.
- Para abrir, clonar ou acessar projetos/repositórios no VS Code, use sempre abrir_ou_clonar_repositorio.
- Não use ferramentas inexistentes.
- Entenda referências como "ele", "esse projeto", "nele", "isso" usando o histórico.
- Se o Mateus corrigir o nome de um projeto, use esse nome nas próximas ações.
- Não diga que não tem acesso se existir ferramenta disponível.
- Não invente resultado de ferramenta.
- Datas de lembrete devem ser convertidas para o formato dd/mm/aaaa hh:mm usando a data atual como referência.
- Responda em português do Brasil, direto, espontâneo, carismático, confiante e útil.
- Seja bem-humorado e prestativo, com energia de assistente pessoal de alto nível.
- Trate o Mateus com cordialidade; pode usar "senhor" às vezes, sem exagerar.
"""

    historico_conversa.append({
        "role": "user",
        "content": mensagem
    })

    resposta = client.responses.create(
        model="gpt-4.1-mini",
        instructions=contexto,
        input=historico_conversa,
        tools=tools
    )

    while True:
        chamadas = []

        for item in resposta.output:
            if item.type == "function_call":
                chamadas.append(item)

        if not chamadas:
            texto_final = resposta.output_text

            historico_conversa.append({
                "role": "assistant",
                "content": texto_final
            })

            historico_conversa = historico_conversa[-20:]

            return texto_final

        tool_outputs = []

        for chamada in chamadas:
            nome_funcao = chamada.name
            argumentos = json.loads(chamada.arguments)

            funcao = funcoes_disponiveis.get(nome_funcao)

            if not funcao:
                resultado = f"Ferramenta não encontrada: {nome_funcao}"
            else:
                try:
                    resultado = funcao(**argumentos)
                except Exception as erro:
                    resultado = f"Erro ao executar {nome_funcao}: {erro}"

            tool_outputs.append({
                "type": "function_call_output",
                "call_id": chamada.call_id,
                "output": str(resultado)
            })

        resposta = client.responses.create(
            model="gpt-4.1-mini",
            instructions=contexto,
            input=historico_conversa + resposta.output + tool_outputs,
            tools=tools
        )


# =========================
# ATIVAÇÃO POR NOMES
# =========================

PALAVRAS_ATIVACAO = [
    "jarvis",
    "jads",
    "chaves",
    "jad",
    "jadis",
    "jaque",
    "jadson"
]


def contem_ativacao(texto):
    texto = texto.lower()
    return any(palavra in texto for palavra in PALAVRAS_ATIVACAO)


def remover_ativacao(texto):
    texto_limpo = texto

    for palavra in PALAVRAS_ATIVACAO:
        padrao = re.compile(re.escape(palavra), re.IGNORECASE)
        texto_limpo = padrao.sub("", texto_limpo, count=1)

    texto_limpo = re.sub(r"\s+", " ", texto_limpo).strip()
    texto_limpo = texto_limpo.strip(" ,.!?;:-")

    return texto_limpo


# =========================
# VOZ
# =========================

PALAVRAS_INICIAR_DIA = [
    "iniciar dia",
    "inicia dia",
    "começar dia",
    "comecar dia",
    "começa o dia",
    "comeca o dia",
    "iniciar o dia",
    "papai ta de volta",
    "papai tá de volta",
    "papai voltou",
]

recognizer = sr.Recognizer()
pygame.mixer.init()

parar_fala = False
falando = False


def parar_audio():
    global parar_fala, falando

    parar_fala = True

    try:
        pygame.mixer.music.stop()
    except Exception:
        pass

    falando = False


def falar(texto):
    global parar_fala, falando

    texto = str(texto)
    print("\nJarvis:", texto)

    parar_fala = False
    falando = True

    try:
        async def gerar_audio():
            arquivo_temp = tempfile.NamedTemporaryFile(
                delete=False,
                suffix=".mp3"
            )

            caminho_audio = arquivo_temp.name
            arquivo_temp.close()

            communicate = edge_tts.Communicate(
                text=texto,
                voice="pt-BR-AntonioNeural"
            )

            await communicate.save(caminho_audio)

            return caminho_audio

        caminho_audio = asyncio.run(gerar_audio())

        pygame.mixer.music.load(caminho_audio)
        pygame.mixer.music.play()

        while pygame.mixer.music.get_busy():
            if parar_fala:
                pygame.mixer.music.stop()
                break

            time.sleep(0.1)

        try:
            os.remove(caminho_audio)
        except Exception:
            pass

    except Exception as erro:
        print("Erro ao falar:", erro)
        registrar_erro("falar", erro)

    falando = False


def falar_em_thread(texto):
    thread = threading.Thread(
        target=falar,
        args=(texto,),
        daemon=True
    )

    thread.start()


def contem_comando_inicio_dia(texto):
    texto = texto.lower().strip()
    return any(comando in texto for comando in PALAVRAS_INICIAR_DIA)


def acao_inicio_dia():
    parar_audio()

    try:
        subprocess.Popen("code", shell=True)
    except Exception as erro:
        print("Erro ao abrir VS Code:", erro)
        registrar_erro("acao_inicio_dia_vscode", erro)

    try:
        abrir_site("https://github.com")
    except Exception as erro:
        print("Erro ao abrir GitHub:", erro)
        registrar_erro("acao_inicio_dia_github", erro)

    try:
        tocar_musica_youtube_music("AC DC")
    except Exception as erro:
        print("Erro ao abrir YouTube Music:", erro)
        registrar_erro("acao_inicio_dia_musica", erro)

    falar_em_thread("Bem-vindo de volta, senhor! Temos um ótimo dia pela frente.")


def ouvir_microfone():
    try:
        with sr.Microphone() as source:
            print("\n🎤 Ouvindo...")

            recognizer.adjust_for_ambient_noise(source, duration=0.5)

            audio = recognizer.listen(
                source,
                timeout=None,
                phrase_time_limit=8
            )

        try:
            texto = recognizer.recognize_google(
                audio,
                language="pt-BR"
            )

            print(f"\nVocê disse: {texto}")
            return texto

        except sr.UnknownValueError:
            print("Não entendi o áudio.")
            return None

        except sr.RequestError as erro:
            print("Erro no reconhecimento do Google:", erro)
            registrar_erro("recognize_google", erro)
            return None

    except Exception as erro:
        print("Erro crítico no microfone:", erro)
        registrar_erro("ouvir_microfone", erro)
        time.sleep(2)
        return None


# =========================
# THREADS
# =========================

threading.Thread(target=monitorar_lembretes, daemon=True).start()


# =========================
# LOOP PRINCIPAL
# =========================

falar_em_thread("Jarvis iniciado e ouvindo você.")

while True:
    try:
        mensagem = ouvir_microfone()

        if not mensagem:
            continue

        mensagem_lower = mensagem.lower().strip()

        if contem_comando_inicio_dia(mensagem_lower):
            acao_inicio_dia()
            continue

        if contem_ativacao(mensagem_lower) and (
            "parar" in mensagem_lower
            or "pare" in mensagem_lower
            or "silêncio" in mensagem_lower
            or "cala" in mensagem_lower
        ):
            parar_audio()
            print("\nJarvis: Fala interrompida.")
            continue

        if contem_ativacao(mensagem_lower) and (
            "encerrar" in mensagem_lower
            or "desligar" in mensagem_lower
            or "sair" in mensagem_lower
        ):
            parar_audio()
            falar("Encerrando sistema. Até mais, senhor.")
            break

        if contem_ativacao(mensagem_lower):
            comando = remover_ativacao(mensagem)

            if not comando:
                falar_em_thread("Sim, senhor?")
                continue

            resposta = executar_jarvis(comando)

            if resposta:
                falar_em_thread(resposta)

    except Exception as erro:
        print("Erro no loop principal:", erro)
        registrar_erro("loop_principal", erro)
        time.sleep(2)
