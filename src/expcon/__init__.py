"""Expcon - Experiment Control System for AI-assisted ML research.

Expcon is a deterministic experiment control plane that defines and freezes
scientific experiment identity, governs valid experiment lifecycle transitions,
dispatches execution to replaceable environments, registers generated artifacts,
verifies returned evidence, and separates execution success from scientific
conclusions.
"""

from importlib.metadata import version

__version__ = version("expcon")
__all__ = ["__version__"]
