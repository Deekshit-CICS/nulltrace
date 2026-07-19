import os
from pydantic_settings import BaseSettings, SettingsConfigDict
import sys
class Settings(BaseSettings):

    # def __init__(self, provider: str = "Direct_Azure"):
    #     self.provider = provider
        
    # def get_url(self) -> str:
    #     return os.environ.get("XXXXX_API_URL", "https://sfsd-cu5775-genpop-md-rc.ue1.sfn21.sfn01.n...")
        
    # def get_model(self) -> str:
    #     return os.environ.get("XXXXX_MODEL", "azure-openai-chat-gpt52")
        
    # def get_stream_mode(self) -> bool:
    #     return True
        
    # def get_client_id(self) -> str:
    #     clinet_id = ""
    #     return client_id
        
    # def get_client_secret(self) -> str:
    #     client_secret=""
    #     return client_secret
        
    XXXXX_BASE_URL: str = ""
    
    XXXXX_CLIENT_ID: str = ""
    XXXXX_CLIENT_SECRET: str = ""
    
    SERVICENOW_INSTANCE_URL: str = ""
    SERVICENOW_USERNAME: str = ""
    SERVICENOW_PASSWORD: str = ""

    ELASTIC_ESS_CLOUD_ID="My_Deployment:dXMtY2VudHJhbDEuZ2NwLmNsb3VkLmVsYXN0aWMuY28..."
    ELASTIC_ESS_API_KEY="VzF4M2JKMEJk...=="
    
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

settings = Settings()

PYTHON_EXECUTABLE = sys.executable
SERVER_SCRIPT_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "mcp_server", "server.py"))
print(f"SERVER_SCRIPT_PATH -> {SERVER_SCRIPT_PATH}")