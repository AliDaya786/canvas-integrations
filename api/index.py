import os
from fastapi import FastAPI, Body, Request
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client

os.environ.setdefault("COMPOSIO_CACHE_DIR", "/tmp/.composio")
from composio import Composio

SLACK_TOOL_VERSION = "20251118_00"
CALENDLY_TOOLKIT_VERSION = "20251111_01"
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