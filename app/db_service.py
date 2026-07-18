import uuid
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

# Configure your MS SQL Connection
connection_string = (
    "DRIVER={ODBC Driver 17 for SQL Server};"
    "SERVER=your_server_name;"
    "DATABASE=your_db_name;"
    "UID=your_user;PWD=your_password"
)
connection_url = URL.create("mssql+pyodbc", query={"odbc_connect": connection_string})
engine = create_engine(connection_url)

def save_triage_run(state: dict):
    """
    Takes the final_state from LangGraph and persists it to SQL Server.
    """
    session_id = uuid.uuid4() # Generate ID first to link all tables
    
    with engine.begin() as conn:
        # 1. Insert into triage_sessions
        conn.execute(
            text("""
                INSERT INTO triage_sessions (id, app_id, incident_number, priority) 
                VALUES (:id, :app, :inc, :pri)
            """),
            {"id": session_id, "app": state.get("app_id"), "inc": state.get("incident_number"), "pri": state.get("priority")}
        )
        
        # 2. Insert into triage_metadata
        conn.execute(
            text("""
                INSERT INTO triage_metadata (session_id, short_description, assignment_group) 
                VALUES (:sid, :desc, :group)
            """),
            {"sid": session_id, "desc": state.get("short_description"), "group": state.get("assignment_group")}
        )
        
        # 3. Insert into triage_evidence
        conn.execute(
            text("""
                INSERT INTO triage_evidence (session_id, hostname, asset_details, technical_evidence) 
                VALUES (:sid, :host, :details, :evidence)
            """),
            {
                "sid": session_id, 
                "host": state.get("hostname"), 
                "details": state.get("asset_details"), # JSON string
                "evidence": state.get("technical_evidence")
            }
        )
    return session_id