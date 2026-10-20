from __future__ import annotations

import sys


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--worker":
        if len(sys.argv) != 3:
            raise SystemExit("Uso interno: Folio.exe --worker <directorio>")
        sys.argv = [sys.argv[0], sys.argv[2]]
        from worker import main as run_worker
        return run_worker()
    from server import main as run_server
    run_server()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
