import hashlib

import pytest

from expcon.runner.invocation import InvocationError, resolve_invocation


def test_declared_file_identity_is_checked_before_execution(tmp_path):
    path = tmp_path / "dataset.json"
    path.write_text('[1,2,3]')
    spec = {"inputs": {"dataset": {"kind": "file", "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}},
            "argv": ["${inputs.dataset.path}"]}
    resolve_invocation(spec, bundle_root=tmp_path, output_root=tmp_path / "out",
                       input_bindings={"dataset": str(path)}, environment_bindings={})
    path.write_text('[4,5,6]')
    with pytest.raises(InvocationError, match="CONTENT_IDENTITY_MISMATCH"):
        resolve_invocation(spec, bundle_root=tmp_path, output_root=tmp_path / "out",
                           input_bindings={"dataset": str(path)}, environment_bindings={})


def test_directory_identity_binds_contents_not_just_index(tmp_path):
    from expcon.runner.inputs import content_identity
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    (dataset / "index.json").write_text('["values.json"]')
    (dataset / "values.json").write_text('[1,2]')
    before = content_identity(dataset)
    spec = {"inputs": {"dataset": {"kind": "directory", "sha256": before["sha256"]}},
            "argv": ["${inputs.dataset.root}"]}
    (dataset / "values.json").write_text('[2,3]')
    with pytest.raises(InvocationError, match="CONTENT_IDENTITY_MISMATCH"):
        resolve_invocation(spec, bundle_root=tmp_path, output_root=tmp_path / "out",
                           input_bindings={"dataset": str(dataset)}, environment_bindings={})


def test_tree_identity_is_independent_of_mount_location(tmp_path):
    from expcon.runner.inputs import content_identity
    import shutil
    first = tmp_path / "first"
    first.mkdir()
    (first / "data.json").write_text('[1,2]')
    shutil.copytree(first, tmp_path / "second")
    assert content_identity(first) == content_identity(tmp_path / "second")


def test_declared_nonsecret_environment_identity_is_enforced(tmp_path):
    value = "read_only"
    spec = {"argv": [], "environment": {"CACHE_MODE": "${environment.CACHE_MODE}"},
            "environment_sha256": {"CACHE_MODE": hashlib.sha256(value.encode()).hexdigest()}}
    with pytest.raises(InvocationError, match="ENVIRONMENT_IDENTITY_MISMATCH"):
        resolve_invocation(spec, bundle_root=tmp_path, output_root=tmp_path / "out",
                           input_bindings={}, environment_bindings={"CACHE_MODE": "write"})
