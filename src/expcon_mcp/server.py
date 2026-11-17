"""Official MCP SDK transports for the explicit-workspace controller."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from expcon import __version__
from mcp.server.transport_security import TransportSecuritySettings

from expcon.service.controller import ExperimentService, page
from expcon.bundle.bundle import BundleVerifier
from expcon.contract.operations import diff_experiment


def create_server(workspace_root: str, port: int = 7680) -> FastMCP:
    service = ExperimentService(workspace_root)
    mcp = FastMCP(
        "expcon",
        host="127.0.0.1",
        port=port,
        json_response=True,
        stateless_http=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=["127.0.0.1:*", "localhost:*", "testserver"],
            allowed_origins=["http://127.0.0.1:*", "http://localhost:*"],
        ),
    )

    @mcp.tool()
    def expcon_doctor() -> dict[str, Any]:
        """Discover installed capability; this is a trusted-host controller."""
        from expcon.backends.kaggle import KaggleApiTransport, KaggleCliTransport

        return {
            "version": __version__,
            "trust_model": "trusted-host",
            "workspace": str(service.root),
            "kaggle": {
                "api": KaggleApiTransport().capabilities(),
                "cli": KaggleCliTransport().capabilities(),
            },
        }

    @mcp.tool()
    def experiment_list(offset: int = 0, limit: int = 50) -> dict[str, Any]:
        """List editable and retained experiment references."""
        return page(
            [
                str(p.parent.relative_to(service.root))
                for p in sorted(
                    (service.root / "experiments").glob("*/EXPERIMENT.yaml")
                )
            ],
            offset,
            limit,
        )

    @mcp.tool()
    def experiment_init(experiment: str, contract: dict) -> dict[str, Any]:
        """Create a new v3 editable draft; never replace an existing version."""
        return service.init(experiment, contract)

    @mcp.tool()
    def experiment_inspect(experiment: str) -> dict[str, Any]:
        """Read contract and authoritative lifecycle and frozen identity."""
        return service.inspect(experiment)

    @mcp.tool()
    def experiment_validate(experiment: str) -> dict[str, Any]:
        """Validate the experiment structurally without executing science."""
        return service.validate(experiment)

    @mcp.tool()
    def experiment_preflight(
        experiment: str, inputs: dict[str, str] | None = None
    ) -> dict[str, Any]:
        """Compute the candidate identity to review before explicit freeze."""
        return service.preflight(experiment, inputs)

    @mcp.tool()
    def experiment_freeze(
        experiment: str, expected_candidate_id: str
    ) -> dict[str, Any]:
        """Freeze the reviewed candidate; edits require another preflight."""
        return service.freeze(experiment, expected_candidate_id)

    @mcp.tool()
    def experiment_submit(
        draft_directory: str, expected_candidate_id: str | None = None
    ) -> dict[str, Any]:
        """Deprecated admission-only import and freeze. Does not execute a run."""
        return service.import_draft(draft_directory, expected_candidate_id)

    @mcp.tool()
    def experiment_diff(experiment: str) -> dict[str, Any]:
        """Detect drift from retained frozen identity."""
        service.validate(experiment)
        return diff_experiment(service.experiment(experiment))

    @mcp.tool()
    def experiment_bundle(experiment: str) -> dict[str, Any]:
        """Materialize and verify a clean frozen experiment bundle."""
        return service.bundle(experiment)

    @mcp.tool()
    def bundle_verify(bundle: str, expected_bundle_id: str) -> dict[str, Any]:
        """Verify bundle bytes against an independently retained identity."""
        return BundleVerifier(service.path(bundle), expected_bundle_id).verify()

    @mcp.tool()
    def experiment_run(
        experiment: str,
        idempotency_key: str,
        backend: str = "local",
        kernel: str | None = None,
        inputs: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Explicitly execute a frozen bundle. Returns a durable run ID promptly."""
        return service.run(experiment, idempotency_key, backend, kernel, inputs)

    @mcp.tool()
    def experiment_status(run_id: str) -> dict[str, Any]:
        """Reconcile persisted execution with backend observation."""
        return service.status(run_id)

    @mcp.tool()
    def experiment_events(
        run_id: str, offset: int = 0, limit: int = 50
    ) -> dict[str, Any]:
        """Read a bounded page from the durable event ledger."""
        return page(service.lifecycle.get_run_events(run_id), offset, limit)

    @mcp.tool()
    def experiment_fetch(run_id: str) -> dict[str, Any]:
        """Collect immutable evidence from an observed completed run."""
        return service.fetch(run_id)

    @mcp.tool()
    def experiment_verify(run_id: str) -> dict[str, Any]:
        """Verify evidence against retained run, bundle, and seals."""
        return service.verify(run_id)

    @mcp.tool()
    def experiment_adjudicate(run_id: str) -> dict[str, Any]:
        """Evaluate independent execution, contract, evidence, and scientific statuses."""
        return service.adjudicate(run_id)

    @mcp.tool()
    def experiment_result(run_id: str) -> dict[str, Any]:
        """Read selected verification and adjudication; never runs lifecycle steps."""
        return service.result(run_id)

    @mcp.tool()
    def experiment_artifacts(
        run_id: str, offset: int = 0, limit: int = 50
    ) -> dict[str, Any]:
        """List registered artifacts and provenance."""
        return service.artifacts(run_id, offset, limit)

    @mcp.tool()
    def artifact_read(
        run_id: str, artifact_id: str, offset: int = 0, limit: int = 8192
    ) -> dict[str, Any]:
        """Read a bounded range of a checksum-verified registered artifact."""
        return service.artifact_read(run_id, artifact_id, offset, limit)

    @mcp.tool()
    def research_history(offset: int = 0, limit: int = 50) -> dict[str, Any]:
        """Recover proposals, runs, and decisions from persistent state."""
        return service.history(offset, limit)

    @mcp.tool()
    def research_propose(
        hypothesis: str, details: dict | None = None
    ) -> dict[str, Any]:
        """Append a research proposal; a proposal does not authorize execution."""
        if not hypothesis.strip():
            raise ValueError("HYPOTHESIS_REQUIRED")
        return service.record(
            "proposals", {**(details or {}), "hypothesis": hypothesis}
        )

    @mcp.tool()
    def research_record_decision(
        interpretation: str, referenced_runs: list[str], details: dict | None = None
    ) -> dict[str, Any]:
        """Append interpretation with validated run references; never changes verdicts."""
        return service.record(
            "decisions",
            {
                **(details or {}),
                "interpretation": interpretation,
                "referenced_runs": referenced_runs,
            },
        )

    return mcp


def create_app(workspace_root: str | None = None):
    return create_server(
        workspace_root or os.environ.get("EXPCON_WORKSPACE", str(Path.cwd()))
    ).streamable_http_app()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workspace", default=os.environ.get("EXPCON_WORKSPACE", str(Path.cwd()))
    )
    parser.add_argument("--stdio", action="store_true")
    parser.add_argument("--port", type=int, default=7680)
    parser.add_argument(
        "--host", default="127.0.0.1", choices=["127.0.0.1", "localhost"]
    )
    args = parser.parse_args()
    create_server(args.workspace, args.port).run(
        transport="stdio" if args.stdio else "streamable-http"
    )


if __name__ == "__main__":
    main()
