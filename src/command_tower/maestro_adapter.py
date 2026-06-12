"""Maestro backend seam: the SAME Cases/Stages/HumanTasks, two backends.

The engine, CLI, eval, and webapp all talk to a ``MaestroBackend``. Two
implementations ship — exactly mirroring the SplunkRestBackend pattern in the
sibling repos (local works offline; the cloud path is real, code-complete REST
that only needs Automation Cloud credentials to go live):

* :class:`LocalMaestroBackend` — in-process. Persists cases/human-tasks/audit in
  memory and runs the offline :class:`CaseEngine`. This is what the demo, tests,
  and webapp run on; no credentials, no network.
* :class:`UiPathMaestroBackend` — the documented production path. It authenticates
  to UiPath Identity Server (OAuth 2.0 ``client_credentials`` at
  ``/identity_/connect/token``), then maps each Maestro construct onto the real
  Automation Cloud / Orchestrator REST endpoints:

      Case instance   -> Maestro process instance  (start / get / list)
      Stage transition -> process variable update
      Human Task gate  -> Action Center task (create / read / complete)
      Audit event      -> Orchestrator audit / case comment

  It activates only when ``UIPATH_CLIENT_ID`` + ``UIPATH_CLIENT_SECRET`` (and the
  org/tenant) are set. It is real, correct REST code: unit-testable against a
  mocked HTTP layer (see ``tests/test_maestro_adapter.py``) and droppable onto a
  live tenant with no other change.

The one-line switch::

    backend = make_backend()   # cloud if creds present, else local
"""

from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from typing import Any, Protocol

from .audit import AuditTrail
from .case_engine import CaseEngine
from .models import Case, HumanTask


# ---------------------------------------------------------------------------
# interface
# ---------------------------------------------------------------------------

class MaestroBackend(Protocol):
    """Anything that can host cases, surface human tasks, and record audit."""

    @property
    def label(self) -> str: ...

    def register_case(self, case: Case) -> str:
        """Create the backing Maestro case instance; return its id."""
        ...

    def advance_case(self, case: Case) -> Case:
        """Run the case forward until it blocks/terminates."""
        ...

    def pending_human_tasks(self, case_id: str | None = None) -> list[HumanTask]: ...

    def decide(self, case: Case, task_id: str, decision: str,
               operator_id: str = "operator", note: str = "") -> None: ...

    def audit_events(self, case_id: str | None = None) -> list[dict[str, Any]]: ...


# ---------------------------------------------------------------------------
# Local (default, offline)
# ---------------------------------------------------------------------------

class LocalMaestroBackend:
    """In-process Maestro backend over the offline :class:`CaseEngine`."""

    def __init__(self, engine: CaseEngine | None = None) -> None:
        self.audit = AuditTrail()
        self.engine = engine or CaseEngine(audit=self.audit)
        self.cases: dict[str, Case] = {}

    @property
    def label(self) -> str:
        return "local"

    def register_case(self, case: Case) -> str:
        self.cases[case.case_id] = case
        self.engine.audit.emit(case_id=case.case_id, stage=1, actor="engine",
                               action="case_registered",
                               detail=f"{case.competition.name} ({case.competition.track_name})")
        return case.case_id

    def advance_case(self, case: Case) -> Case:
        return self.engine.run_to_block(case)

    def pending_human_tasks(self, case_id: str | None = None) -> list[HumanTask]:
        return self.engine.pending_human_tasks(case_id)

    def decide(self, case: Case, task_id: str, decision: str,
               operator_id: str = "operator", note: str = "") -> None:
        self.engine.decide(case, task_id, decision, operator_id, note)

    def audit_events(self, case_id: str | None = None) -> list[dict[str, Any]]:
        evs = self.audit.for_case(case_id) if case_id else self.audit.events
        return [e.to_dict() for e in evs]


# ---------------------------------------------------------------------------
# UiPath Automation Cloud (documented production path, credential-gated)
# ---------------------------------------------------------------------------

class _Http:
    """Tiny urllib wrapper so the cloud backend can be mocked in tests.

    A test injects a fake ``post_form``/``post_json``/``get`` by passing an http
    object; production uses the default urllib implementation. No third-party
    HTTP dependency — same approach as the sibling SplunkRestBackend._Http.
    """

    def __init__(self, verify_tls: bool = True):
        self.verify_tls = verify_tls

    def _ctx(self):  # pragma: no cover - thin TLS shim
        if self.verify_tls:
            return None
        import ssl
        c = ssl.create_default_context()
        c.check_hostname = False
        c.verify_mode = ssl.CERT_NONE
        return c

    def _send(self, method: str, url: str, *, data: bytes | None = None,
              headers: dict[str, str] | None = None) -> str:
        req = urllib.request.Request(url, data=data, method=method)
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        with urllib.request.urlopen(req, context=self._ctx()) as resp:  # pragma: no cover
            return resp.read().decode("utf-8")

    def post_form(self, url: str, form: dict[str, str],
                  headers: dict[str, str] | None = None) -> str:
        body = urllib.parse.urlencode(form).encode()
        h = {"Content-Type": "application/x-www-form-urlencoded", **(headers or {})}
        return self._send("POST", url, data=body, headers=h)

    def post_json(self, url: str, obj: dict[str, Any],
                  headers: dict[str, str] | None = None) -> str:
        body = json.dumps(obj).encode()
        h = {"Content-Type": "application/json", **(headers or {})}
        return self._send("POST", url, data=body, headers=h)

    def get(self, url: str, headers: dict[str, str] | None = None) -> str:
        return self._send("GET", url, headers=headers)


class UiPathMaestroBackend:
    """Maps Cases/Stages/HumanTasks onto live Automation Cloud REST endpoints.

    Endpoints used (Automation Cloud, documented):

    * Auth:    ``POST {base}/identity_/connect/token``
               (OAuth2 ``client_credentials``, scope ``OR.Default``)
    * Cases:   ``POST {orch}/maestro_/api/v1/process-instances`` (start),
               ``GET  {orch}/maestro_/api/v1/process-instances/{id}`` (get),
               ``GET  {orch}/maestro_/api/v1/process-instances`` (list)
    * Tasks:   ``POST {orch}/orchestrator_/tasks/AppTasks/CreateAppTask``
               ``GET  {orch}/orchestrator_/odata/Tasks`` (read)
               ``POST {orch}/orchestrator_/odata/Tasks/UiPath.Server.Configuration.OData.CompleteTask``
    * Audit:   ``POST {orch}/maestro_/api/v1/process-instances/{id}/comments``

    All Orchestrator calls send the ``X-UIPATH-OrganizationUnitId`` (folder)
    header. The class never logs the client secret or token.
    """

    TOKEN_PATH = "/identity_/connect/token"
    TOKEN_SCOPE = "OR.Default"

    def __init__(self, *, base_url: str, client_id: str, client_secret: str,
                 org: str, tenant: str, folder_id: str = "",
                 maestro_process_key: str = "CompetitionCommandTower",
                 http: _Http | None = None, verify_tls: bool = True):
        self.base_url = base_url.rstrip("/")
        self.client_id = client_id
        self._client_secret = client_secret
        self.org = org
        self.tenant = tenant
        self.folder_id = folder_id
        self.maestro_process_key = maestro_process_key
        self.http = http or _Http(verify_tls)
        self._token: str | None = None
        self._token_exp: float = 0.0

    @property
    def label(self) -> str:
        return f"uipath:{self.org}/{self.tenant}"

    # ---- org/tenant scoped base for Orchestrator OData ---------------------
    @property
    def orch_base(self) -> str:
        return f"{self.base_url}/{self.org}/{self.tenant}"

    # ---- auth -------------------------------------------------------------
    def _auth_headers(self) -> dict[str, str]:
        token = self._ensure_token()
        h = {"Authorization": f"Bearer {token}"}
        if self.folder_id:
            h["X-UIPATH-OrganizationUnitId"] = self.folder_id
        return h

    def _ensure_token(self) -> str:
        if self._token and time.time() < self._token_exp - 60:
            return self._token
        resp = self.http.post_form(self.base_url + self.TOKEN_PATH, {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self._client_secret,
            "scope": self.TOKEN_SCOPE,
        })
        obj = json.loads(resp)
        token = obj.get("access_token")
        if not token:
            raise RuntimeError("UiPath Identity did not return an access_token")
        self._token = token
        self._token_exp = time.time() + float(obj.get("expires_in", 3600))
        return token

    # ---- cases ------------------------------------------------------------
    def register_case(self, case: Case) -> str:
        """Start a Maestro process instance for this competition case."""
        payload = {
            "processKey": self.maestro_process_key,
            "inputArguments": {
                "competitionKey": case.competition.key,
                "competitionName": case.competition.name,
                "rulesUrl": case.competition.rules_url,
                "deadlineRaw": case.competition.deadline_raw,
                "trackName": case.competition.track_name,
                "requiredAssets": case.competition.required_assets,
                "credentialRefs": case.competition.credential_refs,
            },
        }
        resp = self.http.post_json(
            f"{self.orch_base}/maestro_/api/v1/process-instances",
            payload, headers=self._auth_headers())
        obj = json.loads(resp)
        return obj.get("instanceId") or obj.get("id") or case.case_id

    def get_case(self, instance_id: str) -> dict[str, Any]:
        resp = self.http.get(
            f"{self.orch_base}/maestro_/api/v1/process-instances/"
            f"{urllib.parse.quote(instance_id)}",
            headers=self._auth_headers())
        return json.loads(resp)

    def list_cases(self) -> list[dict[str, Any]]:
        resp = self.http.get(
            f"{self.orch_base}/maestro_/api/v1/process-instances"
            f"?processKey={urllib.parse.quote(self.maestro_process_key)}",
            headers=self._auth_headers())
        obj = json.loads(resp)
        return obj.get("value", obj.get("instances", []))

    def advance_case(self, case: Case) -> Case:  # pragma: no cover - live path
        """In the cloud, Maestro itself advances the instance; we poll status.

        The offline engine drives the demo; against a live tenant the case is
        advanced by the deployed Maestro process, so this maps to a status
        refresh rather than local execution.
        """
        status = self.get_case(case.case_id)
        case.status = status.get("status", case.status)
        return case

    # ---- human tasks (Action Center) -------------------------------------
    def create_app_task(self, case: Case, task: HumanTask) -> str:
        payload = {
            "title": task.title,
            "priority": "Medium",
            "data": {"prompt": task.prompt, "options": task.options,
                     **task.context},
            "appId": self.maestro_process_key,
        }
        resp = self.http.post_json(
            f"{self.orch_base}/orchestrator_/tasks/AppTasks/CreateAppTask",
            payload, headers=self._auth_headers())
        obj = json.loads(resp)
        return str(obj.get("Id") or obj.get("id") or task.task_id)

    def pending_human_tasks(self, case_id: str | None = None) -> list[HumanTask]:  # pragma: no cover - live path
        resp = self.http.get(
            f"{self.orch_base}/orchestrator_/odata/Tasks"
            "?$filter=Status eq 'Unassigned' or Status eq 'Pending'",
            headers=self._auth_headers())
        obj = json.loads(resp)
        out: list[HumanTask] = []
        for t in obj.get("value", []):
            out.append(HumanTask(
                task_id=str(t.get("Id")), case_id=case_id or "",
                stage=int(t.get("Data", {}).get("stage", 0)),
                title=t.get("Title", ""), prompt=t.get("Data", {}).get("prompt", ""),
                options=t.get("Data", {}).get("options", []),
                context=t.get("Data", {})))
        return out

    def decide(self, case: Case, task_id: str, decision: str,
               operator_id: str = "operator", note: str = "") -> None:  # pragma: no cover - live path
        payload = {"taskId": int(task_id) if task_id.isdigit() else task_id,
                   "data": {"decision": decision, "note": note},
                   "action": decision}
        self.http.post_json(
            f"{self.orch_base}/orchestrator_/odata/Tasks/"
            "UiPath.Server.Configuration.OData.CompleteTask",
            payload, headers=self._auth_headers())

    # ---- audit ------------------------------------------------------------
    def post_audit_comment(self, instance_id: str, text: str) -> None:  # pragma: no cover - live path
        self.http.post_json(
            f"{self.orch_base}/maestro_/api/v1/process-instances/"
            f"{urllib.parse.quote(instance_id)}/comments",
            {"text": text}, headers=self._auth_headers())

    def audit_events(self, case_id: str | None = None) -> list[dict[str, Any]]:  # pragma: no cover - live path
        resp = self.http.get(
            f"{self.orch_base}/maestro_/api/v1/process-instances/"
            f"{urllib.parse.quote(case_id or '')}/comments",
            headers=self._auth_headers())
        return json.loads(resp).get("value", [])


# ---------------------------------------------------------------------------
# selector
# ---------------------------------------------------------------------------

def make_backend(*, engine: CaseEngine | None = None) -> MaestroBackend:
    """Return the live UiPath backend if credentials are present, else local.

    This is the one-line switch the orchestrator/CLI/webapp use; nothing else
    changes between modes.
    """
    cid = os.environ.get("UIPATH_CLIENT_ID")
    secret = os.environ.get("UIPATH_CLIENT_SECRET")
    if cid and secret:
        return UiPathMaestroBackend(
            base_url=os.environ.get("UIPATH_BASE_URL", "https://cloud.uipath.com"),
            client_id=cid, client_secret=secret,
            org=os.environ.get("UIPATH_ORG", "myorg"),
            tenant=os.environ.get("UIPATH_TENANT", "DefaultTenant"),
            folder_id=os.environ.get("UIPATH_FOLDER_ID", ""),
            verify_tls=os.environ.get("UIPATH_VERIFY_TLS", "1") not in ("0", "false", "no"),
        )
    return LocalMaestroBackend(engine=engine)
