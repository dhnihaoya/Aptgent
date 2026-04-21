import sys

if __name__ == "__main__":
    if len(sys.argv) >= 2:
        subcmd = sys.argv[1]
        if subcmd == "run-job":
            from aptgent.jobs.runner import main
            raise SystemExit(main())
        if subcmd == "doctor":
            from aptgent.cli.doctor import run_doctor
            raise SystemExit(run_doctor())
        print(f"Unknown subcommand: {subcmd}", file=sys.stderr)
        print("Usage: python -m aptgent [doctor | run-job ...]", file=sys.stderr)
        raise SystemExit(1)

    from aptgent.tui.app import run
    run()
