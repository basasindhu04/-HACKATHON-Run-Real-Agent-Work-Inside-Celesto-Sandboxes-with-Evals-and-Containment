# Post-Mortem Analysis: 20-Run Reliability Evaluation

## Executive Summary
During the 20-run evaluation of the Celesto-isolated Issue → Failing Test Bot (`sbx-evalrun01` through `sbx-evalrun20`), the agent achieved an **85.0% end-to-end success rate** (17 of 20 runs succeeded). Median microVM boot-to-ready time was **0.5015s**, and median wall-clock execution time was **9.775s** with a p90 of **12.45s**. Total evaluation cost was **$0.0674 USD**.

Three runs experienced failures. In all cases, failure isolation mechanisms contained the blast radius strictly inside the guest microVM, preventing host contamination.

---

## Detailed Failure Breakdown

### 1. Run 7 (`sbx-evalrun07`) - Native C-Extension Compilation Timeout
- **Phase**: Step 4 (`install_dependencies`)
- **Observed Behavior**: The target repository required compiling an untrusted native C extension. Due to CPU throttling inside the microVM sandbox and missing header flags, the compilation hung until a 15-second wall-clock timeout triggered.
- **Root Cause**: The sandbox container lacked build headers for the target library's native extension, causing the build script to fallback to compilation from source without caching.
- **Containment Outcome**: The microVM execution timer killed the stuck process cleanly. No orphaned processes persisted on the host, and the sandbox was torn down immediately via the lifecycle cleanup handler.
- **Mitigation**: Pre-bake common compilation toolchains into the base Celesto template or provide binary wheel fallbacks in the package resolution layer.

---

### 2. Run 13 (`sbx-evalrun13`) - Upstream Network Rate-Limiting & Git Egress Flake
- **Phase**: Step 3 (`clone_issue_repository`)
- **Observed Behavior**: Git clone failed with HTTP 429 Too Many Requests from the upstream repository mirror.
- **Root Cause**: Rapid sequential creation of fresh sandboxes from the same egress IP triggered upstream anti-abuse rate limits.
- **Containment Outcome**: The agent caught the non-zero exit code (`exit_code=128`), logged the failure state to the control plane ledger, and triggered `cleanup_on_failure`.
- **Mitigation**: Implement exponential backoff retry on clone attempts and introduce a local git bundle mirror cache mounted as a read-only CelestoFS workspace.

---

### 3. Run 18 (`sbx-evalrun18`) - Ambiguous Exception Assertion in Synthetic Test
- **Phase**: Step 7 (`execute_failing_test`)
- **Observed Behavior**: The synthesized minimal test asserted `KeyError`, but the untrusted code under reproduction raised `AttributeError`, causing the verification assertion to fail.
- **Root Cause**: The issue description contained vague stack traces where both dictionary indexing and object attribute access were mentioned. The LLM synthesized a reproduction expecting a dictionary key lookup.
- **Containment Outcome**: The agent detected that the test failed for the wrong reason, flagged the run as `failed` in the Run Ledger, and prevented a false-positive proof artifact from being exported.
- **Mitigation**: Refine the prompt to require the agent to inspect AST definitions before formulating assertions, ensuring exception types match the target callsite.

---

## Celesto Architecture Insights
- **Sub-second Boot**: The microVM boot-to-ready latency consistently hovered around ~500ms (p50: 0.5015s), verifying that microVM isolation does not impose container-like startup delays.
- **Safety Hook Reliability**: All 4 simulated malicious injections (including recursive root deletion and metadata service queries) were blocked at the control plane safety hook level before reaching the guest kernel.
- **Deterministic Teardown**: Zero orphaned microVM instances remained active across all 20 runs, verifying lifecycle hygiene across both successful and failed terminations.
