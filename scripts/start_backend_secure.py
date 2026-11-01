"""Interactive local backend startup; hidden password, process environment only.
No credentials on command line, disk, or logs; no Neo4j data/schema operations.
"""
import getpass
import logging
import os
from pathlib import Path
import sys
import warnings

ROOT = Path(__file__).resolve().parents[1]
URI = os.getenv("NEO4J_URI") or "bolt://127.0.0.1:17687"
USER = os.getenv("NEO4J_USER") or "neo4j"
DATABASE = os.getenv("NEO4J_DATABASE") or "neo4j"


def ensure_backend_port_free():
    # Never kill processes. The user stops their own backend in its terminal.
    import socket
    with socket.socket() as probe:
        probe.settimeout(2)
        if probe.connect_ex(('127.0.0.1',8003)) == 0:
            raise RuntimeError('BACKEND_PORT_BUSY_STOP_OWN_TERMINAL')
    print('BACKEND_PORT_FREE')


def main():
    if len(sys.argv) != 1 or not all(s.isatty() for s in (sys.stdin, sys.stdout, sys.stderr)):
        print("Ordinary interactive PowerShell required; no arguments, pipes or transcript.")
        return 2
    import neo4j
    if not (5, 26) <= tuple(int(x) for x in neo4j.__version__.split(".")[:2]) < (6, 0):
        print("DRIVER_VERSION_MISMATCH; nothing stopped.")
        return 2
    logging.getLogger("neo4j").disabled = True
    print("Target: configured Neo4j endpoint (values not logged); backend: 127.0.0.1:8003")
    print("Plan: verify authentication, require free backend port 8003, then serve on 127.0.0.1:8003.")
    print("No restart of Neo4j/frontend, import, password change or configuration-file write.")
    password = None
    stage = 'hidden_input'
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            password = getpass.getpass("Neo4j password (hidden; no retry): ")
        if not password:
            print("EMPTY_PASSWORD; nothing stopped.")
            return 1
        # Authenticate without stopping any process; no Cypher submitted.
        stage = 'verify_connectivity'
        with neo4j.GraphDatabase.driver(URI, auth=(USER, password), connection_timeout=5,
                    connection_acquisition_timeout=5, max_transaction_retry_time=0,
                    max_connection_pool_size=1, telemetry_disabled=True) as driver:
            driver.verify_connectivity()
        print("CONNECTIVITY_VERIFIED; verification driver closed.")
        stage = 'check_backend_port'
        ensure_backend_port_free()
        # These exact names are consumed by the unmodified get_graph_service().
        # The secret is ephemeral process state, never a file/command argument.
        stage = 'configure_environment'
        os.environ.update(NEO4J_URI=URI, NEO4J_USER=USER, NEO4J_DATABASE=DATABASE,
                          NEO4J_PASSWORD=password, VISION_ENABLED="false",
                          LANGSMITH_TRACING="false", DEEPSEEK_API_KEY="")
        password = None
        print("Neo4j configuration nonempty: " + str({name: bool(os.getenv(name)) for name in
              ("NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD", "NEO4J_DATABASE")}))
        os.chdir(ROOT)
        sys.path.insert(0, str(ROOT))
        sys.dont_write_bytecode = True
        stage = 'import_application'
        import uvicorn
        # Use the original app and original configuration dependency, no override.
        from src.api.main import app
        stage = 'serve'
        print('BACKEND_PID=' + str(os.getpid()) + '; reload=False; same-process environment')
        uvicorn.run(app, host="127.0.0.1", port=8003, reload=False, log_level="info")
        return 0
    except (KeyboardInterrupt, EOFError):
        print("CANCELLED; no automatic retry.")
        return 130
    except (Exception, SystemExit) as error:
        # Do not expose raw driver/authentication exceptions or local variables.
        reason = 'BACKEND_PORT_BUSY_STOP_OWN_TERMINAL' if isinstance(error, RuntimeError) and error.args == ('BACKEND_PORT_BUSY_STOP_OWN_TERMINAL',) else 'SEE_STAGE_AND_EXCEPTION_TYPE'
        print('START_FAILED; stage=' + stage + '; type=' + type(error).__name__ + '; reason=' + reason + '; no automatic retry.')
        return 1
    finally:
        password = None
        os.environ.pop("NEO4J_PASSWORD", None)


if __name__ == "__main__":
    try:
        code = main()
    except (Exception, KeyboardInterrupt):
        print("SETUP_FAILED; no sensitive details printed.")
        code = 2
    raise SystemExit(code)
