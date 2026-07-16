Python
import os
import httpx
from mcp.server.fastmcp import FastMCP

# Initialize your FastMCP server
mcp = FastMCP("Servicenow operational Intelligence Extension")

# Retrieve credentials safely
SNOW_INSTANCE = os.getenv("SNOW_INSTANCE")
SNOW_USERNAME = os.getenv("SNOW_USERNAME")
SNOW_PASSWORD = os.getenv("SNOW_PASSWORD")

@mcp.tool()
async def get_incident_details(incident_number: str) -> str:
    """
    Queries the live ServiceNow Table API to retrieve core details 
    for a specific incident ticket number.
    """
    # 1. Construct the ServiceNow Table API URL
    # We query by 'number' and limit fields using 'sysparm_fields' to save bandwidth
    url = f"https://{SNOW_INSTANCE}.service-now.com/api/now/table/incident"
    
    params = {
        "sysparm_query": f"number={incident_number}",
        "sysparm_limit": "1",
        # Request ONLY the fields your agent needs to see:
        "sysparm_fields": "number,short_description,severity,state,assignment_group,description,priority"
    }
    
    # 2. Trigger the live API call
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                url,
                params=params,
                auth=(SNOW_USERNAME, SNOW_PASSWORD),
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json"
                },
                timeout=10.0
            )
            response.raise_for_status()
            data = response.json()
            
        except httpx.HTTPStatusError as e:
            return f"Error connecting to ServiceNow: HTTP {e.response.status_code}"
        except Exception as e:
            return f"Network error contacting ServiceNow: {str(e)}"

    # 3. Handle 'Ticket Not Found' cases gracefully
    results = data.get("result", [])
    if not results:
        return f"Error: No ServiceNow incident ticket found matching '{incident_number}'."

    raw_ticket = results[0]

    # 4. Extract and format the output
    # ServiceNow returns relational fields like 'assignment_group' as an object containing a link and a display_value.
    # We resolve those to keep our schema clean.
    assignment_group_data = raw_ticket.get("assignment_group")
    assignment_group_name = (
        assignment_group_data.get("display_value") 
        if isinstance(assignment_group_data, dict) 
        else assignment_group_data or "Unassigned"
    )

    # 5. Build a lean, clean dictionary
    clean_output = {
        "number": raw_ticket.get("number"),
        "short_description": raw_ticket.get("short_description"),
        "priority": raw_ticket.get("priority"),
        "severity": raw_ticket.get("severity"),
        "state": raw_ticket.get("state"),
        "assignment_group": assignment_group_name,
        "description": raw_ticket.get("description")
    }

    # 6. Format as structured JSON output to return to the LLM
    import json
    return json.dumps(clean_output, indent=2)