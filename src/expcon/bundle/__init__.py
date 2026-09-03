"""Bundle creation and verification.

A bundle is a content-addressed package containing everything needed to
execute an experiment: the resolved contract, source manifest, configs,
runner code, and a bundle manifest with hashes.
"""

from expcon.bundle.bundle import (
    BundleBuilder,
    BundleVerifier,
    BundleManifest,
    BundleError,
    BundleIdentity,
    BUNDLE_IDENTITY_ALGORITHM_V1,
    BUNDLE_IDENTITY_ALGORITHM_V2,
    bundle_id_for,
    compute_bundle_identity,
    verify_frozen_bundle_compatibility,
    verify_bundle,
    create_bundle,
)

__all__ = [
    "BundleBuilder",
    "BundleVerifier",
    "BundleManifest",
    "BundleError",
    "BundleIdentity",
    "BUNDLE_IDENTITY_ALGORITHM_V1",
    "BUNDLE_IDENTITY_ALGORITHM_V2",
    "bundle_id_for",
    "compute_bundle_identity",
    "verify_frozen_bundle_compatibility",
    "verify_bundle",
    "create_bundle",
]
