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

# Connect to Elastic Cloud Service (ESS)
es_client = AsyncElasticsearch(
    cloud_id=os.getenv("ELASTIC_ESS_CLOUD_ID"),
    api_key=os.getenv("ELASTIC_ESS_API_KEY")
)

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


@mcp.tool()
async def find_similar_closed_resolutions(search_keyword: str, max_results: int = 3) -> str:
    """
    Searches historical ServiceNow records for closed incidents containing the search_keyword
    in their short description to review how they were successfully resolved in the past.
    """
    url = f"https://{SNOW_INSTANCE}.service-now.com/api/now/table/incident"
    
    # ServiceNow query parameters:
    # 1. state=7 means Closed (or state=6 for Resolved depending on your instance configuration)
    # 2. short_descriptionLIKE resolves keyword matching
    encoded_query = f"state=7^short_descriptionLIKE{search_keyword}"
    
    params = {
        "sysparm_query": encoded_query,
        "sysparm_limit": str(max_results),
        # Retrieve only resolution-related information to save tokens
        "sysparm_fields": "number,short_description,close_notes,close_code,closed_at"
    }
    
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": f"Basic {b64_credentials}"  # Reusing your encoded header
    }
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, params=params, headers=headers, timeout=10.0)
            response.raise_for_status()
            data = response.json()
        except Exception as e:
            return f"Error querying historical incidents from ServiceNow: {str(e)}"

    results = data.get("result", [])
    if not results:
        return f"No similar closed historical incidents found matching the keyword '{search_keyword}'."

    # Format the cleaned list array for the LangGraph agent
    cleaned_history = []
    for ticket in results:
        cleaned_history.append({
            "incident_number": ticket.get("number"),
            "short_description": ticket.get("short_description"),
            "closed_at": ticket.get("closed_at"),
            "resolution_type": ticket.get("close_code") or "Not Specified",
            "resolution_notes": ticket.get("close_notes") or "No resolution logs provided."
        })

    import json
    return json.dumps({"historical_resolutions": cleaned_history}, indent=2)


@mcp.tool()
async def get_elastic_ci_logs(ci_name: str, incident_triggered_time: str) -> str:
    """
    Queries Elastic ESS to retrieve actual error logs for a specific 
    Configuration Item (CI) within a 30-minute window surrounding the failure.
    """
    # 1. Compute time window boundaries
    trigger_dt = datetime.fromisoformat(incident_triggered_time.replace('Z', '+00:00'))
    start_window = (trigger_dt - timedelta(minutes=15)).isoformat()
    end_window = (trigger_dt + timedelta(minutes=15)).isoformat()

    # 2. Build the Elasticsearch query DSL
    query = {
        "bool": {
            "must": [
                {"match": {"host.name": ci_name}},
                {"range": {"@timestamp": {"gte": start_window, "lte": end_window}}},
                {"terms": {"log.level": ["error", "critical", "fatal", "ERROR", "CRITICAL"]}}
            ]
        }
    }

    try:
        # 3. Search your logging indices (e.g., logs-*, filebeat-*)
        response = await es_client.search(
            index="logs-*",
            query=query,
            size=10,
            sort=[{"@timestamp": "desc"}]
        )
        
        # 4. Filter and structure the output cleanly for the LLM
        hits = response['hits']['hits']
        extracted_logs = []
        for hit in hits:
            source = hit['_source']
            extracted_logs.append({
                "timestamp": source.get("@timestamp"),
                "level": source.get("log", {}).get("level"),
                "message": source.get("message")
            })

        return json.dumps({
            "ci_target": ci_name,
            "status": "Success",
            "total_errors_found": len(extracted_logs),
            "logs": extracted_logs
        }, indent=2)

    except Exception as e:
        return json.dumps({"status": "Error", "message": f"Failed to query Elastic ESS: {str(e)}"})
    