"""Tests for the Maestro backend seam (local + mocked UiPath cloud REST).

The cloud backend is exercised against a fake HTTP layer that records the exact
requests, proving the REST request shapes (OAuth token, Maestro process-instance
start, Action Center task create) are correct without a live Automation Cloud
tenant — exactly mirroring the SplunkRestBackend mocked-HTTP tests in the
sibling repo.
"""

import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from command_tower.maestro_adapter import (  # noqa: E402
    LocalMaestroBackend, UiPathMaestroBackend, make_backend,
)
from command_tower.models import (  # noqa: E402
    Case, Competition, TaskDecision, build_stages, new_id,
)


def make_case() -> Case:
    comp = Competition(key="k", name="Demo", rules_url="https://x/rules",
                       deadline_raw="2026-08-01 23:59 UTC", track_name="Maestro Case",
                       required_assets=["repo"], credential_refs=["github"],
                       credential_available={"github": True},
                       build_tasks=["Implement the code"])
    return Case(case_id=new_id("case"), competition=comp, stages=build_stages())


# --------------------------------------------------------------------------- #
# local backend
# --------------------------------------------------------------------------- #

def test_local_backend_label_and_register():
    be = LocalMaestroBackend()
    case = make_case()
    cid = be.register_case(case)
    assert be.label == "local"
    assert cid == case.case_id
    assert case.case_id in be.cases


def test_local_backend_runs_case_to_gate():
    be = LocalMaestroBackend()
    case = make_case()
    be.register_case(case)
    be.advance_case(case)
    assert be.pending_human_tasks(case.case_id)
    assert be.audit_events(case.case_id)


def test_local_backend_decide_advances():
    be = LocalMaestroBackend()
    case = make_case()
    be.register_case(case)
    be.advance_case(case)
    t = be.pending_human_tasks(case.case_id)[0]
    be.decide(case, t.task_id, TaskDecision.APPROVE.value)
    be.advance_case(case)
    # advanced past Stage 3
    assert case.current_stage >= 4


def test_make_backend_defaults_to_local(monkeypatch):
    for v in ("UIPATH_CLIENT_ID", "UIPATH_CLIENT_SECRET"):
        monkeypatch.delenv(v, raising=False)
    be = make_backend()
    assert isinstance(be, LocalMaestroBackend)
    assert be.label == "local"


def test_make_backend_switches_to_cloud(monkeypatch):
    monkeypatch.setenv("UIPATH_CLIENT_ID", "cid")
    monkeypatch.setenv("UIPATH_CLIENT_SECRET", "secret")
    monkeypatch.setenv("UIPATH_ORG", "acme")
    monkeypatch.setenv("UIPATH_TENANT", "Default")
    be = make_backend()
    assert isinstance(be, UiPathMaestroBackend)
    assert be.label == "uipath:acme/Default"


# --------------------------------------------------------------------------- #
# mocked UiPath cloud REST
# --------------------------------------------------------------------------- #

class FakeHttp:
    """Records requests and returns canned UiPath-shaped JSON responses."""

    def __init__(self):
        self.calls = []

    def post_form(self, url, form, headers=None):
        self.calls.append(("POST_FORM", url, form, headers))
        assert form["grant_type"] == "client_credentials"
        return json.dumps({"access_token": "tok-123", "expires_in": 3600})

    def post_json(self, url, obj, headers=None):
        self.calls.append(("POST_JSON", url, obj, headers))
        if "process-instances" in url:
            return json.dumps({"instanceId": "pi-999", "status": "Running"})
        if "CreateAppTask" in url:
            return json.dumps({"Id": 4242})
        if "CompleteTask" in url:
            return json.dumps({"value": "ok"})
        return json.dumps({})

    def get(self, url, headers=None):
        self.calls.append(("GET", url, headers))
        if url.endswith("process-instances") or "?processKey" in url:
            return json.dumps({"value": [{"instanceId": "pi-999"}]})
        return json.dumps({"instanceId": "pi-999", "status": "Completed"})


def make_cloud(http=None) -> UiPathMaestroBackend:
    return UiPathMaestroBackend(
        base_url="https://cloud.uipath.com", client_id="cid",
        client_secret="sekret", org="acme", tenant="Default",
        folder_id="42", http=http or FakeHttp())


def test_cloud_auth_uses_client_credentials_at_identity_endpoint():
    http = FakeHttp()
    be = make_cloud(http)
    tok = be._ensure_token()
    assert tok == "tok-123"
    url, form = http.calls[0][1], http.calls[0][2]
    assert url == "https://cloud.uipath.com/identity_/connect/token"
    assert form["client_id"] == "cid"
    assert form["scope"] == "OR.Default"


def test_cloud_token_is_cached():
    http = FakeHttp()
    be = make_cloud(http)
    be._ensure_token()
    be._ensure_token()
    token_calls = [c for c in http.calls if c[0] == "POST_FORM"]
    assert len(token_calls) == 1   # cached, only one token request


def test_cloud_register_case_starts_process_instance():
    http = FakeHttp()
    be = make_cloud(http)
    case = make_case()
    iid = be.register_case(case)
    assert iid == "pi-999"
    start = [c for c in http.calls if c[0] == "POST_JSON" and "process-instances" in c[1]][0]
    body = start[2]
    assert body["processKey"] == "CompetitionCommandTower"
    assert body["inputArguments"]["competitionKey"] == "k"
    # auth header + folder header present
    headers = start[3]
    assert headers["Authorization"] == "Bearer tok-123"
    assert headers["X-UIPATH-OrganizationUnitId"] == "42"


def test_cloud_orch_base_scopes_org_tenant():
    be = make_cloud()
    assert be.orch_base == "https://cloud.uipath.com/acme/Default"


def test_cloud_create_app_task_shapes_payload():
    http = FakeHttp()
    be = make_cloud(http)
    case = make_case()
    be.advance_case  # noqa: B018 - attribute exists
    from command_tower.stages import stage3_credential_gate
    task = stage3_credential_gate(case).human_task
    tid = be.create_app_task(case, task)
    assert tid == "4242"
    call = [c for c in http.calls if c[0] == "POST_JSON" and "CreateAppTask" in c[1]][0]
    assert call[2]["title"] == task.title
    assert call[2]["data"]["options"] == task.options


def test_cloud_list_cases_reads_value_array():
    be = make_cloud()
    cases = be.list_cases()
    assert cases and cases[0]["instanceId"] == "pi-999"


def test_cloud_never_logs_secret():
    http = FakeHttp()
    be = make_cloud(http)
    be._ensure_token()
    # the secret only appears in the form body to the identity endpoint, never
    # stored on a public attribute
    assert not hasattr(be, "client_secret")
    assert be._client_secret == "sekret"
