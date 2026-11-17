"""Initialize an installed stdio server and invoke its actual diagnostic tool."""

import asyncio
import json
import os
import sys
import tempfile
from importlib.metadata import version
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main():
    with tempfile.TemporaryDirectory(prefix="expcon-installed-mcp-") as workspace:
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        env.pop("PYTHONPATH", None)
        params = StdioServerParameters(
            command=str(Path(sys.executable).parent / "expcon-mcp"),
            args=["--stdio", "--workspace", workspace],
            env=env,
        )
        async with stdio_client(params) as streams:
            async with ClientSession(*streams) as client:
                await client.initialize()
                tools = await client.list_tools()
                assert "experiment_freeze" in {t.name for t in tools.tools}
                result = await client.call_tool("expcon_doctor", {})
                assert not result.isError
                data = result.structuredContent
                assert data["version"] == version("expcon")
                assert data["workspace"] == workspace
                print(
                    json.dumps(
                        {
                            "status": "PASS",
                            "version": data["version"],
                            "transport": "stdio",
                        }
                    )
                )


if __name__ == "__main__":
    asyncio.run(asyncio.wait_for(main(), timeout=30))
