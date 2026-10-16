# Personal AI Assistant Platform

A standalone product application for creating privately owned AI assistants, indexing user knowledge through RAG Core, testing answers through the AI Application Backend, publishing a website chat widget, and connecting Telegram bots.

The product lives in this directory and has its own Git repository. The sibling `../../core/rag_core` and `../../core/ai_application_backend` projects remain independently deployed services. The product calls their documented HTTP APIs only; it does not import their Python packages, query their databases, or access their files.

## What is implemented

- Django 5.2 / DRF API with email/password registration, JWT login/refresh, profile, migrations, admin, and OpenAPI.
- Assistant CRUD with a dedicated Core knowledge base and AI Backend assistant provisioned on create. Server-side ownership checks are used on every private resource path.
- Text, PDF, DOCX, TXT, and Markdown sources; a database-backed worker uploads sources and reports `indexed` only after Core returns its documented synchronous `completed` status.
- Website discovery as a worker job, sitemap and same-origin link discovery, page limits, depth, robots policy, page preview, manual selection and automatic processing.
- Extraction adapters for local HTML, Jina Reader, and Firecrawl. Optional adapters need server-side credentials. Extracted content is persisted before Core upload so a retry does not repeat extraction.
- Shared conversation routing for dashboard playground, public web widget, and Telegram. The AI Backend owns generation and conversation history; the product persists its own channel conversation/message record.
- Public widget execution is rate-limited and requires an active assistant with widget publication enabled. Widget source is a standalone custom element using Shadow DOM and safe text rendering.
- Telegram token validation, encrypted-at-rest token storage, hashed webhook secrets, webhook setup/removal, inbound update deduplication, and text replies.
- Product-only Docker Compose with PostgreSQL, backend, database-backed worker, and Next.js frontend.

## Architecture and integration boundary

The upstream services expose API-key-scoped resources. The product uses a server-side RAG Core API key to create knowledge bases and ingest documents, and a server-side AI Backend API key to create assistants and persistent conversations. The AI Backend makes retrieval calls using the encrypted RAG credential attached to its own upstream tenant.

**Important tenant setup:** the `RAG_CORE_API_KEY` supplied to this product and the RAG key configured on the AI Backend tenant must belong to the same RAG Core tenant. Otherwise ingestion can succeed while AI retrieval receives a knowledge-base 404. The current upstream services do not expose public tenant-provisioning or per-product-user credential APIs, so a service administrator must create the two upstream API clients and keep this tenant/key association aligned. Product users are isolated by local owner foreign keys and server-side querysets; upstream records are held under those configured service tenants.

The AI Backend currently exposes a configurable provider/model execution contract but no model-capability or allowed-model listing endpoint. Therefore the product takes one server-configured `AI_DEFAULT_MODEL`; users cannot submit provider keys or arbitrary model requests. Verify that model ID is configured in the AI Backend before creating assistants.

No duplicate Core/AI databases or containers are started by the product Compose file. On Docker Desktop/WSL, the product reaches the existing services through `host.docker.internal` and their published host ports. The current Core upload and AI generation APIs are synchronous; long-running website discovery and source upload orchestration run in the product's single lightweight database-polling worker, while the existing Core remains responsible for extraction (supported file formats), chunking, embeddings, vector storage, and retrieval.

## Configure upstream service credentials

Start and configure RAG Core and the AI Backend separately, following each service's own README. On a RAG Core deployment with an existing authorized admin shell, create/reuse the product service tenant and create an API client:

```bash
cd ../../core/rag_core
python manage.py create_api_client personal-ai-product personal-ai-product
```

The Core command prints the key once. Keep it private; it is the value for `RAG_CORE_API_KEY`.

On AI Backend, create the matching service tenant/client. The command prompts for that tenant's RAG Core API key; enter the key belonging to the same Core tenant:

```bash
cd ../ai_application_backend
python manage.py create_api_client \
  --tenant-name "Personal AI Product" \
  --tenant-slug personal-ai-product \
  --client-name personal-ai-product
```

Keep the generated AI Backend key private as `AI_BACKEND_API_KEY`. Configure the AI Backend's own provider variables (`AI_PROVIDER_API_KEY`, base URL, and other provider settings) in the AI Backend deployment, not in this product's frontend. The actual model ID to set in product `AI_DEFAULT_MODEL` must be supported by that Backend's configured provider.

## Docker Compose on WSL

Use Docker Desktop with WSL integration enabled. For best file performance, keep a Linux-based development checkout under `~/src` rather than building from `/mnt/c`.

From this directory in a WSL shell:

```bash
cp .env.example .env
```

Edit `.env` before starting. Set both upstream API keys and a valid `AI_DEFAULT_MODEL`. Replace local database and Django secrets for any shared or deployed environment. Keep `DEBUG=True` only for local development. For a non-local deployment, set `DEBUG=False`, a unique `DJANGO_SECRET_KEY`, a stable independent `CREDENTIAL_ENCRYPTION_KEY`, production `ALLOWED_HOSTS`, HTTPS origins, and `SECURE_SSL_REDIRECT=True`.

Build and start the product services:

```bash
docker compose config --quiet
docker compose build
docker compose up -d
docker compose ps
docker compose logs -f backend worker frontend
```

The backend container applies migrations before starting Gunicorn. The worker waits for backend health before polling. Visit `http://localhost:3000`; API health and docs are at `http://localhost:8002/health/` and `http://localhost:8002/api/docs/`.

Useful lifecycle and maintenance commands:

```bash
docker compose exec backend python manage.py createsuperuser
docker compose exec backend python manage.py test
docker compose exec backend python manage.py check
docker compose exec backend python manage.py makemigrations --check --dry-run
docker compose logs -f worker
docker compose down
```

**Destructive local reset only:** this removes the product's database and uploaded files, not the independent RAG Core or AI Backend:

```bash
docker compose down -v
```

## Local development without Docker

Python 3.12 and Node 20+ are recommended. Copy `.env.example` to `.env`; for local processes, change the integration origins to host-reachable URLs such as `http://127.0.0.1:8000` for Core and `http://127.0.0.1:8001` for AI Backend. The default SQLite URL is for local development only.

Terminal 1, from the product root:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r backend/requirements.txt
python backend/manage.py migrate
python backend/manage.py createsuperuser
python backend/manage.py runserver 0.0.0.0:8002
```

Terminal 2:

```bash
cd frontend
npm ci
npm run dev
```

Terminal 3:

```bash
cd backend
python manage.py runworker
```

The worker stores extracted page content and ingestion state in PostgreSQL/SQLite. It processes pending work continuously; Ctrl+C stops it. To process one queue pass in a test:

```bash
python manage.py runworker --once
```

## API overview

All product application routes are under `/api/v1/`. Dashboard endpoints require `Authorization: Bearer <JWT>`; widget and Telegram webhook endpoints are public but rate-limited or secret-validated as appropriate.

| Endpoint | Purpose |
|---|---|
| `POST /api/v1/auth/register/` | Create a user and return access/refresh tokens |
| `POST /api/v1/auth/token/` | Obtain tokens (`username` is the registered email) |
| `POST /api/v1/auth/token/refresh/` | Refresh access token |
| `GET /api/v1/auth/me/` | Current account profile |
| `/api/v1/assistants/` | Owned assistant CRUD |
| `/api/v1/assistants/{id}/sources/` | List and queue text/file sources |
| `/api/v1/assistants/{id}/sources/{source_id}/retry/` | Retry an eligible failed source |
| `/api/v1/assistants/{id}/crawls/` | Queue discovery and list jobs |
| `/api/v1/assistants/{id}/crawls/{job_id}/process/` | Submit the selected discovered URLs |
| `/api/v1/conversations/` | Owner-scoped conversation list/create |
| `/api/v1/conversations/{id}/messages/` | Read history or submit a message |
| `POST /api/v1/widget/init/` | Create/resume an enabled public widget conversation |
| `POST /api/v1/widget/messages/` | Send a widget message |
| `/api/v1/assistants/{id}/telegram/` | Validate, connect, inspect, or disconnect Telegram |
| `POST /api/v1/webhooks/telegram/{assistant_id}/` | Secret-header-validated Telegram webhook |
| `GET /api/schema/`, `/api/docs/` | Generated OpenAPI schema and Swagger UI |
| `GET /health/` | Liveness check |

DRF validation and integration failures return explicit non-success HTTP responses. Upstream credentials, provider credentials, and saved Telegram tokens are never returned from dashboard APIs.

## Website crawler security and behavior

Discovery permits only HTTP/HTTPS URLs on public IPs and ports 80/443. Every request resolves all DNS answers, rejects any non-public address, connects directly to one of those validated IPs (no second DNS lookup by the HTTP client), and validates redirect destinations independently. TLS certificate validation and SNI continue to use the requested hostname. The crawler is same-origin only, honors robots rules by default, blocks access when robots policy is unavailable or malformed, limits redirects, page count, depth, response bytes, request time, and per-domain pacing. The response is not rendered in a browser; local extraction does not support JavaScript-only pages.

Manual discovery stores candidate metadata and waits for the user to select pages. Automatic discovery processes pages up to `CRAWLER_MAX_PAGES` (hard capped at 500). Cancellation is checked between pages and cannot interrupt a request already in progress. External Jina/Firecrawl adapters receive only a URL already validated by the product; their remote fetch and redirect behavior is ultimately governed by those providers.

The current API contract of RAG Core ingests synchronously and does not provide an asynchronous job resource or an explicit document-status polling operation. The product verifies the upload response's actual `completed` status and reports a failure otherwise. Existing source content remains available for retry, but if Core reports a non-completed state without a retrievable document status, the product cannot independently determine whether that remote document will finish later.

## Widget

Enable **Web widget** on the assistant, save the settings, host `widget/widget.js` on your own HTTPS site or static host, and embed:

```html
<script src="https://YOUR-DOMAIN/widget.js" defer></script>
<personal-ai-widget
  assistant-id="PUBLIC-ASSISTANT-ID"
  api-base="https://YOUR-API-DOMAIN">
</personal-ai-widget>
```

The public identifier is not a secret. The widget stores a random conversation ID in the visitor's local storage and renders all assistant content as text, never as HTML. Add your dashboard and publishing origins to `CORS_ALLOWED_ORIGINS`; add intended website origins to `WIDGET_ALLOWED_ORIGINS`. Origin checks are an additional filter, not authentication. Public execution also uses a server-side IP rate limit.

For a local demo, serve `widget/` over HTTP (not `file://`), update the placeholder assistant ID in `widget/demo.html`, then visit the page:

```bash
cd widget
python -m http.server 8080
```

## Telegram

Set `TELEGRAM_WEBHOOK_BASE_URL` to the public HTTPS origin of the product API before connecting a bot. In Assistant → Channels, paste the BotFather token once. The API calls Telegram `getMe` and `setWebhook`, encrypts the token using `CREDENTIAL_ENCRYPTION_KEY`, stores only a hash of the webhook secret, and never returns the bot token. Without a publicly reachable HTTPS origin, the bot is safely saved but inbound webhook delivery is inactive. Configure inbound reachability and test via a real Telegram bot after deployment.

## Environment variables

All product settings and placeholder-only secrets are documented in `.env.example`. In particular:

- `DJANGO_SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`, `SECURE_SSL_REDIRECT`: Django runtime.
- `DATABASE_URL`, `POSTGRES_*`: product database (Compose config overrides `DATABASE_URL` to the Compose database).
- `AI_BACKEND_BASE_URL`, `AI_BACKEND_API_KEY`, `AI_DEFAULT_MODEL`: upstream execution API and server-side model choice.
- `RAG_CORE_BASE_URL`, `RAG_CORE_API_KEY`: upstream knowledge API.
- `CRAWLER_EXTRACTOR`, `CRAWLER_FALLBACK`, `CRAWLER_*`, `JINA_*`, `FIRECRAWL_*`: crawler behavior and optional extraction.
- `CREDENTIAL_ENCRYPTION_KEY`: stable server-side encryption root for Telegram bot tokens.
- `CORS_ALLOWED_ORIGINS`, `WIDGET_ALLOWED_ORIGINS`: browser and widget origin policy.
- `TELEGRAM_WEBHOOK_BASE_URL`: public HTTPS product API origin for bot webhooks.

Do not place any upstream key, provider key, Telegram token, Django secret, or encryption key in a `NEXT_PUBLIC_*` variable or commit a real `.env`.

## Tests and checks

From the product root:

```bash
python backend/manage.py check
python backend/manage.py makemigrations --check --dry-run
python backend/manage.py test
cd frontend
npm ci
npm test
npm run lint
npm run typecheck
npm run build
```

Backend tests use SQLite and mocked upstream HTTP contracts; widget tests run under jsdom and verify conversation continuity and safe text rendering. No test sends requests to live AI, RAG, Jina, Firecrawl, or Telegram services. Live integration checks require configured upstream services and credentials; the standard automated test suite does not claim those external deployments are healthy.

Docker Compose configuration/build and container smoke tests should be run from WSL with Docker Desktop enabled. If Compose is unavailable, local Python/Node checks above remain usable; do not treat them as proof of container behavior.

## Current limitations

- Upstream tenant/client provisioning is administrative and must be completed outside the product; local user records do not create upstream tenants.
- Model discovery/allowlist validation cannot be implemented against the current AI Backend contract; one server-side configured model is used.
- The upstream RAG API is synchronous; the product's worker isolates long-running requests from dashboard requests but cannot make the Core ingestion itself asynchronous.
- The product uses a single configured integration credential pair. Product-level owner isolation is enforced locally; independent upstream credentials per product user are not available through the documented APIs.
- Telegram and paid extractor integrations remain unverified until real credentials and reachable public URLs are supplied.
