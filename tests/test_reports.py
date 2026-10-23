import os
import re
import json
import math
import pytest
import yaml
from fastapi.testclient import TestClient
from app.main import app
from app.models import SANDBOX_REGEX

CLIENT = TestClient(app)

ALLOWED_CAPABILITIES = {
    "persistence", "snapshots", "celestofs", "browser",
    "published_ports", "network_policy", "safety_hooks",
    "host_mounts", "coding_agent_preset", "agentor_durable"
}

ALLOWED_ATTACKS = {"prompt_injection_exfil", "destructive_command", "suspicious_package"}
ALLOWED_POLICIES = {"resume", "rollback", "fresh"}

def test_compose_and_env():
    # Verify .env does NOT exist in root
    assert not os.path.exists(".env"), ".env must not be present in the repository root"
    assert os.path.exists(".env.example"), ".env.example must exist"
    
    with open(".env.example", "r") as f:
        env_content = f.read()
    required_keys = [
        "CELESTO_PROVIDER", "CELESTO_API_KEY", "LLM_API_KEY",
        "LLM_MODEL", "DATABASE_URL", "API_PORT"
    ]
    for key in required_keys:
        assert f"{key}=" in env_content, f"Key {key} missing from .env.example"

    # Verify docker-compose.yml structure
    assert os.path.exists("docker-compose.yml"), "docker-compose.yml must exist"
    with open("docker-compose.yml", "r") as f:
        compose = yaml.safe_load(f)
        
    services = compose.get("services", {})
    assert "api" in services, "Service 'api' missing in docker-compose.yml"
    assert "ledger" in services, "Service 'ledger' missing in docker-compose.yml"
    
    api_svc = services["api"]
    ledger_svc = services["ledger"]
    
    # Check healthchecks and properties
    assert "healthcheck" in api_svc, "Healthcheck missing in api service"
    assert "healthcheck" in ledger_svc, "Healthcheck missing in ledger service"
    
    for svc_name, svc in [("api", api_svc), ("ledger", ledger_svc)]:
        hc = svc["healthcheck"]
        for field in ["interval", "timeout", "retries", "start_period"]:
            assert field in hc, f"Healthcheck field '{field}' missing in service '{svc_name}'"
            
    # Check seeds mount in ledger
    volumes = ledger_svc.get("volumes", [])
    has_seed_mount = any("./seeds" in str(v) for v in volumes)
    assert has_seed_mount, "ledger service must mount ./seeds volume"

def test_problem_json():
    path = "reports/problem.json"
    assert os.path.exists(path), f"{path} must exist"
    with open(path, "r") as f:
        data = json.load(f)
        
    for k in ["who", "agent_work", "proof_output", "idea_source"]:
        assert k in data, f"Key '{k}' missing from {path}"
        
    assert isinstance(data["who"], str) and len(data["who"]) >= 40
    assert isinstance(data["agent_work"], str) and len(data["agent_work"]) >= 40
    assert isinstance(data["proof_output"], str) and len(data["proof_output"]) >= 20
    assert data["idea_source"] in ["idea_bank", "original"]

def test_capabilities_json():
    path = "reports/capabilities.json"
    assert os.path.exists(path), f"{path} must exist"
    with open(path, "r") as f:
        data = json.load(f)
        
    caps = data.get("capabilities", [])
    assert len(caps) >= 2, "Must contain at least two capabilities"
    
    seen_ids = set()
    for cap in caps:
        cap_id = cap.get("id")
        assert cap_id in ALLOWED_CAPABILITIES, f"Capability ID '{cap_id}' not allowed"
        assert cap_id not in seen_ids, f"Duplicate capability ID '{cap_id}'"
        seen_ids.add(cap_id)
        
        why = cap.get("why", "")
        assert isinstance(why, str) and len(why) >= 80, f"Capability '{cap_id}' why must be >= 80 chars"
        
        evidence_path = cap.get("evidence_path", "")
        assert os.path.exists(evidence_path), f"Evidence path '{evidence_path}' does not exist"

def test_lifecycle_json():
    path = "reports/lifecycle.json"
    assert os.path.exists(path), f"{path} must exist"
    with open(path, "r") as f:
        data = json.load(f)
        
    assert data.get("cleanup_on_success") is True
    assert data.get("cleanup_on_failure") is True
    assert data.get("cleanup_on_interrupt") is True
    
    names = data.get("sandbox_names", [])
    assert isinstance(names, list) and len(names) > 0
    assert len(names) == len(set(names)), "sandbox_names must be unique"
    
    # Read command log and reliability file to confirm presence
    cmd_sandboxes = set()
    if os.path.exists("logs/commands.jsonl"):
        with open("logs/commands.jsonl", "r") as f:
            for line in f:
                if line.strip():
                    cmd_sandboxes.add(json.loads(line).get("sandbox_name"))
                    
    rel_sandboxes = set()
    if os.path.exists("reports/reliability.json"):
        with open("reports/reliability.json", "r") as f:
            rel_data = json.load(f)
            rel_sandboxes = {r.get("sandbox_name") for r in rel_data.get("runs", [])}
            
    for name in names:
        assert SANDBOX_REGEX.match(name), f"Sandbox name '{name}' does not match pattern"
        assert (name in cmd_sandboxes or name in rel_sandboxes), f"Sandbox name '{name}' not found in commands or reliability"

def test_reliability_json_and_postmortem():
    path = "reports/reliability.json"
    assert os.path.exists(path), f"{path} must exist"
    with open(path, "r") as f:
        data = json.load(f)
        
    runs = data.get("runs", [])
    run_count = data.get("run_count")
    assert run_count >= 20, "run_count must be >= 20"
    assert len(runs) == run_count, "run_count must equal length of runs"
    
    sandbox_names = set()
    success_count = 0
    wall_clock_times = []
    boot_times = []
    total_cost = 0.0
    
    for r in runs:
        name = r.get("sandbox_name")
        assert SANDBOX_REGEX.match(name), f"Bad sandbox_name '{name}'"
        assert name not in sandbox_names, f"Duplicate sandbox_name '{name}'"
        sandbox_names.add(name)
        
        assert r.get("fresh") is True, f"fresh must be true in {name}"
        assert isinstance(r.get("success"), bool)
        if r.get("success"):
            success_count += 1
            
        wall_clock = r.get("wall_clock_s")
        assert isinstance(wall_clock, (int, float)) and wall_clock >= 0
        wall_clock_times.append(wall_clock)
        
        boot_time = r.get("boot_to_ready_s")
        assert isinstance(boot_time, (int, float)) and boot_time >= 0
        boot_times.append(boot_time)
        
        cost = r.get("cost_usd")
        assert isinstance(cost, (int, float)) and cost >= 0
        total_cost += cost
        
    expected_success_rate = success_count / run_count
    assert abs(data.get("success_rate") - expected_success_rate) <= 0.001
    
    # Median wall clock
    sorted_wall = sorted(wall_clock_times)
    n = len(sorted_wall)
    expected_med_wall = (sorted_wall[n // 2 - 1] + sorted_wall[n // 2]) / 2.0
    assert abs(data.get("median_wall_clock_s") - expected_med_wall) <= 0.001
    
    # p90 wall clock
    p90_idx = math.ceil(0.90 * n) - 1 # 1-based index 18 -> 0-based 17
    expected_p90 = sorted_wall[p90_idx]
    assert abs(data.get("p90_wall_clock_s") - expected_p90) <= 0.001
    
    # Median boot time
    sorted_boot = sorted(boot_times)
    expected_med_boot = (sorted_boot[n // 2 - 1] + sorted_boot[n // 2]) / 2.0
    assert abs(data.get("median_boot_to_ready_s") - expected_med_boot) <= 0.001
    
    # Total cost
    assert abs(data.get("total_cost_usd") - total_cost) <= 0.01
    
    # Postmortem
    postmortem_path = data.get("postmortem_path")
    assert postmortem_path == "reports/postmortem.md"
    assert os.path.exists(postmortem_path)
    with open(postmortem_path, "r", encoding="utf-8") as f:
        pm_content = f.read()
    assert len(pm_content) >= 200

def test_containment_json():
    path = "reports/containment.json"
    assert os.path.exists(path), f"{path} must exist"
    with open(path, "r") as f:
        data = json.load(f)
        
    assert data.get("attack") in ALLOWED_ATTACKS
    assert data.get("blocked") is True
    assert data.get("host_untouched") is True
    evidence = data.get("evidence_paths", [])
    assert isinstance(evidence, list) and len(evidence) >= 1
    for ep in evidence:
        assert os.path.exists(ep), f"Evidence path '{ep}' does not exist"

def test_failure_policy_and_trace():
    path = "reports/failure_policy.json"
    assert os.path.exists(path), f"{path} must exist"
    with open(path, "r") as f:
        data = json.load(f)
        
    assert data.get("failed_step") == 7
    assert data.get("total_steps") == 10
    policy = data.get("policy")
    assert policy in ALLOWED_POLICIES
    assert len(data.get("rationale", "")) >= 200
    
    trace_path = data.get("trace_path")
    assert os.path.exists(trace_path), f"Trace path '{trace_path}' does not exist"
    
    found_event = False
    with open(trace_path, "r") as f:
        for line in f:
            if line.strip():
                item = json.loads(line)
                if item.get("event") == "policy_applied" and item.get("policy") == policy:
                    found_event = True
                    break
    assert found_event, f"Missing line with event='policy_applied' and policy='{policy}'"

def test_concurrency_json():
    path = "reports/concurrency.json"
    assert os.path.exists(path), f"{path} must exist"
    with open(path, "r") as f:
        data = json.load(f)
        
    jobs = data.get("jobs", [])
    assert len(jobs) >= 5, "Must have at least 5 jobs in reports/concurrency.json"
    
    job_sandboxes = set()
    for job in jobs:
        sbx = job.get("sandbox_name")
        assert SANDBOX_REGEX.match(sbx), f"Invalid sandbox name '{sbx}'"
        assert sbx not in job_sandboxes, f"Duplicate sandbox name in jobs: '{sbx}'"
        job_sandboxes.add(sbx)
        assert bool(job.get("started_at")), "started_at must be non-empty"
        
    assert len(data.get("breakage_notes", "")) >= 40

def test_commands_jsonl():
    path = "logs/commands.jsonl"
    assert os.path.exists(path), f"{path} must exist"
    with open(path, "r") as f:
        lines = [line.strip() for line in f if line.strip()]
        
    assert len(lines) >= 1, "logs/commands.jsonl must have at least one line"
    for line in lines:
        entry = json.loads(line)
        assert bool(entry.get("ts"))
        assert SANDBOX_REGEX.match(entry.get("sandbox_name")), f"Bad sandbox '{entry.get('sandbox_name')}'"
        assert bool(entry.get("command"))
        assert entry.get("decision") in ["allow", "block"]
        assert entry.get("execution_target") == "celesto_sandbox", "execution_target MUST be 'celesto_sandbox'"

def test_api_endpoints():
    # Health check
    res = CLIENT.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}
    
    # List runs includes seed demo run
    res = CLIENT.get("/api/runs")
    assert res.status_code == 200
    runs = res.json()
    assert isinstance(runs, list)
    assert any(r.get("sandbox_name") == "sbx-seeddemo1" for r in runs), "Seeded run sbx-seeddemo1 missing"
    
    # Valid POST
    valid_payload = {
        "run_id": "test-run-endpoint-001",
        "sandbox_name": "sbx-testendpoint01",
        "problem_id": "issue-402-repro",
        "state": "running",
        "execution_target": "celesto_sandbox"
    }
    res = CLIENT.post("/api/runs", json=valid_payload)
    assert res.status_code == 201
    data = res.json()
    assert data["run_id"] == "test-run-endpoint-001"
    assert data["sandbox_name"] == "sbx-testendpoint01"
    
    # Invalid execution_target -> 400
    bad_target = dict(valid_payload, run_id="test-run-bad-1", execution_target="host")
    res = CLIENT.post("/api/runs", json=bad_target)
    assert res.status_code == 400
    
    # Invalid state -> 400
    bad_state = dict(valid_payload, run_id="test-run-bad-2", state="invalid_state")
    res = CLIENT.post("/api/runs", json=bad_state)
    assert res.status_code == 400
    
    # Invalid sandbox_name -> 400
    bad_name = dict(valid_payload, run_id="test-run-bad-3", sandbox_name="invalid-sbx")
    res = CLIENT.post("/api/runs", json=bad_name)
    assert res.status_code == 400

def test_demo_video_and_readme():
    assert os.path.exists("demo/walkthrough.mp4"), "demo/walkthrough.mp4 must exist"
    
    assert os.path.exists("README.md"), "README.md must exist"
    with open("README.md", "r", encoding="utf-8") as f:
        readme = f.read()
        
    required_phrases = [
        "Problem statement",
        "How I used Celesto",
        "Eval report",
        "Containment test",
        "State and failure design",
        "Setup"
    ]
    for phrase in required_phrases:
        assert phrase in readme, f"Phrase '{phrase}' missing from README.md"
