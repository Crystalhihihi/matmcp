"""Fast pre-flight gate before any expensive run: compile all modules + import."""
import py_compile

for f in ["src/matmcp/config.py", "src/matmcp/engines.py", "src/matmcp/workflows.py",
          "src/matmcp/verify.py", "src/matmcp/server.py", "src/matmcp/report.py"]:
    py_compile.compile(f, doraise=True)

from matmcp import engines, report, server, verify, workflows  # noqa: F401

print("PREFLIGHT_OK")
