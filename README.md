This Project contains 

app/auth.py 

this module is used for generating oauth token using client id and client secret of ping. 
Then We will use this oauth token to generate jwt token, which intern combinely used to 
create and instance of openai connection. 


app/config.py -> This file contains configurations required for our triage agent

app/db_service.py.  -> this script contains methods used for udpating database tables. Currently there are 3 tables.



app/graph.py -> this is actual langgraph orchestration script.


app/main.py -> This is our fast api script, which executed to enable triage api.


app/mcp_client.py -> This is used for establishing connection with mcp_server and pass required env variables.


app/utils.py -> This is used for formating the output of your traige agent executions.

mcp_server/server.py -> This is used for maintanining tools with respect to our ser