import os
import json
import logging
import signal
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from app.celesto_client import CelestoSandbox, CommandResult

logger = logging.getLogger("celesto_agent")

class CommandBlockedError(Exception):
    """Raised when a pre-execution safety hook detects and blocks a malicious command."""
    pass

class SafetyHookManager:
    """
    Control plane safety hook inspector.
    Evaluates every command string against security rules BEFORE dispatching to the guest microVM.
    """
    DISALLOWED_PATTERNS = [
        "rm -rf /",
        "--no-preserve-root",
        "169.254.169.254", # AWS/GCP metadata service
        ".env.canary",      # Honeytoken exfiltration
        "CANARY_API_KEY",
        ":(){ :|:& };:",    # Fork bomb
        "/etc/shadow",
        "chmod 777 /"
    ]

    @classmethod
    def inspect(cls, command: str) -> str:
        cmd_lower = command.lower()
        for pattern in cls.DISALLOWED_PATTERNS:
            if pattern.lower() in cmd_lower:
                return "block"
        return "allow"

class AgentOrchestrator:
    """
    Agent loop executing real computer work inside isolated Celesto sandboxes.
    Guarantees clean microVM lifecycle, audited tool dispatch, and deterministic recovery.
    """
    def __init__(self, sandbox_name: str, network_isolated: bool = False):
        self.sandbox_name = sandbox_name
        self.network_settings = {"mode": "off"} if network_isolated else {"mode": "on"}
        self.sandbox = CelestoSandbox(
            sandbox_name=self.sandbox_name,
            internet_settings=self.network_settings
        )
        self.log_file = "logs/commands.jsonl"
        os.makedirs("logs", exist_ok=True)
        self._register_signal_handlers()

    def _register_signal_handlers(self):
        def _handle_interrupt(signum, frame):
            logger.warning(f"Process interrupted (signal={signum}). Cleaning up sandbox {self.sandbox_name}")
            self.sandbox.delete()
            exit(1)

        try:
            signal.signal(signal.SIGINT, _handle_interrupt)
            signal.signal(signal.SIGTERM, _handle_interrupt)
        except (ValueError, AttributeError):
            pass

    def record_command_audit(self, command: str, decision: str):
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "sandbox_name": self.sandbox_name,
            "command": command,
            "decision": decision,
            "execution_target": "celesto_sandbox"
        }
        with open(self.log_file, "a") as f:
            f.write(json.dumps(entry) + "\n")

    def execute_tool(self, command: str) -> CommandResult:
        """
        Safety-audited tool execution.
        Evaluates command with safety hooks, records to audit log, and dispatches to Celesto sandbox.
        """
        decision = SafetyHookManager.inspect(command)
        self.record_command_audit(command, decision)

        if decision == "block":
            logger.error(f"SafetyHook blocked unauthorized command in {self.sandbox_name}: {command}")
            raise CommandBlockedError(f"Command blocked by safety hook: '{command}'")

        # Dispatched strictly to the Celesto microVM
        return self.sandbox.run(command)

    def run_workflow_with_rollback(self) -> Dict[str, Any]:
        """
        Executes a 10-step reproduction workflow.
        Demonstrates checkpointing, step 7 failure, and snapshot rollback recovery.
        """
        try:
            self.sandbox.start()

            # Steps 1 to 4: Preparation
            self.execute_tool("uname -a")
            self.execute_tool("git clone https://github.com/mock/repo.git /workspace/repo")
            self.execute_tool("pip install -r /workspace/repo/requirements.txt")

            # Step 5: Checkpoint before risky execution
            self.sandbox.snapshot("snap-clean-step5", resume_source=True)

            # Step 6: Generate synthetic test
            # Step 7: Risky reproduction attempt (Simulated MidTaskFailure)
            step_7_failed = True
            if step_7_failed:
                # Apply rollback policy
                self.sandbox.restore_snapshot("snap-clean-step5")

            # Steps 8 to 10: Complete with sanitized harness
            res = self.execute_tool("pytest /workspace/repo/tests/test_repro.py")
            return {"status": "succeeded", "proof": res.stdout}
        finally:
            self.sandbox.delete()
