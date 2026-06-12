# Automation Cloud Deploy Runbook

The same code runs locally (offline demo/tests) and against a live **UiPath
Automation Cloud** tenant. `make_backend()` (in `src/command_tower/maestro_adapter.py`)
returns the `UiPathMaestroBackend` automatically when five environment variables
are present, otherwise the `LocalMaestroBackend`. No code change is needed to go
live — only credentials.

## 1. One-time setup in Automation Cloud (≈5 min)
1. Create a free **UiPath Automation Cloud** account (Google SSO is fine).
2. In **Admin → Tenant → Maestro**, enable Maestro for the tenant.
3. In **Admin → External Applications → Add Application**:
   - Application type: **Confidential application** (OAuth `client_credentials`).
   - Add scopes: `OR.Execution`, `OR.Folders`, `OR.Jobs`, and the Maestro
     process scopes (`OR.Maestro` / process-instances) + Action Center
     (`OR.Tasks`) so the case engine can create process instances and human tasks.
   - Save and copy the **Client ID** and **Client Secret**.
4. Note your **org** (account logical name), **tenant** name, and the target
   **Folder ID** (Orchestrator → Folders → the folder's settings).

## 2. Set the five variables
```bash
export UIPATH_CLIENT_ID="<client id>"
export UIPATH_CLIENT_SECRET="<client secret>"
export UIPATH_ORG="<account logical name>"
export UIPATH_TENANT="<tenant name>"        # e.g. DefaultTenant
export UIPATH_FOLDER_ID="<folder id>"
# optional: export UIPATH_BASE_URL="https://cloud.uipath.com"  (default)
```

## 3. Deploy — one command
```bash
pip install -r webapp/requirements.txt        # fastapi/uvicorn/pydantic
PYTHONPATH=src python -m command_tower          # drives all 6 cases live via Maestro
```
`make_backend()` detects the credentials and routes every case transition,
human task, and audit event through the Automation Cloud REST API
(`UiPathMaestroBackend`). With no credentials the identical command runs the
offline `LocalMaestroBackend` — that is how the demo and the 58 tests run.

Confirm which backend is active:
```bash
PYTHONPATH=src python -c "from command_tower.maestro_adapter import make_backend; print(type(make_backend()).__name__)"
# UiPathMaestroBackend  (creds present)  |  LocalMaestroBackend (none)
```

## 4. For the Devpost submission
- After step 3, the cases appear as live Maestro **process instances** in
  Automation Cloud and their human tasks in **Action Center**.
- Paste the tenant's Maestro/Orchestrator URL (the live project) into the
  Devpost **"Live Automation Cloud URL"** field — this satisfies the
  "running solution on UiPath Automation Cloud" required asset.
- Repo, video, deck, and description are already prepared (see
  `docs/devpost_submission.md`).

## Safety
- Credentials live only in your shell/CI secret store — never commit them.
  `.gitignore` covers `.env`, `out/`, and caches.
- The OAuth token is fetched at runtime via `client_credentials`; it is never
  written to disk by this project.
