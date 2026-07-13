# Installation and Contributor Setup

This guide prepares a local development or test checkout. The application uses a Conda-managed
Python environment, locked npm dependencies, and Docker Compose for PostgreSQL and Redis. A local
LLM is optional; development and tests use fake model providers by default.

## Prerequisites

- Git
- Miniconda or Anaconda with `conda` available in the shell
- Node.js `^20.19.0` or `>=22.12.0`, including npm
- Docker with the Compose plugin, for the API, database-backed tests, and E2E tests

On Linux, ensure your user can access the Docker daemon before continuing:

```bash
docker version
docker compose version
```

## Automated setup

From the repository root, run:

```bash
./scripts/setup.sh
```

When run in a terminal, setup first asks you to choose **Interactive** or **Automatic** mode.
Interactive is the default: press Enter to select it, choose whether to install frontend and
browser-test dependencies, review every destination, and confirm before installing. Automatic mode
uses the standard frontend-enabled, browser-skipped defaults, displays the plan, and then continues
without further prompts.
When no interactive terminal is available, it displays the plan and requires an explicit `--yes`
before it will install anything.

The script is safe to run again. It:

1. Creates or updates the `offline-ai` Conda environment from `environment.yml`.
2. Installs pinned Python packages from `requirements.txt`.
3. Installs frontend packages with `npm ci` and the committed lock file.
4. Creates ignored runtime directories under `var/`.
5. Creates `config/env/local.env` from its example only when it does not already exist.

Existing local configuration is never overwritten.

Useful setup variants:

```bash
# Backend-only contributor
./scripts/setup.sh --backend-only

# Include Chromium for Playwright E2E tests
./scripts/setup.sh --with-browser

# Inspect actions without changing anything
./scripts/setup.sh --dry-run

# Force prompts, even when terminal detection is unavailable
./scripts/setup.sh --interactive

# Use the default selections without prompting
./scripts/setup.sh --automatic

# Automation/CI alias for automatic mode
./scripts/setup.sh --yes
```

Before it changes anything, the installer reports the project root, Conda environment and expected
prefix, Python requirements source, frontend `node_modules` destination, optional Playwright browser
cache, local configuration behavior, and runtime-data directories. It also explicitly states that
Docker services are not started and model weights are not downloaded. After installation, resolved
Conda, Python package, npm, configuration, and runtime paths are printed again.

Set `OIH_CONDA_ENV` to use another Conda environment name:

```bash
OIH_CONDA_ENV=offline-ai-dev ./scripts/setup.sh
```

## Start the development services

Activate the environment and start PostgreSQL and Redis:

```bash
conda activate offline-ai
docker compose -f deploy/compose.yaml up -d postgres redis
```

Apply database migrations and start the API:

```bash
./manage.py migrate
./manage.py runserver
```

In another terminal, start the web application:

```bash
cd apps/web
npm run dev
```

The default endpoints are:

- Web application: `http://127.0.0.1:5173`
- API: `http://127.0.0.1:8000`
- Interactive API documentation: `http://127.0.0.1:8000/docs`

## Local configuration

Tracked defaults live in `config/env/dev.env`. Put machine-specific paths, ports, or provider
settings in the ignored `config/env/local.env`; it is layered over the development defaults.

Do not commit secrets or personal paths. The setup script preserves an existing local file.
Configuration can also be selected for one command:

```bash
./manage.py --env-file /path/to/custom.env runserver
```

## Run checks and tests

Start PostgreSQL and Redis first, then run backend checks:

```bash
./manage.py lint
./manage.py typecheck
./manage.py test
```

Run frontend checks:

```bash
cd apps/web
npm run typecheck
npm run test:unit
npm run build
```

For browser tests, install Chromium once if it was not installed during setup:

```bash
cd apps/web
npx playwright install chromium
npm run test:e2e
```

## Manual installation

If the setup script cannot be used, run its equivalent commands from the repository root:

```bash
conda env create --file environment.yml
conda run -n offline-ai python -m pip install --requirement requirements.txt
npm --prefix apps/web ci
mkdir -p var/cache var/models var/run var/storage/documents
cp config/env/local.example.env config/env/local.env
```

Skip the final copy when `config/env/local.env` already exists.

## Troubleshooting

### Conda is unavailable

Install Miniconda or Anaconda, initialize Conda for your shell, and open a new terminal. Confirm
installation with `conda --version`.

### Docker reports permission denied

Start Docker and configure access to its daemon. On Linux this commonly means adding your user to
the Docker group and starting a new login session. Do not run project-generated files as root.

### PostgreSQL or Redis ports are already occupied

Stop the conflicting service or update the relevant ports in `deploy/compose.yaml` and local
connection URLs in `config/env/local.env`.

### Playwright cannot find a browser

Run `npx playwright install chromium` from `apps/web`, or rerun
`./scripts/setup.sh --with-browser`.

### Local model files are unavailable

No model download is needed for normal development or tests. Keep `LLM_BACKEND=fake` and
`EMBEDDING_BACKEND=fake`. See [Model runtime](mvp/model-runtime.md) for optional local inference.

## Production deployment

The contributor setup script is not a production installer. For the containerized production
stack, follow [Model runtime and production startup](mvp/model-runtime.md) and use
`deploy/compose.prod.yaml` with `config/env/prod.env`.
