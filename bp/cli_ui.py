"""``bp ui`` — start the web interface.

The CLI is a testing scaffold; this is the product. The command binds to
localhost by default because the server has no authentication and every endpoint
can write to the user's proof graph.
"""

from __future__ import annotations

import threading
import webbrowser
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from .paths import ProjectNotFound, find_project

console = Console()
err_console = Console(stderr=True)


def register(app: typer.Typer) -> None:
    @app.command()
    def ui(
        root: Optional[Path] = typer.Option(None, "--root"),
        host: str = typer.Option("127.0.0.1", "--host"),
        port: int = typer.Option(8000, "--port"),
        replay: bool = typer.Option(
            False, "--replay", help="resolve every model call from the log"
        ),
        open_browser: bool = typer.Option(True, "--open/--no-open"),
        vendor: bool = typer.Option(
            False, "--vendor", help="download Cytoscape and KaTeX for offline use, then serve"
        ),
    ) -> None:
        """Serve the web interface — the intended daily surface."""
        import uvicorn

        from .ui.app import create_app
        from .ui import assets

        try:
            project = find_project(root)
        except ProjectNotFound as exc:
            err_console.print(f"[bold red]error[/] {exc}")
            raise typer.Exit(code=2)

        if vendor:
            console.print("downloading the front-end libraries…")
            try:
                written = assets.download(log=lambda line: console.print(f"[dim]{line}[/]"))
            except RuntimeError as exc:
                err_console.print(f"[bold red]error[/] {exc}")
                raise typer.Exit(code=1)
            console.print(f"vendored {written} file(s) into {assets.vendor_dir()}")

        url = f"http://{host}:{port}/"
        console.print(f"Albatross on [bold]{url}[/]  (project: {project.root})")
        if assets.is_vendored():
            console.print("[dim]front-end libraries served locally; this works offline[/]")
        else:
            console.print(
                "[dim]Cytoscape and KaTeX load from a CDN. `bp ui --vendor` "
                "downloads them for offline use.[/]"
            )
        if replay:
            console.print("[dim]--replay: model calls resolve from the log, never the network[/]")
        if host not in ("127.0.0.1", "localhost", "::1"):
            console.print(
                "[bold yellow]warning[/] binding to a non-local address. There is no "
                "authentication and every endpoint can write to your proof graph."
            )

        if open_browser:
            threading.Timer(1.0, lambda: webbrowser.open(url)).start()

        uvicorn.run(
            create_app(project, replay=replay),
            host=host,
            port=port,
            log_level="warning",
        )
