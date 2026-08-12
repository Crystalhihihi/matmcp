"""MCP smoke test: exercise the real stdio MCP path (no DFT heavy lifting).

Run inside WSL matmcp env:  python tools/test_mcp_smoke.py [run_id]
"""
import asyncio
import sys

from fastmcp import Client
from fastmcp.client.transports import StdioTransport

CMD = ("source ~/miniforge3/etc/profile.d/conda.sh && conda activate matmcp && "
       "cd /mnt/d/材料mcp大串烧 && exec python -m matmcp.server")


async def main() -> None:
    transport = StdioTransport(command="bash", args=["-lc", CMD])
    async with Client(transport) as client:
        tools = await client.list_tools()
        print("TOOLS:", sorted(t.name for t in tools))

        r = await client.call_tool("fetch_structure",
                                   {"query": "MoS2", "use_builtin": True})
        data = r.data
        print("FETCH ok:", data.get("ok"), "| run_id:", data.get("run_id"))
        assert data["ok"], data

        run_id = sys.argv[1] if len(sys.argv) > 1 else data["run_id"]
        r = await client.call_tool("get_run_artifacts", {"run_id": run_id})
        arts = r.data.get("artifacts", [])
        print(f"ARTIFACTS of {run_id}: {len(arts)} files")
        for a in arts:
            print("  ", a["path"], a["bytes"], "B")
    print("MCP_SMOKE_DONE")


asyncio.run(main())
