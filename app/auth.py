import httpx
import openai
import time
from threading import Lock
# from llm_config import LLMConfig
import jwt
import datetime
import base64
import requests

client_id = "xxxxx"
client_secret = "xxxxxx"
encoded_client_creds = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("utf-8")

ping_url = "https://authdev.fmacnp.com/pf/JWKS"
jwks_client = jwt.PyJWKClient(ping_url)

_token_cache = {
    "access_token": None,
    "jwt_token": None,
    "expires_at": 0
}
_cache_lock = Lock()

def get_oauth_token():
    url = "https://authdev.xxxxx.com/as/token.oauth2"
    
    payload = 'grant_type=password&username=gocntkit&password=xxxxxxx&validator_id=FHLMCPCV'
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded',
        'Authorization': 'Basic ' + encoded_client_creds,
    }
    
    response = requests.request("POST", url, headers=headers, data=payload, verify=False)
    
    data = response.json()
    return data['access_token']

def get_jwt_token(ping_access_token) -> str:
    signing_key = jwks_client.get_signing_key_from_jwt(ping_access_token)
    
    ping_user = jwt.decode(
        ping_access_token,
        signing_key.key,
        algorithms=["RS256"],
        options={"verify_aud": False}
    )
    print(ping_user)
    
    auth_id = ping_user.get("sub")
    email = ping_user.get("email")
    
    if not auth_id:
        raise ValueError("ping token is missing the sub")
        
    payload = {
        "sub": auth_id,
        "email": email,
        "exp": datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1),
        "iat": datetime.datetime.now(datetime.timezone.utc),
        "iss": "https://authdev.fmacnp.com/"
    }
    
    return jwt.encode(payload, client_secret, algorithm="RS256")

def get_cached_tokens() -> tuple[str, str]:
    global _token_cache
    current_time = time.time()
    
    with _cache_lock:
        if not _token_cache["access_token"] or current_time >= (_token_cache["expires_at"] - 60):
            access_tkn = get_oauth_token()
            jwt_tkn = get_jwt_token(access_tkn)
            
            _token_cache["access_token"] = access_tkn
            _token_cache["jwt_token"] = jwt_tkn
            
        return _token_cache["access_token"], _token_cache["jwt_token"]

class DynamicCorpAuth(httpx.Auth):
    def auth_flow(self, request: httpx.Request):
        access_tkn, jwt_tkn = get_cached_tokens()
        request.headers["Authorization"] = f"Bearer {access_tkn}"
        request.headers["x-jwt-token"] = jwt_tkn
        yield request

class DynamicCorpAsyncAuth(httpx.Auth):
    async def async_auth_flow(self, request: httpx.Request):
        access_tkn, jwt_tkn = get_cached_tokens()
        request.headers["Authorization"] = f"Bearer {access_tkn}"
        request.headers["x-jwt-token"] = jwt_tkn
        yield request

def create_authenticated_openai_and_http_clients():
    """
    Creates an Async HTTP client that dynamically injects fresh tokens on every single request
    made by LangChain
    """
    sync_http_client = httpx.Client(
        headers={"Content-Type": "application/json"},
        auth=DynamicCorpAuth(),
        verify=False
    )
    
    async_http_client = httpx.AsyncClient(
        headers={"Content-Type": "application/json"},
        auth=DynamicCorpAsyncAuth(),
        verify=False
    )
    
    openai_client = openai.OpenAI(
        api_key="dynamic-placeholder",
        base_url="https://api.openai.com/v1", #OpenAI API base URL
        http_client=sync_http_client
    )
    
    return openai_client, sync_http_client, async_http_client