# -*- coding: utf-8 -*-
"""Publish to ACC - the parts that need .NET.

HTTP through WebRequest (present on .NET Framework 4.8 and .NET 8), the
sign-in callback through a plain TcpListener on the loopback address (no URL
reservation or admin rights needed, unlike HttpListener), the browser through
the shell, and the refresh token encrypted with Windows DPAPI for the current
user. If DPAPI is not available the token is kept for this run only.

The waiting loop polls the socket for 0.2 s at a time and pumps the window
between polls. It never calls Thread.Sleep: on Revit's STA thread that is
what once opened a blank pyRevit output window.
"""
import os
import time

import mcu_clr  # noqa: F401 - must come before any System.* import
import mcu_core as core
import mcu_aps as aps
import mcu_json as js

from System import Array, Byte, Convert
from System.IO import StreamReader
from System.Text import Encoding
from System.Net import (WebRequest, WebException, ServicePointManager,
                        SecurityProtocolType, IPAddress)
from System.Net.Sockets import TcpListener, SelectMode
from System.Diagnostics import Process, ProcessStartInfo


class PublishError(Exception):
    pass


class Cancelled(Exception):
    pass


# the token for this run of the tool
SESSION = {u"token": None, u"client": u""}


# ============================================================
# HTTP
# ============================================================

def _tls():
    try:
        ServicePointManager.SecurityProtocol = (
            ServicePointManager.SecurityProtocol | SecurityProtocolType.Tls12)
    except Exception:
        pass


def http(method, url, body=None, content_type=None, token=None, timeout_ms=30000):
    """(status, text). Non-2xx answers are returned, not raised."""
    _tls()
    request = WebRequest.Create(url)
    request.Method = method
    request.Timeout = timeout_ms
    try:
        request.Accept = u"application/json, application/vnd.api+json"
    except Exception:
        pass
    if token:
        request.Headers.Add(u"Authorization", u"Bearer " + token)
    if body is not None:
        data = Encoding.UTF8.GetBytes(body)
        request.ContentType = content_type
        request.ContentLength = data.Length
        stream = request.GetRequestStream()
        try:
            stream.Write(data, 0, data.Length)
        finally:
            stream.Close()
    try:
        response = request.GetResponse()
    except WebException as error:
        response = getattr(error, u"Response", None)
        if response is None:
            raise PublishError(u"No answer from Autodesk ({0}). Check the internet "
                               u"connection or proxy.".format(core.to_text(error)))
    try:
        status = int(response.StatusCode)
        reader = StreamReader(response.GetResponseStream(), Encoding.UTF8)
        text = reader.ReadToEnd()
    finally:
        response.Close()
    core.log(u"APS {0} {1} -> {2}".format(method, url.split(u"?")[0], status))
    return status, core.to_text(text)


def ok(status):
    return 200 <= int(status) < 300


# ============================================================
# token store (DPAPI)
# ============================================================

def store_path():
    return os.path.join(core.appdata_dir(), u"model_cleanup_aps.txt")


def _protect(value):
    try:
        from System.Security.Cryptography import ProtectedData, DataProtectionScope
        data = ProtectedData.Protect(Encoding.UTF8.GetBytes(value), None,
                                     DataProtectionScope.CurrentUser)
        return Convert.ToBase64String(data)
    except Exception:
        return None


def _unprotect(value):
    try:
        from System.Security.Cryptography import ProtectedData, DataProtectionScope
        data = ProtectedData.Unprotect(Convert.FromBase64String(value), None,
                                       DataProtectionScope.CurrentUser)
        return core.to_text(Encoding.UTF8.GetString(data))
    except Exception:
        return u""


def save_refresh(client_id, refresh):
    protected = _protect(refresh) if refresh else None
    if not protected:
        forget()
        return False
    return core.write_kv(store_path(), [(u"client_id", client_id), (u"refresh", protected)],
                         u"RevoBIM ACC sign-in (encrypted for this Windows user)")


def load_refresh(client_id):
    raw = core.read_kv(store_path())
    if raw.get(u"client_id") != client_id or not raw.get(u"refresh"):
        return u""
    return _unprotect(raw[u"refresh"])


def forget():
    SESSION[u"token"] = None
    try:
        if os.path.isfile(store_path()):
            os.remove(store_path())
    except Exception:
        pass


def signed_in_text(client_id):
    token = SESSION.get(u"token")
    if token is not None and SESSION.get(u"client") == client_id and token.valid():
        return u"Signed in for this session."
    if client_id and load_refresh(client_id):
        return u"Signed in (remembered for this Windows user)."
    return u"Not signed in. The first publish opens the browser."


# ============================================================
# sign-in
# ============================================================

def open_browser(url):
    info = ProcessStartInfo(url)
    info.UseShellExecute = True
    Process.Start(info)


def _read_request_line(stream):
    buffer = Array.CreateInstance(Byte, 8192)
    count = stream.Read(buffer, 0, buffer.Length)
    if count <= 0:
        return u""
    text = core.to_text(Encoding.ASCII.GetString(buffer, 0, count))
    return text.split(u"\r\n")[0]


def _send(stream, data):
    array = Array[Byte](list(bytearray(data)))
    stream.Write(array, 0, array.Length)


def sign_in(client_id, port, tick, timeout=240.0):
    """Browser sign-in. tick() is called between socket polls; it pumps the
    window and raises Cancelled when the user pressed Escape."""
    verifier = aps.new_verifier()
    state = aps.new_state()
    listener = TcpListener(IPAddress.Loopback, int(port))
    try:
        listener.Start()
    except Exception:
        raise PublishError(
            u"Port {0} is already in use on this PC. Pick another sign-in port in "
            u"Export Settings, and add the matching callback URL to the APS app:\n{1}"
            .format(port, aps.callback_url(port)))
    code = None
    try:
        open_browser(aps.authorize_url(client_id, port, aps.challenge_for(verifier), state))
        started = time.time()
        while code is None:
            if time.time() - started > timeout:
                raise PublishError(u"No sign-in arrived within {0} minutes.".format(int(timeout // 60)))
            tick()
            if not listener.Server.Poll(200000, SelectMode.SelectRead):
                continue
            client = listener.AcceptTcpClient()
            try:
                client.ReceiveTimeout = 5000
                stream = client.GetStream()
                line = _read_request_line(stream)
                code, error = aps.parse_callback(line, state)
                if code:
                    _send(stream, aps.callback_response(u"Signed in. Model Cleanup is publishing."))
                elif error:
                    _send(stream, aps.callback_response(u"Sign-in failed: " + error))
                    raise PublishError(u"Sign-in failed: " + error)
                else:
                    _send(stream, aps.callback_response(u"Waiting for sign-in."))
            finally:
                client.Close()
    finally:
        try:
            listener.Stop()
        except Exception:
            pass
    status, body = http(u"POST", aps.TOKEN_URL, aps.code_request(client_id, port, code, verifier),
                        u"application/x-www-form-urlencoded")
    if not ok(status):
        raise PublishError(u"Sign-in could not be completed.\n\n" + aps.explain_status(status, body))
    return aps.token_from_reply(body)


def refresh(client_id, refresh_token):
    status, body = http(u"POST", aps.TOKEN_URL, aps.refresh_request(client_id, refresh_token),
                        u"application/x-www-form-urlencoded")
    if not ok(status):
        return None
    try:
        return aps.token_from_reply(body)
    except Exception:
        return None


def get_token(client_id, port, tick, allow_browser=True):
    """A valid access token: this run's, else a refreshed remembered one,
    else a browser sign-in (unless allow_browser is off - then None)."""
    token = SESSION.get(u"token")
    if token is not None and SESSION.get(u"client") == client_id and token.valid():
        return token.access
    remembered = load_refresh(client_id)
    if remembered:
        token = refresh(client_id, remembered)
        if token is None:
            forget()
    if token is None or not token.valid():
        if not allow_browser:
            return None
        token = sign_in(client_id, port, tick)
    SESSION[u"token"] = token
    SESSION[u"client"] = client_id
    if token.refresh and not save_refresh(client_id, token.refresh):
        core.log(u"ACC sign-in kept for this run only - DPAPI is not available")
    return token.access


# ============================================================
# the model on ACC
# ============================================================

def _call(doc, name):
    method = getattr(doc, name, None)
    if method is None:
        return u""
    for args in ((), (False,)):
        try:
            return core.to_text(method(*args))
        except TypeError:
            continue
        except Exception:
            return u""
    return u""


def model_guid(doc):
    try:
        return core.to_text(doc.GetCloudModelPath().GetModelGUID())
    except Exception:
        return u""


def resolve_item(doc, token):
    """(project id, item lineage urn) of the open cloud model."""
    project = aps.dm_project_id(_call(doc, u"GetProjectId"))
    if not project:
        raise PublishError(u"Revit did not report which ACC project this model is in.")
    urn = _call(doc, u"GetCloudModelUrn")
    if aps.is_lineage(urn):
        return project, urn
    if aps.is_version(urn):
        status, body = http(u"GET", aps.version_url(project, urn), token=token)
        if ok(status):
            item = aps.item_from_version_reply(body)
            if item:
                return project, item
    folder = _call(doc, u"GetCloudFolderId")
    guid = model_guid(doc)
    url = aps.folder_url(project, folder) if folder else u""
    pages = 0
    while url and pages < 20:
        status, body = http(u"GET", url, token=token)
        if not ok(status):
            raise PublishError(aps.explain_status(status, body))
        item = aps.item_from_folder_reply(body, guid)
        if item:
            return project, item
        url = js.dig(js.loads(body), u"links", u"next", u"href") or u""
        pages += 1
    raise PublishError(u"This model could not be found in its ACC folder.")


def _command(token, project, command_type, item):
    return http(u"POST", aps.commands_url(project), aps.command_body(command_type, item),
                aps.JSONAPI_TYPE, token)


def job_state(token, project, item):
    status, body = _command(token, project, aps.CMD_GET_JOB, item)
    if not ok(status):
        return aps.JOB_UNKNOWN, u"HTTP {0}".format(status)
    try:
        return aps.job_state(body)
    except Exception:
        return aps.JOB_UNKNOWN, u"unreadable reply"


def publish(token, project, item, with_links):
    status, body = _command(token, project, aps.publish_command(with_links), item)
    if status == 401:
        return False, 401
    if not ok(status):
        raise PublishError(aps.explain_status(status, body))
    return True, status
