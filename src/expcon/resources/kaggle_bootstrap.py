"""Frozen Kaggle executor. Only stdlib is needed for Python stage execution."""

import json
import os
import platform
import subprocess
import sys
from pathlib import Path


def main(bundle, output):
    bundle, output = Path(bundle).resolve(), Path(output).resolve()
    contract = json.loads((bundle / "resolved_contract.json").read_text())
    sys.path.insert(0, str(bundle / "source"))
    import types

    for name in ("expcon", "expcon.runner", "expcon.hashing", "expcon.util"):
        module = types.ModuleType(name)
        module.__path__ = [str(bundle / "source" / name.replace(".", "/"))]
        sys.modules[name] = module
    output.mkdir(parents=True, exist_ok=True)
    import importlib.metadata
    from expcon.runner.environment import (
        _root_dependencies,
        _python_requirement_satisfied,
    )
    import importlib

    tomllib = importlib.import_module(
        "tomllib" if sys.version_info >= (3, 11) else "tomli"
    )

    lock = bundle / "dependency.lock"
    if not lock.is_file():
        raise RuntimeError("DEPENDENCY_LOCK_REQUIRED")
    specification = tomllib.loads(lock.read_text())
    requirement = specification.get("requires-python")
    if requirement and not _python_requirement_satisfied(
        platform.python_version(), requirement
    ):
        raise RuntimeError("REMOTE_PYTHON_MISMATCH")
    for name, version in _root_dependencies(lock).items():
        if importlib.metadata.version(name) != version:
            raise RuntimeError("REMOTE_DEPENDENCY_MISMATCH")
    distributions = {
        d.metadata["Name"].lower().replace("_", "-"): d.version
        for d in importlib.metadata.distributions()
    }
    expected = contract.get("environment", {}).get("distribution_versions")
    if expected is not None and expected != distributions:
        raise RuntimeError("REMOTE_ENVIRONMENT_MISMATCH")
    environment = {
        "installed_distributions": distributions,
        "python": sys.version,
        "platform": platform.platform(),
        "provider": "kaggle",
        "execution_host": True,
    }
    (output / "environment.json").write_text(json.dumps(environment))
    stages = list(contract["execution"]["stages"])
    completed: set[str] = set()
    results = []
    while stages:
        stage = next(
            (s for s in stages if set(s.get("requires", [])) <= completed), None
        )
        if stage is None:
            raise RuntimeError("INVALID_STAGE_GRAPH")
        directory = output / stage["id"]
        directory.mkdir()
        script = bundle / "runner" / stage["entrypoint"]
        spec = stage.get("invocation", contract["execution"].get("invocation"))
        # The controller packages its deterministic invocation implementation.
        from expcon.runner.invocation import resolve_invocation

        bindings = contract["execution"].get("kaggle", {}).get("inputs", {})
        invocation = resolve_invocation(
            spec,
            bundle_root=bundle,
            output_root=directory,
            input_bindings=bindings,
            environment_bindings={},
        )
        if script.suffix == ".ipynb":
            import nbformat  # type: ignore[import-not-found]
            from nbclient import NotebookClient  # type: ignore[import-not-found]

            notebook = nbformat.read(script, as_version=4)
            os.environ.update(invocation.environment)
            os.environ["PYTHONPATH"] = str(bundle / "source")
            os.environ["EXPCON_INVOCATION_JSON"] = json.dumps(invocation.argv)
            os.environ["EXPCON_BUNDLE_ROOT"] = str(bundle)
            os.environ["EXPCON_OUTPUT_ROOT"] = str(directory)
            NotebookClient(
                notebook, timeout=600, resources={"metadata": {"path": str(directory)}}
            ).execute()
            nbformat.write(notebook, directory / "executed.ipynb")
            success = True
        else:
            process = subprocess.run(
                [sys.executable, str(script), *invocation.argv],
                cwd=bundle,
                env={
                    **os.environ,
                    **invocation.environment,
                    "PYTHONPATH": str(bundle / "source"),
                },
                capture_output=True,
                text=True,
            )
            (directory / "stdout.log").write_text(process.stdout)
            (directory / "stderr.log").write_text(process.stderr)
            success = process.returncode == 0
        results.append({"stage_id": stage["id"], "success": success})
        (output / "results.json").write_text(
            json.dumps(
                {"success": all(r["success"] for r in results), "stages": results}
            )
        )
        if not success:
            raise RuntimeError("STAGE_FAILED")
        completed.add(stage["id"])
        stages.remove(stage)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
