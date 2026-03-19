"""ClusterPilot entry point.

Usage
-----
    clusterpilot                    # launch TUI
    clusterpilot init               # create starter ~/.config/clusterpilot/config.toml
    clusterpilot daemon run         # run poll daemon in foreground (no TUI)
    clusterpilot daemon install     # install systemd user service
"""
from __future__ import annotations

import argparse
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="clusterpilot",
        description="AI-assisted HPC workflow manager",
    )
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("init", help="Create starter config at ~/.config/clusterpilot/config.toml")

    daemon_p = sub.add_parser("daemon", help="Daemon management")
    daemon_sub = daemon_p.add_subparsers(dest="daemon_cmd")
    daemon_sub.add_parser("run", help="Run poll daemon in foreground")
    daemon_sub.add_parser("install", help="Install systemd user service unit")

    args = parser.parse_args()

    if args.cmd == "init":
        _cmd_init()
    elif args.cmd == "daemon":
        if args.daemon_cmd == "run":
            _cmd_daemon_run()
        elif args.daemon_cmd == "install":
            _cmd_daemon_install()
        else:
            daemon_p.print_help()
    else:
        _cmd_tui()


# ── Subcommands ───────────────────────────────────────────────────────────────

def _cmd_init() -> None:
    from clusterpilot.config import CONFIG_PATH, write_default_config
    if CONFIG_PATH.exists():
        print(f"Config already exists: {CONFIG_PATH}")
        return
    write_default_config()
    print(f"Config written to {CONFIG_PATH}")
    print("Edit it to set your cluster username and account, then run: clusterpilot")


def _cmd_daemon_run() -> None:
    import asyncio
    import aiosqlite
    from clusterpilot.config import ConfigError, load_config
    from clusterpilot.db import DB_PATH, init_db
    from clusterpilot.jobs.daemon import PollDaemon

    try:
        config = load_config()
    except ConfigError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    async def _run() -> None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(DB_PATH) as db:
            await init_db(db)
        daemon = PollDaemon(config, DB_PATH)
        await daemon.run_forever()

    print("ClusterPilot daemon running. Press Ctrl-C to stop.")
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        print("\nDaemon stopped.")


def _cmd_daemon_install() -> None:
    from clusterpilot.jobs.daemon import write_service_file
    path = write_service_file()
    print(f"Service file written to: {path}")
    print()
    print("Enable and start with:")
    print("  systemctl --user daemon-reload")
    print("  systemctl --user enable --now clusterpilot-poll.service")


def _cmd_tui() -> None:
    import logging
    from clusterpilot.config import ConfigError, load_config, write_default_config
    from clusterpilot.tui.app import ClusterPilotApp

    logging.basicConfig(
        level=logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    try:
        config = load_config()
    except ConfigError:
        # First run — write default config and guide the user.
        write_default_config()
        from clusterpilot.config import CONFIG_PATH
        print("Welcome to ClusterPilot!")
        print()
        print(f"A starter config has been written to:\n  {CONFIG_PATH}")
        print()
        print("Edit it to add your cluster username and account,")
        print("then run 'clusterpilot' again.")
        sys.exit(0)

    if not config.clusters:
        print("No clusters defined in config. Edit ~/.config/clusterpilot/config.toml.")
        sys.exit(1)

    if not config.api_key and config.provider != "ollama":
        env_var = "OPENAI_API_KEY" if config.provider == "openai" else "ANTHROPIC_API_KEY"
        print(
            f"Warning: no API key configured. "
            "Script generation will fail.\n"
            f"Set api_key in config.toml or export {env_var}."
        )

    from clusterpilot.db import DB_PATH
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    app = ClusterPilotApp(config)
    app.run()


if __name__ == "__main__":
    main()
