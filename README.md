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

Acesse: http://127.0.0.1:8000

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