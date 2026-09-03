"""Expcon CLI - machine-readable and human-readable output."""

import sys

import click

from expcon.cli.commands import (
    init_cmd,
    inspect_cmd,
    validate_cmd,
    freeze_cmd,
    diff_cmd,
    bundle_cmd,
    preflight_cmd,
    verify_bundle_cmd,
    run_cmd,
    ps_cmd,
    status_cmd,
    events_cmd,
    fetch_cmd,
    verify_cmd,
    adjudicate_cmd,
    artifacts_cmd,
    workspace_cmd,
    attach_cmd,
    doctor_cmd,
    skill_cmd,
    colab_cmd,
    kaggle_cmd,
    tinker_cmd,
)


@click.group()
@click.version_option(version="0.1.0", prog_name="expcon")
@click.pass_context
def main(ctx: click.Context) -> None:
    """Expcon - Experiment Control System for AI-assisted ML research.

    Governs experiment identity, lifecycle, artifact provenance,
    execution evidence, and scientific validity.
    """
    ctx.ensure_object(dict)


# Register all commands
main.add_command(init_cmd)
main.add_command(inspect_cmd)
main.add_command(validate_cmd)
main.add_command(freeze_cmd)
main.add_command(diff_cmd)
main.add_command(bundle_cmd)
main.add_command(preflight_cmd)
main.add_command(verify_bundle_cmd)
main.add_command(run_cmd)
main.add_command(ps_cmd)
main.add_command(status_cmd)
main.add_command(events_cmd)
main.add_command(fetch_cmd)
main.add_command(verify_cmd)
main.add_command(adjudicate_cmd)
main.add_command(artifacts_cmd)
main.add_command(workspace_cmd)
main.add_command(attach_cmd)
main.add_command(doctor_cmd)
main.add_command(skill_cmd)
main.add_command(colab_cmd)
main.add_command(kaggle_cmd)
main.add_command(tinker_cmd)


if __name__ == "__main__":
    sys.exit(main())
