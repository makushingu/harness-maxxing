from .cli import main

raise SystemExit(main())   # the exit code matters: `maxxing update` runs the new code as `python -m maxxing ...`
