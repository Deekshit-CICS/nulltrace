from langchain_mcp_adapters.client import MultiServerMCPClient
from app.config import settings

async def get_servicenow_tools():
    """
    Connects to the ServiceNow MCP server via stdio transport and 
    fetches the available incident management tools dynamically.
    """
    # Using an official or custom npx/python executable ServiceNow MCP server wrapper.
    # We pass the auth environment variables down to the spawned subprocess.
    client = MultiServerMCPClient({
        "servicenow": {
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-servicenow"],
            "transport": "stdio",
            "env": {
                "SN_INSTANCE_URL": settings.SERVICENOW_INSTANCE_URL,
                "SN_USERNAME": settings.SERVICENOW_USERNAME,
                "SN_PASSWORD": settings.SERVICENOW_PASSWORD,
                "PATH": os.environ.get("PATH", "") # Ensure node execution path passes down
            }
        }
    })
    
    # Discovers and maps MCP tools into native LangChain StructuredTool objects
    tools = await client.get_tools()
    return tools, client