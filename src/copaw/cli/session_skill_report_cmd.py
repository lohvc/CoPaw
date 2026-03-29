# -*- coding: utf-8 -*-
from __future__ import annotations

import click

from ..app.session_skill_report import main


@click.command(
    "session-skill-report",
    context_settings={
        "ignore_unknown_options": True,
        "allow_extra_args": True,
    },
)
@click.pass_context
def session_skill_report_cmd(ctx: click.Context) -> None:
    """Upload CoPaw session dialogs with a cross-platform CLI wrapper."""
    ctx.exit(main(list(ctx.args)))
