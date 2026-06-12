"""Tests for multi-agent work routing + the deterministic simulated executor."""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from command_tower.agents import (  # noqa: E402
    AgentLane, SimulatedExecutor, WorkRouter, classify_task,
)


def test_classify_task_routes_keywords():
    assert classify_task("Write the pytest suite") == "tests"
    assert classify_task("Implement the API endpoint") == "code"
    assert classify_task("Draft the README wording") == "wording"
    assert classify_task("Brainstorm alternative ideas") == "ideation"
    assert classify_task("Push the repo and tag a release") == "repo_ops"
    assert classify_task("Produce the demo narration") == "demo_script"


def test_classify_task_default_is_code():
    assert classify_task("something totally unrelated") == "code"


def test_router_assigns_primary_lane():
    r = WorkRouter()
    packets = r.route("case-1", ["Implement the code"])
    assert packets[0].lane == AgentLane.CODEX.value
    assert packets[0].primary_lane == AgentLane.CODEX.value


def test_router_falls_back_when_lane_disabled():
    r = WorkRouter(disabled_lanes={AgentLane.CODEX.value})
    packets = r.route("case-1", ["Implement the code"])
    assert packets[0].lane == AgentLane.CLAUDE_CODE.value   # backup
    assert r.fallbacks and r.fallbacks[0][1] == AgentLane.CODEX.value


def test_router_assigns_architecture_to_claude():
    r = WorkRouter()
    packets = r.route("c", ["Review the architecture and refactor"])
    assert packets[0].lane == AgentLane.CLAUDE_CODE.value


def test_executor_is_deterministic():
    r = WorkRouter()
    p = r.route("c", ["Implement the code"])[0]
    ex = SimulatedExecutor()
    r1 = ex.execute(p)
    r2 = ex.execute(p)
    assert r1.artifact == r2.artifact
    assert r1.status == "done" and r1.public_safe


def test_executor_credential_boundary_blocks():
    r = WorkRouter()
    p = r.route("c", ["Make a live platform call now"])[0]
    res = SimulatedExecutor().execute(p)
    assert res.status == "blocked"
    assert res.blocker_code == "CREDENTIAL_BLOCKED"


def test_executor_secret_artifact_is_unsafe_until_scrubbed():
    r = WorkRouter()
    p = r.route("c", ["Implement code with the api key secret"])[0]
    ex = SimulatedExecutor()
    unsafe = ex.execute(p)
    assert not unsafe.public_safe
    safe = ex.execute(p, scrubbed=True)
    assert safe.public_safe


def test_executor_attributes_agent_id():
    r = WorkRouter()
    p = r.route("c", ["Implement the code"])[0]
    res = SimulatedExecutor().execute(p)
    assert "@command-tower" in res.agent_id
