# -*- coding: utf-8 -*-
"""Publish to ACC - every rule, no .NET.

Revit has no API to publish a cloud workshared model. Autodesk's route is the
Data Management API command endpoint:

    POST /data/v1/projects/:project_id/commands
        commands:autodesk.bim360:C4RModelPublish        publish latest, with links
        commands:autodesk.bim360:C4RPublishWithoutLinks publish latest, no links
        commands:autodesk.bim360:C4RModelGetPublishJob  is a publish running / needed

All three need a user (3-legged) token. The token comes from a PKCE sign-in
in the browser against the user's own APS app, so no client secret is ever
stored. Only the refresh token is kept, encrypted for the Windows user.
"""
import base64
import hashlib
import os
import re
import time

import mcu_json as js

APS_HOST = u"https://developer.api.autodesk.com"
AUTHORIZE_URL = APS_HOST + u"/authentication/v2/authorize"
TOKEN_URL = APS_HOST + u"/authentication/v2/token"
SCOPES = u"data:read data:write data:create"
CALLBACK_PATH = u"/revobim/callback"
DEFAULT_PORT = 8765

CMD_PUBLISH = u"commands:autodesk.bim360:C4RModelPublish"
CMD_PUBLISH_NO_LINKS = u"commands:autodesk.bim360:C4RPublishWithoutLinks"
CMD_GET_JOB = u"commands:autodesk.bim360:C4RModelGetPublishJob"
JSONAPI_TYPE = u"application/vnd.api+json"

LINKS_ASK = u"ask"
LINKS_WITH = u"with"
LINKS_WITHOUT = u"without"
LINK_CHOICES = [LINKS_ASK, LINKS_WITH, LINKS_WITHOUT]

SETUP_HELP = (
    u"Publishing needs a one-time setup, because Revit has no publish API and "
    u"the tool has to use Autodesk Platform Services instead:\n\n"
    u"1. At aps.autodesk.com, create an app of type 'Desktop, Mobile, "
    u"Single-Page App' with the Data Management API.\n"
    u"2. Add this callback URL to it: {callback}\n"
    u"3. Ask your ACC account admin to add the app's Client ID under Account "
    u"Admin > Custom Integrations.\n"
    u"4. Paste the Client ID into Model Cleanup > Export Settings.\n\n"
    u"After that, the first publish opens a browser to sign in once.")


def text(value):
    if value is None:
        return u""
    return value if isinstance(value, type(u"")) else u"{0}".format(value)


# ============================================================
# PKCE and sign-in
# ============================================================

def b64url(data):
    encoded = base64.urlsafe_b64encode(data)
    if not isinstance(encoded, type(u"")):
        encoded = encoded.decode(u"ascii")
    return encoded.rstrip(u"=")


def new_verifier(random_bytes=None):
    raw = random_bytes if random_bytes is not None else os.urandom(48)
    return b64url(raw)


def challenge_for(verifier):
    digest = hashlib.sha256(verifier.encode(u"ascii")).digest()
    return b64url(digest)


def new_state(random_bytes=None):
    return b64url(random_bytes if random_bytes is not None else os.urandom(18))


def callback_url(port):
    return u"http://localhost:{0}{1}".format(int(port), CALLBACK_PATH)


def quote(value):
    safe = u"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_.~"
    out = []
    for byte in bytearray(text(value).encode(u"utf-8")):
        ch = chr(byte)
        out.append(ch if ch in safe else u"%{0:02X}".format(byte))
    return u"".join(out)


def unquote(value):
    raw = text(value).replace(u"+", u" ")
    data = bytearray()
    index = 0
    while index < len(raw):
        ch = raw[index]
        if ch == u"%" and index + 2 < len(raw) and re.match(u"^[0-9A-Fa-f]{2}$", raw[index + 1:index + 3]):
            data.append(int(raw[index + 1:index + 3], 16))
            index += 3
            continue
        data.extend(ch.encode(u"utf-8"))
        index += 1
    return bytes(data).decode(u"utf-8", u"replace")


def form(pairs):
    return u"&".join(u"{0}={1}".format(quote(k), quote(v)) for k, v in pairs)


def authorize_url(client_id, port, challenge, state):
    return AUTHORIZE_URL + u"?" + form([
        (u"response_type", u"code"),
        (u"client_id", client_id),
        (u"redirect_uri", callback_url(port)),
        (u"scope", SCOPES),
        (u"code_challenge", challenge),
        (u"code_challenge_method", u"S256"),
        (u"state", state),
    ])


def code_request(client_id, port, code, verifier):
    return form([
        (u"grant_type", u"authorization_code"),
        (u"code", code),
        (u"redirect_uri", callback_url(port)),
        (u"client_id", client_id),
        (u"code_verifier", verifier),
    ])


def refresh_request(client_id, refresh_token):
    return form([
        (u"grant_type", u"refresh_token"),
        (u"refresh_token", refresh_token),
        (u"client_id", client_id),
        (u"scope", SCOPES),
    ])


def parse_callback(request_line, expected_state):
    """The browser's first request line, e.g.
    'GET /revobim/callback?code=..&state=.. HTTP/1.1'.
    Returns (code, error). Exactly one of them is set; (None, None) means the
    request was not the callback (a favicon, say) and should be ignored."""
    parts = text(request_line).split()
    if len(parts) < 2:
        return None, None
    target = parts[1]
    path, _, query = target.partition(u"?")
    if path != CALLBACK_PATH:
        return None, None
    params = {}
    for pair in query.split(u"&"):
        if not pair:
            continue
        key, _, value = pair.partition(u"=")
        params[unquote(key)] = unquote(value)
    if u"error" in params:
        return None, params.get(u"error_description") or params[u"error"]
    if params.get(u"state") != expected_state:
        return None, u"The sign-in reply did not match this request. Try again."
    if not params.get(u"code"):
        return None, u"The sign-in reply carried no code."
    return params[u"code"], None


CALLBACK_PAGE = (
    u"<html><head><title>RevoBIM</title></head>"
    u"<body style=\"font-family:Segoe UI;background:#232326;color:#E4E4E4;"
    u"padding:40px\"><h2 style=\"color:#4FA3E3\">RevoBIM</h2>"
    u"<p>{0}</p><p style=\"color:#9A9A9E\">You can close this tab and go back to Revit.</p>"
    u"</body></html>")


def callback_response(message):
    body = CALLBACK_PAGE.format(message).encode(u"utf-8")
    head = (u"HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\n"
            u"Content-Length: {0}\r\nConnection: close\r\n\r\n").format(len(body))
    return head.encode(u"ascii") + body


# ============================================================
# tokens
# ============================================================

class Token(object):
    def __init__(self, access=u"", refresh=u"", expires_at=0.0):
        self.access = access
        self.refresh = refresh
        self.expires_at = expires_at

    def valid(self, now=None, margin=120.0):
        now = time.time() if now is None else now
        return bool(self.access) and now < self.expires_at - margin


def token_from_reply(body, now=None):
    now = time.time() if now is None else now
    data = js.loads(body)
    access = js.dig(data, u"access_token")
    if not access:
        raise ValueError(u"Autodesk returned no access token: " + describe_error(data))
    try:
        seconds = float(js.dig(data, u"expires_in") or 0)
    except (TypeError, ValueError):
        seconds = 0.0
    return Token(access, js.dig(data, u"refresh_token") or u"", now + seconds)


def describe_error(data):
    if not isinstance(data, dict):
        return text(data)[:300]
    for key in (u"developerMessage", u"error_description", u"errorDescription",
                u"message", u"error"):
        if data.get(key):
            return text(data[key])
    errors = data.get(u"errors")
    if isinstance(errors, list) and errors:
        first = errors[0]
        if isinstance(first, dict):
            return text(first.get(u"detail") or first.get(u"title") or first)
    return js.dumps(data)[:300]


def explain_status(status, body):
    """A sentence for a failed call, naming the usual cause."""
    try:
        detail = describe_error(js.loads(body))
    except Exception:
        detail = text(body)[:300]
    hints = {
        400: u"Autodesk did not accept the request.",
        401: u"The sign-in has expired. Sign in again.",
        403: (u"Autodesk refused. Usually the APS app has not been added under "
              u"ACC Account Admin > Custom Integrations, or you lack edit rights "
              u"on this model's folder."),
        404: u"Autodesk could not find this model or project.",
        409: u"A publish is already running for this model.",
        429: u"Autodesk is rate limiting. Wait a minute and try again.",
    }
    head = hints.get(int(status), u"Autodesk returned HTTP {0}.".format(status))
    return head + (u"\n\n" + detail if detail else u"")


# ============================================================
# ids
# ============================================================

def dm_project_id(project_id):
    """ACC / BIM 360 project ids in the Data Management API carry 'b.'."""
    value = text(project_id).strip()
    if not value:
        return u""
    return value if value.startswith(u"b.") else u"b." + value


def is_lineage(urn):
    return text(urn).startswith(u"urn:adsk.wipprod:dm.lineage:") or \
        text(urn).startswith(u"urn:adsk.wipemea:dm.lineage:")


def is_version(urn):
    return u":fs.file:" in text(urn)


def item_from_version_reply(body):
    return js.dig(js.loads(body), u"data", u"relationships", u"item", u"data", u"id")


def item_from_folder_reply(body, model_guid):
    """Folder contents -> the item whose version carries this model GUID."""
    data = js.loads(body)
    wanted = text(model_guid).lower().strip(u"{}")
    for version in (data.get(u"included") or []):
        guid = js.dig(version, u"attributes", u"extension", u"data", u"modelGuid")
        if guid and text(guid).lower().strip(u"{}") == wanted:
            return js.dig(version, u"relationships", u"item", u"data", u"id")
    return None


def commands_url(project_id):
    return APS_HOST + u"/data/v1/projects/{0}/commands".format(dm_project_id(project_id))


def version_url(project_id, version_urn):
    return APS_HOST + u"/data/v1/projects/{0}/versions/{1}".format(
        dm_project_id(project_id), quote(version_urn))


def folder_url(project_id, folder_urn):
    return APS_HOST + u"/data/v1/projects/{0}/folders/{1}/contents".format(
        dm_project_id(project_id), quote(folder_urn))


def command_body(command_type, item_urn):
    return js.dumps({
        u"jsonapi": {u"version": u"1.0"},
        u"data": {
            u"type": u"commands",
            u"attributes": {u"extension": {u"type": command_type, u"version": u"1.0.0"}},
            u"relationships": {u"resources": {u"data": [
                {u"type": u"items", u"id": item_urn}]}},
        },
    })


def publish_command(with_links):
    return CMD_PUBLISH if with_links else CMD_PUBLISH_NO_LINKS


# ============================================================
# the publish job
# ============================================================

JOB_NEEDED = u"needed"
JOB_RUNNING = u"running"
JOB_DONE = u"done"
JOB_FAILED = u"failed"
JOB_UNKNOWN = u"unknown"


def job_state(body):
    """GetPublishModelJob: data null means the latest sync is not published
    yet; otherwise the job's status."""
    data = js.loads(body)
    if js.dig(data, u"data") is None:
        return JOB_NEEDED, u"not published since the last sync"
    status = text(js.dig(data, u"data", u"attributes", u"status")).lower()
    if status in (u"processing", u"queued", u"pending", u"inprogress", u"in_progress"):
        return JOB_RUNNING, status
    if status in (u"complete", u"completed", u"success", u"succeeded"):
        return JOB_DONE, status
    if status in (u"failed", u"failure", u"error", u"cancelled"):
        return JOB_FAILED, status
    return JOB_UNKNOWN, status or u"no status"


JOB_WORDS = {
    JOB_NEEDED: u"Waiting for ACC to pick it up",
    JOB_RUNNING: u"Publishing on ACC",
    JOB_DONE: u"Published on ACC",
    JOB_FAILED: u"ACC reports the publish failed",
    JOB_UNKNOWN: u"ACC status",
}


def job_line(state, status, elapsed_text):
    return u"{0} ({1}) - {2}".format(JOB_WORDS.get(state, u"ACC"), status, elapsed_text)


def poll_should_stop(state, elapsed, limit=900.0):
    return state in (JOB_DONE, JOB_FAILED) or elapsed >= limit


def normalise_links(value):
    value = text(value).strip().lower()
    return value if value in LINK_CHOICES else LINKS_ASK


def can_publish(info, synced):
    """None when the Publish button may light, else why not."""
    if not info.get(u"cloud"):
        return u"Only cloud models on ACC can be published."
    if not info.get(u"workshared"):
        return u"Only workshared cloud models are published."
    if not synced:
        return u"Sync first - ACC publishes the latest synced version."
    return None
