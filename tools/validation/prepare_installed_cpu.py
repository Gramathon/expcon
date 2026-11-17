"""Prepare the installed wheel's CPU example drafts for the Pi integration test."""

import sys
from expcon.resources.examples.cpu.create_drafts import prepare

if __name__ == "__main__":
    prepare(sys.argv[1])
