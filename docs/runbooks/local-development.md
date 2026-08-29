# Desenvolvimento local

## Pré-requisitos

- Node.js 20 ou superior;
- Python 3.12 ou superior;
- Docker Desktop para executar o Supabase local.

## Instalação

    npm install
    python -m venv .venv
    .\.venv\Scripts\Activate.ps1
    python -m pip install -e ".\backend[dev]"

## Executar a fatia M1

Em um terminal:

    .\.venv\Scripts\Activate.ps1
    python -m uvicorn ares.api.app:app --reload --port 8000

Em outro:

    npm run dev:web

Abra http://localhost:5173 e use Simular evento.

## Supabase

    npm run db:start
    npm run db:reset
    npm run db:test

O Docker Desktop precisa estar em execução. Sem Docker, migrations e testes RLS
permanecem não executados; não considerar o banco validado.
