import os
from langchain_mcp_adapters.client import MultiServerMCPClient
from config import PYTHON_EXECUTABLE, SERVER_SCRIPT_PATH, settings

async def get_mcp_tools():
    """
    Spawns the local FastMCP server as an explicti backgodun sub-process,
    connecting over stdio pipe transport and translating tools into LangChain objects.
    """

    client = MultiServerMCPClient({
        "custom_servicenow_mcp": {
            "command": PYTHON_EXECUTABLE,
            "args": [SERVER_SCRIPT_PATH],
            "transport": "stdio",
            "env": {
                "SERVICENOW_INSTANCE_URL": settings.SERVICENOW_INSTANCE_URL,
                "SERVICENOW_USERNAME": settings.SERVICENOW_USERNAME,
                "SERVICENOW_PASSWORD": settings.SERVICENOW_PASSWORD,
                "PYTHONPATH": os.path.dirname(SERVER_SCRIPT_PATH),
                "PATH": os.environ.get("PATH", "")
            }
        }
    })

    tools = await client.get_tools()
    return tools, client