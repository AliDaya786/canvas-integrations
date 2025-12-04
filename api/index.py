import os
from fastapi import FastAPI, Body, Request
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client

os.environ.setdefault("COMPOSIO_CACHE_DIR", "/tmp/.composio")
from composio import Composio

SLACK_TOOL_VERSION = "20251118_00"
CALENDLY_TOOLKIT_VERSION = "20251111_01"
ATTIO_TOOLKIT_VERSION = "20251202_01"
supabase = create_client(os.environ["SUPABASE_PROJECT_URL"], os.environ["SUPABASE_API_KEY"])


app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_composio() -> Composio:
    return Composio()


@app.get("/")
async def healthcheck():
    return {"status": "ok"}

def get_mcp_server():
    client = get_composio()
    servers = client.mcp.list()["items"]

    for server in servers:
        if server.name == "crm-mcps":
            return server

    return client.mcp.create(
        name="crm-mcps",
        toolkits=[
            {"toolkit": "attio", "auth_config": os.environ["ATTIO_AUTH_CONFIG_ID"]},
            {"toolkit": "hubspot", "auth_config": os.environ["HUBSPOT_AUTH_CONFIG_ID"]},
            {"toolkit": "notion", "auth_config": os.environ["NOTION_AUTH_CONFIG_ID"]}
        ]
    )

@app.get("/app/mcp-info")
async def mcp_info():
    """Optional: View the MCP server URL"""
    server = get_mcp_server()
    return {"mcp_url": server.mcp_url}



@app.get("/api/oauth_start")
async def oauth_start(request: Request):
    client = get_composio()
    user_id = request.query_params.get("user_id")

    backend_base = os.getenv("BACKEND_BASE_URL")
    callback_url = f"{backend_base}/api/oauth_callback?user_id={user_id}"

    connection_request = client.connected_accounts.link(
        user_id=user_id,
        auth_config_id=os.environ["CALENDLY_AUTH_CONFIG_ID"],
        callback_url=callback_url,
    )

    return {"redirect_url": connection_request.redirect_url}

@app.get("/api/oauth_callback")
async def oauth_callback(request: Request):
    from fastapi.responses import RedirectResponse
    user_id = request.query_params.get("user_id")
    client = get_composio()

    user_info = client.tools.execute(
        slug="CALENDLY_GET_USER",
        user_id=user_id,
        version=CALENDLY_TOOLKIT_VERSION,
        arguments={"uuid": "me"},
    )

    resource = user_info["data"]["resource"]
    org_url = resource["current_organization"]
    user_url = resource["uri"]

    target_url = f"{os.environ['BACKEND_BASE_URL'].rstrip('/')}/calendly-webhook?user_id={user_id}"

    client.tools.execute(
        slug="CALENDLY_CREATE_WEBHOOK_SUBSCRIPTION",
        user_id=user_id,
        version=CALENDLY_TOOLKIT_VERSION,
        arguments={
            "url": target_url,
            "events": ["invitee.created"],
            "scope": "user",
            "organization": org_url,
            "user": user_url,
        },
    )

    return RedirectResponse(url=f"https://frontend-three-psi-61.vercel.app?user_id={user_id}")

@app.get("/api/slack_oauth_start")
async def slack_oauth_start(request: Request):
    client = get_composio()
    user_id = request.query_params.get("user_id")

    backend_base = os.getenv("BACKEND_BASE_URL")
    callback_url = f"{backend_base}/api/slack_oauth_callback?user_id={user_id}"

    connection_request = client.connected_accounts.link(
        user_id=user_id,
        auth_config_id=os.environ["SLACK_AUTH_CONFIG_ID"],
        callback_url=callback_url,
    )

    return {"redirect_url": connection_request.redirect_url}

@app.get("/api/slack_oauth_callback")
async def slack_oauth_callback(request: Request):
    from fastapi.responses import RedirectResponse
    user_id = request.query_params.get("user_id")
    return RedirectResponse(url=f"https://frontend-three-psi-61.vercel.app?user_id={user_id}")

@app.get("/api/slack_channels")
async def slack_channels(request: Request):
    user_id = request.query_params.get("user_id")
    client = get_composio()
    result = client.tools.execute(
        slug="SLACK_LIST_ALL_CHANNELS",
        user_id=user_id,
        version="20251126_02",
        arguments={"limit": 100, "types": "public_channel,private_channel,im,mpim"},
    )
    channels = result.get("data", {}).get("channels", [])
    return [{"id": c["id"], "name": c.get("name") or c.get("user") or c["id"]} for c in channels]


@app.post('/calendly-webhook')
async def calendly_webhook(request: Request, payload: dict = Body(...)):
    user_id = request.query_params.get("user_id")
    invitee = payload.get("payload", {})
    scheduled_event = invitee.get("scheduled_event", {})

    supabase.table("calendly_events").insert({
        "user_id": user_id,
        "event_name": scheduled_event.get("name"),
        "invitee_name": invitee.get("name"),
        "invitee_email": invitee.get("email"),
        "start_time": scheduled_event.get("start_time"),
        "end_time": scheduled_event.get("end_time"),
        "cancel_url": invitee.get("cancel_url"),
        "reschedule_url": invitee.get("reschedule_url"),
    }).execute()


@app.post('/api/send-slack')
async def send_slack(payload: dict = Body(...)):
    print("Payload:", payload)
    record = payload.get("record", {})
    user_id = record.get("user_id")

    user = supabase.table("users").select("channel_id, message_format").eq("name", user_id).single().execute()

    text = (
        f"{user.data['message_format'] or ''}\n\n"
        f"Event: {record.get('event_name')}\n"
        f"Invitee: {record.get('invitee_name')} ({record.get('invitee_email')})\n"
        f"Start - end: {record.get('start_time')} - {record.get('end_time')}\n"
        f"Cancel: {record.get('cancel_url')}\n"
        f"Reschedule: {record.get('reschedule_url')}"
    )

    get_composio().tools.execute(
        slug="SLACK_SEND_MESSAGE",
        user_id=user_id,
        version=SLACK_TOOL_VERSION,
        arguments={"channel": user.data["channel_id"], "text": text},
    )
    return {"status": "sent"}


@app.post("/instantly-webhook")
async def instantly_webhook(payload: dict = Body(...)):
    composio = get_composio()

    data = payload
    campaign_name = data["campaign_name"]
    lead_email = data["lead_email"]
    reply_msg = data["reply_text_snippet"]
    link = data["unibox_url"]
    domain = lead_email.split("@")[1]
    company_name = domain.split(".")[0]

    text = (
        f"New email reply received!\n\n"
        f"Campaign: {campaign_name}\n"
        f"Company: {company_name}\n"
        f"Lead: {lead_email}\n"
        f"Reply message:\n{reply_msg}\n"
        f"Open in Instantly: {link}"
            )

    result = composio.tools.execute(
            slug="SLACK_SEND_MESSAGE",
            user_id=SLACK_USER_ID,
            version=SLACK_TOOL_VERSION,
            arguments={
                "channel": CHANNEL_ID,
                "text": text,
            },
        )
    print(result)

@app.get("/api/attio_oauth_start")
async def attio_oauth_start(request: Request):
    client = get_composio()
    user_id = request.query_params.get("user_id")

    backend_base = os.getenv("BACKEND_BASE_URL")
    callback_url = f"{backend_base}/api/attio_oauth_callback?user_id={user_id}"

    connection_request = client.connected_accounts.link(
        user_id=user_id,
        auth_config_id=os.environ["ATTIO_AUTH_CONFIG_ID"],
        callback_url=callback_url,
    )

    return {"redirect_url": connection_request.redirect_url}

@app.get("/api/attio_oauth_callback")
async def attio_oauth_callback(request: Request):
    from fastapi.responses import RedirectResponse
    user_id = request.query_params.get("user_id")
    print(f"Attio connected for user: {user_id}")

    # Test MCP with hardcoded prompt
    result = await ai_action({
        "user_id": user_id,
        "prompt": "Add a user called John Smith and attatch a note saying meeting notes:meeting was canceled"
    })
    print(f"MCP Test Result: {result}")

    return RedirectResponse(url=f"https://frontend-three-psi-61.vercel.app?user_id={user_id}")

@app.post('/api/ai-action')
async def ai_action(payload: dict = Body(...)):
    """Send a prompt to Claude with Attio tools via MCP"""
    from anthropic import Anthropic

    user_id = payload.get("user_id")
    prompt = payload.get("prompt")

    server = get_mcp_server()
    mcp_url = f"{server.mcp_url}?user_id={user_id}"

    response = Anthropic().beta.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=4096,
        system="You are a helpful assistant with access to Attio, HubSpot, and Notion. Use the tools without asking for confirmation.",
        messages=[{"role": "user", "content": prompt}],
        mcp_servers=[{"type": "url", "url": mcp_url, "name": "crm"}],
        betas=["mcp-client-2025-04-04"]
    )

    return response
    for block in response.content:
        if hasattr(block, 'text'):
            return {"result": block.text}
    return {"result": "No text response"}

@app.post('/api/create-attio-record')
async def create_attio_record(payload: dict = Body(default={})):
    client = get_composio()
    record = payload.get("record", {})
    user_id = record.get("user_id")

    result = client.tools.execute(
        slug="ATTIO_CREATE_RECORD",
        user_id=user_id,
        version=ATTIO_TOOLKIT_VERSION,
        arguments={
            "object_type": "people",
            "values": {
                "name": [{"first_name": "Test", "last_name": "Person", "full_name": "Test Person"}],
                "email_addresses": [{"email_address": "test@example.com"}]
            }
        }
    )
    print("Attio result:", result)
    return result

@app.get("/api/hubspot_oauth_start")
async def hubspot_oauth_start(request: Request):
    client = get_composio()
    user_id = request.query_params.get("user_id")

    backend_base = os.getenv("BACKEND_BASE_URL")
    callback_url = f"{backend_base}/api/hubspot_oauth_callback?user_id={user_id}"

    connection_request = client.connected_accounts.link(
        user_id=user_id,
        auth_config_id=os.environ["HUBSPOT_AUTH_CONFIG_ID"],
        callback_url=callback_url,
    )

    return {"redirect_url": connection_request.redirect_url}

@app.get("/api/hubspot_oauth_callback")
async def hubspot_oauth_callback(request: Request):
    from fastapi.responses import RedirectResponse
    user_id = request.query_params.get("user_id")
    print(f"HubSpot connected for user: {user_id}")

    result = await ai_action({
        "user_id": user_id,
        "prompt": "Create a contact for Essam Sleiman at essam@gmail.com in HubSpot"
    })
    print(f"MCP Test Result: {result}")

    return RedirectResponse(url=f"https://frontend-three-psi-61.vercel.app?user_id={user_id}")

@app.get("/api/notion_oauth_start")
async def notion_oauth_start(request: Request):
    client = get_composio()
    user_id = request.query_params.get("user_id")

    backend_base = os.getenv("BACKEND_BASE_URL")
    callback_url = f"{backend_base}/api/notion_oauth_callback?user_id={user_id}"

    connection_request = client.connected_accounts.link(
        user_id=user_id,
        auth_config_id=os.environ["NOTION_AUTH_CONFIG_ID"],
        callback_url=callback_url,
    )

    return {"redirect_url": connection_request.redirect_url}

@app.get("/api/notion_oauth_callback")
async def notion_oauth_callback(request: Request):
    from fastapi.responses import RedirectResponse
    user_id = request.query_params.get("user_id")
    print(f"Notion connected for user: {user_id}")

    result = await ai_action({
        "user_id": user_id,
        "prompt": "Create a new note about astronomy in Notion"
    })
    print(f"MCP Test Result: {result}")

    return RedirectResponse(url=f"https://frontend-three-psi-61.vercel.app?user_id={user_id}")

