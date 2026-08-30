"""Optional execution-provider adapters.

Adapters are intentionally not imported here: both Colab and Kaggle implement
the shared runner protocol, so eager imports would form a cycle.
"""
