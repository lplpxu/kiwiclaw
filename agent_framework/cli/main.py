"""CLI entry point for Agent Framework"""
import asyncio
import sys
import os
from typing import Optional
import typer
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax

# Fix Windows console encoding for Unicode
if sys.platform == 'win32':
    os.system('chcp 65001 > nul 2>&1')

console = Console(legacy_windows=False)
app = typer.Typer(help="Agent Framework CLI", invoke_without_command=True)


@app.callback()
def main(ctx: typer.Context):
    """Agent Framework - Modular Agent System"""
    pass


@app.command()
def run(
    prompt: str = typer.Argument(..., help="Prompt to send to the agent"),
    model: str = typer.Option("claude-sonnet-4-20250514", "--model", "-m"),
    mode: str = typer.Option("simple", "--mode", help="Agent mode: simple, deep, plan, debug"),
    sandbox: bool = typer.Option(False, "--sandbox", "-s", help="Run in Docker sandbox"),
):
    """Run an agent with a prompt"""
    async def _run():
        from ..core import Agent, AgentConfig, DockerSandbox, SandboxConfig, ToolRegistry

        config = AgentConfig(name="cli-agent", model=model, mode=mode)
        agent = Agent(name="cli-agent", config=config)

        if sandbox:
            sandbox_instance = DockerSandbox(SandboxConfig())
            await sandbox_instance.create()
            console.print("[yellow]Sandbox created[/yellow]")

        result = await agent.think(prompt)
        # Strip non-ASCII characters for Windows console compatibility
        result_clean = result.encode('ascii', 'replace').decode('ascii')
        console.print(Panel(result_clean, title="Agent Response", border_style="green"))

        if sandbox:
            await sandbox_instance.destroy()
            console.print("[yellow]Sandbox destroyed[/yellow]")

    asyncio.run(_run())


@app.command()
def tool_list():
    """List all available tools"""
    from ..core import Agent, AgentConfig

    agent = Agent(name="cli-agent")
    tools = agent._tools

    if not tools:
        console.print("[yellow]No tools available[/yellow]")
        return

    for tool in tools:
        console.print(f"[bold cyan]{tool['name']}[/bold cyan] - {tool.get('description', '')[:50]}")


@app.command()
def sandbox_list():
    """List all sandbox containers"""
    async def _list():
        from ..core import DockerSandbox
        containers = await DockerSandbox.list_containers()
        if not containers:
            console.print("[yellow]No active sandboxes[/yellow]")
            return
        for c in containers:
            console.print(f"[bold]{c['name']}[/bold] - {c['status']}")

    asyncio.run(_list())


@app.command()
def mcp_servers():
    """List all connected MCP servers"""
    console.print("[yellow]MCP server management - coming soon[/yellow]")


@app.command()
def shell():
    """Start interactive REPL"""
    import io
    import sys

    # Force UTF-8 mode on Windows
    if sys.platform == 'win32':
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding='utf-8')

    async def _shell():
        from ..core import Agent, AgentConfig

        print("\n╔══════════════════════════════════════════════════════════╗")
        print("║         Agent Framework REPL                            ║")
        print("║  Type your prompt or 'exit' to quit                     ║")
        print("╚══════════════════════════════════════════════════════════╝\n")

        config = AgentConfig(name="repl-agent")
        agent = Agent(name="repl-agent", config=config)

        while True:
            try:
                user_input = input("\n> ")
                if user_input.lower() in ("exit", "quit", "q"):
                    break
                if not user_input.strip():
                    continue

                result = await agent.think(user_input)
                print("\n" + "─" * 60)
                print(result)
                print("─" * 60)
            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"\nError: {e}")

    asyncio.run(_shell())


if __name__ == "__main__":
    app()