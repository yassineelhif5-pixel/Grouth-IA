"""Periodic fallback synchronisation (missed webhooks): Gmail history, Microsoft Graph delta, IMAP (UIDs)."""
from __future__ import annotations

import base64
import imaplib
import ssl

from apps.core.db import fetch_one
from apps.integrations.gateway import get_credentials, http, load_account
from apps.integrations.providers import access_token

from .services import ingest, parse_raw


def _cursor(mailbox_id: str) -> str | None:
    row = fetch_one("SELECT cursor FROM public.email_sync_cursors WHERE mailbox_id = %s AND deleted_at IS NULL", [mailbox_id])
    return row[0] if row else None


def _save_cursor(tenant_id: str, mailbox_id: str, cursor: str) -> None:
    fetch_one("""INSERT INTO public.email_sync_cursors (tenant_id, mailbox_id, cursor, last_synced_at) VALUES (%s,%s,%s, now())
                 ON CONFLICT (tenant_id, mailbox_id) WHERE deleted_at IS NULL DO UPDATE SET cursor = EXCLUDED.cursor, last_synced_at = now() RETURNING id""",
              [tenant_id, mailbox_id, cursor])


def sync_mailbox(mailbox_id: str) -> dict:
    mb = fetch_one("SELECT tenant_id, connector_account_id, receive_mode, address FROM public.email_mailboxes WHERE id = %s", [mailbox_id])
    tid, account_id, mode, address = str(mb[0]), str(mb[1]) if mb[1] else None, mb[2], mb[3]
    run = fetch_one("INSERT INTO public.email_sync_runs (tenant_id, mailbox_id, status) VALUES (%s,%s,'running') RETURNING id", [tid, mailbox_id])[0]
    stored = 0
    try:
        if mode == "gmail":
            h = {"Authorization": f"Bearer {access_token(account_id)}"}
            cur = _cursor(mailbox_id)
            if not cur:
                cur = http("GET", "https://gmail.googleapis.com/gmail/v1/users/me/profile", provider="gmail", operation="profile", account_id=account_id, headers=h).json()["historyId"]
            d = http("GET", "https://gmail.googleapis.com/gmail/v1/users/me/history", provider="gmail", operation="history", account_id=account_id, headers=h,
                     params={"startHistoryId": cur, "historyTypes": "messageAdded", "labelId": "INBOX"}).json()
            for hrec in d.get("history", []):
                for ma in hrec.get("messagesAdded", []):
                    raw = http("GET", f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{ma['message']['id']}", provider="gmail", operation="get",
                               account_id=account_id, headers=h, params={"format": "raw"}).json()
                    r = ingest(mailbox_id, parse_raw(base64.urlsafe_b64decode(raw["raw"])), provider_message_id=raw["id"], provider_thread_id=raw.get("threadId"))
                    stored += r["status"] == "stored"
            _save_cursor(tid, mailbox_id, str(d.get("historyId", cur)))
        elif mode == "graph":
            h = {"Authorization": f"Bearer {access_token(account_id)}"}
            url = _cursor(mailbox_id) or "https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages/delta?$select=id,conversationId"
            while url:
                d = http("GET", url, provider="microsoft_graph", operation="delta", account_id=account_id, headers=h).json()
                for item in d.get("value", []):
                    mime = http("GET", f"https://graph.microsoft.com/v1.0/me/messages/{item['id']}/$value", provider="microsoft_graph", operation="mime",
                                account_id=account_id, headers=h).content
                    r = ingest(mailbox_id, parse_raw(mime), provider_message_id=item["id"], provider_thread_id=item.get("conversationId"))
                    stored += r["status"] == "stored"
                url = d.get("@odata.nextLink")
                if d.get("@odata.deltaLink"):
                    _save_cursor(tid, mailbox_id, d["@odata.deltaLink"])
        elif mode == "imap":
            acc, cred = load_account(account_id), get_credentials(account_id)
            last_uid = int(_cursor(mailbox_id) or 0)
            with imaplib.IMAP4_SSL(acc.settings["host"], int(acc.settings.get("port", 993)), ssl_context=ssl.create_default_context()) as m:
                m.login(cred["username"], cred["password"])
                m.select("INBOX", readonly=True)
                _, data = m.uid("search", None, f"UID {last_uid + 1}:*")
                for uid in (data[0] or b"").split()[:500]:
                    if int(uid) <= last_uid:
                        continue
                    _, msg = m.uid("fetch", uid, "(RFC822)")
                    r = ingest(mailbox_id, parse_raw(msg[0][1]), provider_message_id=f"imap:{int(uid)}")
                    stored += r["status"] == "stored"
                    last_uid = int(uid)
            _save_cursor(tid, mailbox_id, str(last_uid))
        else:
            fetch_one("UPDATE public.email_sync_runs SET status = 'succeeded', messages_synced = 0 WHERE id = %s RETURNING 1", [run])
            return {"status": "skipped", "reason": f"receive_mode={mode}"}
    except Exception as e:  # noqa: BLE001 — persisted then re-raised
        fetch_one("UPDATE public.email_sync_runs SET status = 'failed', error_message = %s WHERE id = %s RETURNING 1", [str(e)[:1000], run])
        fetch_one("UPDATE public.email_mailboxes SET sync_error = %s WHERE id = %s RETURNING 1", [str(e)[:500], mailbox_id])
        raise
    fetch_one("UPDATE public.email_sync_runs SET status = 'succeeded', messages_synced = %s WHERE id = %s RETURNING 1", [stored, run])
    fetch_one("UPDATE public.email_mailboxes SET last_sync_at = now(), sync_error = NULL WHERE id = %s RETURNING 1", [mailbox_id])
    _ = address
    return {"status": "succeeded", "stored": stored}
