# -*- coding: utf-8 -*-
from __future__ import annotations

import click

from ..app.session_detailed_log_report import main


@click.command(
    "session-detailed-log-report",
    context_settings={
        "ignore_unknown_options": True,
        "allow_extra_args": True,
    },
)
@click.pass_context
def session_detailed_log_report_cmd(ctx: click.Context) -> None:
    """Upload CoPaw detailed session logs with a cross-platform CLI wrapper."""
    ctx.exit(main(list(ctx.args)))
