# Research AI

Sistema local de pesquisa inteligente multimodal para Linux. Coleta informações textuais, imagens, documentos e gera resumo com referências internas.

## Requisitos

- Linux
- Python 3.10+
- Acesso à internet

## Instalação

```bash
cd /sdcard/research-ai
python3 -m venv --copies /tmp/opencode/research-ai-venv  # ou .venv se o filesystem suportar
/tmp/opencode/research-ai-venv/bin/pip install -r requirements.txt
cp .env.example .env
```

Edite `.env` para configurar APIs opcionais (SearXNG, IA).

## Execução

```bash
cd /sdcard/research-ai
bash run.sh
```

Acesse local: http://127.0.0.1:8000
Deploy Render: https://research-ai-ntff.onrender.com

## Busca online no Render (proxy opcional)
O Render (free) bloqueia DuckDuckGo/Openverse. Para restaurar busca completa:
1. Crie um Cloudflare Worker (free) e cole o codigo de `cloudflare-worker.js`.
2. Copie a URL do worker (ex.: https://seu-worker.workers.dev).
3. No Render, adicione env var `SEARCH_PROXY_URL=https://seu-worker.workers.dev`.
4. Redeploy. O app usara o worker para acessar DuckDuckGo/Openverse.

Observacao importante: o Render (free) e bloqueado por DuckDuckGo/Openverse/Wikimedia, entao a busca online pode retornar 0.
Para busca completa, rode localmente e exponha com cloudflared:

```bat
run.bat
"C:\Program Files (x86)\cloudflared\cloudflared.exe" tunnel --url http://127.0.0.1:8000
```

Use a URL https://....trycloudflare.com gerada.

## APIs opcionais

- `SEARXNG_URL`: instância SearXNG.
- `AI_API_KEY`, `AI_BASE_URL`, `AI_MODEL`: provedor OpenAI-compatible para planejamento/resumo.
- Sem chaves, o sistema usa planejamento e resumo heurísticos.

## Testes

```bash
cd /sdcard/research-ai
PYTHONPATH=/sdcard/research-ai /tmp/opencode/research-ai-venv/bin/python -m pytest
```

## Estrutura

Ver diretórios `app/`, `static/`, `storage/`, `tests/`.

## Limitações conhecidas

- Sem Playwright; páginas dependentes de JavaScript podem não ser coletadas.
- Provedores de busca gratuitos podem bloquear ou limitar requisições.
- Sem modelo de visão local; relevância de imagens é heurística, com suporte opcional a API multimodal via configuração.
- Divergências entre fontes são informadas, não resolvidas automaticamente em todos os casos.
## Windows

Execute un.bat (cria venv, instala dependencias e inicia em http://127.0.0.1:8000).

