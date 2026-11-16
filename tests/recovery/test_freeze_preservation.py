import pytest
import yaml

from expcon.contract.operations import ContractOperationError, freeze_experiment
from expcon.lifecycle.experiment_state import ExperimentLifecycle
from expcon.lifecycle.state import ExperimentState


@pytest.mark.parametrize("lost_state", [False, True])
def test_retained_lock_cannot_be_replaced_when_state_changes(research_run, lost_state):
    root, exp, _, _, _ = research_run()
    original = (exp / "contract.lock.json").read_bytes()
    if lost_state:
        (exp / ".expcon_state.json").unlink()
    else:
        ExperimentLifecycle(root).set_experiment_state(exp, ExperimentState.READY)
    contract = yaml.safe_load((exp / "EXPERIMENT.yaml").read_text())
    contract["scientific_parameters"] = {"changed_seed": 123}
    (exp / "EXPERIMENT.yaml").write_text(yaml.safe_dump(contract))
    with pytest.raises(ContractOperationError, match="already frozen"):
        freeze_experiment(exp, root)
    assert (exp / "contract.lock.json").read_bytes() == original


def test_source_include_does_not_walk_unselected_directories(tmp_path, monkeypatch):
    from pathlib import Path
    from expcon.hashing.manifest import compute_directory_manifest
    (tmp_path / "src").mkdir()
    (tmp_path / "src/model.py").write_text("# source\n")
    (tmp_path / "unrelated").mkdir()
    original = Path.rglob
    def checked(path, pattern):
        if path == tmp_path:
            raise RuntimeError("Unrelated tree was traversed")
        return original(path, pattern)
    monkeypatch.setattr(Path, "rglob", checked)
    result = compute_directory_manifest(tmp_path, include=["src/"])
    assert [item.relative_path for item in result.entries] == ["src/model.py"]


def test_pruned_walk_preserves_legacy_directory_symlink_exclusion(tmp_path):
    from expcon.hashing.manifest import compute_directory_manifest
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "model.py").write_text("# outside\n")
    (tmp_path / "src").symlink_to(outside, target_is_directory=True)
    # The old root.rglob walk did not recurse into directory symlinks.
    assert compute_directory_manifest(tmp_path, include=["src/"]).entries == []
