from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from langchain_core.messages import HumanMessage
from graph import create_triage_graph
from utils import display_triage_steps

app = FastAPI(title="GOC Toolkit AI Service")

class TriageRequest(BaseModel):
    incident_number: str

class TriageResponse(BaseModel):
    incident_number: str
    triage_report: str

@app.post("/api/v1/triage", response_model=TriageResponse)
async def run_triage(payload: TriageRequest):
    try:
        graph, mcp_client = await create_triage_graph()
        
        inputs = {
            "messages": [
                HumanMessage(
                    content=f"Analyze operational metrics data and triage ticket {payload.incident_number}"
                ),
            ],
            "triage_report": ""
        }
        
        config = {"configurable": {"thread_id": payload.incident_number}}
        
        final_state = await graph.ainvoke(inputs, config)
        
        display_triage_steps(final_state)
        
        report_content = final_state.get(
            "triage_report",
            "Unable to compile summary response validation analysis"
        )
        
        return TriageResponse(
            incident_number=payload.incident_number,
            triage_report=str(report_content)
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Internal agent state machine failure: {str(e)}"
        )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)