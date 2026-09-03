"""Tests for canonicalisation and hashing."""


import yaml

from expcon.hashing.canonical import canonical_json
from expcon.hashing.digest import sha256_text, sha256_hex, file_sha256
from expcon.hashing.manifest import compute_directory_manifest, verify_directory_manifest, manifest_hash


class TestCanonicalisation:
    """Test deterministic canonical JSON."""

    def test_same_dict_same_hash(self):
        d1 = {"b": 2, "a": 1}
        d2 = {"a": 1, "b": 2}
        assert canonical_json(d1) == canonical_json(d2)

    def test_nested_same_hash(self):
        d1 = {"outer": {"z": 3, "a": 1}, "list": [1, 2, 3]}
        d2 = {"list": [1, 2, 3], "outer": {"a": 1, "z": 3}}
        assert canonical_json(d1) == canonical_json(d2)

    def test_yaml_formatting_invariance(self):
        """Equivalent YAML formatting produces identical hash."""
        yaml1 = """
        experiment:
          id: E13
          version: v001
        hypothesis:
          statement: test
        """
        yaml2 = """
        hypothesis:
          statement: test
        experiment:
          version: v001
          id: E13
        """
        d1 = yaml.safe_load(yaml1)
        d2 = yaml.safe_load(yaml2)
        h1 = sha256_hex(d1)
        h2 = sha256_hex(d2)
        assert h1 == h2

    def test_yaml_with_comments_invariance(self):
        """Comments and whitespace don't affect hash."""
        yaml1 = """
        # This is a comment
        experiment:
          id: E13    # inline comment

          version: v001
        """
        yaml2 = """
        experiment:
          id: E13
          version: v001
        """
        d1 = yaml.safe_load(yaml1)
        d2 = yaml.safe_load(yaml2)
        assert sha256_hex(d1) == sha256_hex(d2)

    def test_bool_not_int(self):
        """bool should not be treated as int."""
        assert sha256_hex({"x": True}) != sha256_hex({"x": 1})

    def test_bytes_converted_to_str(self):
        """Bytes should be converted to UTF-8 strings."""
        d1 = {"x": b"hello"}
        d2 = {"x": "hello"}
        assert canonical_json(d1) == canonical_json(d2)


class TestDigest:
    """Test SHA-256 digest functions."""

    def test_sha256_text(self):
        assert sha256_text("hello") == sha256_text("hello")
        assert sha256_text("hello") != sha256_text("world")

    def test_sha256_hex(self):
        obj = {"a": 1, "b": 2}
        assert sha256_hex(obj) == sha256_hex({"b": 2, "a": 1})

    def test_file_sha256(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello world")
        assert file_sha256(f) == file_sha256(f)
        assert len(file_sha256(f)) == 64

    def test_file_sha256_changes_with_content(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello")
        h1 = file_sha256(f)
        f.write_text("world")
        h2 = file_sha256(f)
        assert h1 != h2


class TestManifest:
    """Test directory manifest computation and verification."""

    def test_compute_manifest(self, tmp_path):
        (tmp_path / "a.txt").write_text("hello")
        (tmp_path / "b.txt").write_text("world")
        manifest = compute_directory_manifest(tmp_path)
        assert len(manifest.entries) == 2
        paths = [e.relative_path for e in manifest.entries]
        assert "a.txt" in paths
        assert "b.txt" in paths

    def test_manifest_hash_stability(self, tmp_path):
        (tmp_path / "a.txt").write_text("hello")
        m1 = compute_directory_manifest(tmp_path)
        m2 = compute_directory_manifest(tmp_path)
        assert manifest_hash(m1) == manifest_hash(m2)

    def test_verify_manifest_pass(self, tmp_path):
        (tmp_path / "a.txt").write_text("hello")
        manifest = compute_directory_manifest(tmp_path)
        result = verify_directory_manifest(tmp_path, manifest)
        assert result["status"] == "PASS"

    def test_verify_manifest_tamper(self, tmp_path):
        (tmp_path / "a.txt").write_text("hello")
        manifest = compute_directory_manifest(tmp_path)
        (tmp_path / "a.txt").write_text("tampered")
        result = verify_directory_manifest(tmp_path, manifest)
        assert result["status"] == "FAIL"
        assert any("HASH_MISMATCH" in m["reason"] or "SIZE_MISMATCH" in m["reason"] for m in result["mismatches"])

    def test_verify_manifest_missing(self, tmp_path):
        (tmp_path / "a.txt").write_text("hello")
        manifest = compute_directory_manifest(tmp_path)
        (tmp_path / "a.txt").unlink()
        result = verify_directory_manifest(tmp_path, manifest)
        assert result["status"] == "FAIL"
        assert any("MISSING" in m["reason"] for m in result["mismatches"])
