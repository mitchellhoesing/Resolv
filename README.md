# Resolv

Autonomous, stateful AI assistant that ingests git repository issues, locates code defects, and generates verified pull requests.

## Setup

```bash
python -m venv venv
# Windows: venv\Scripts\activate
# POSIX:   source venv/bin/activate
pip install -e ".[dev]"
```

Copy `.env.example` to `.env` and fill in `GITHUB_TOKEN`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, and `GITHUB_WEBHOOK_SECRET`.

## Run

CLI:
```bash
resolv run --repo owner/name --issue 123
```

Webhook server:
```bash
uvicorn resolv.webhook:app --host 0.0.0.0 --port 8080
```

## Test

```bash
pytest --cov=src --cov-report=term-missing
```
