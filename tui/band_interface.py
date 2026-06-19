"""Band interface — send messages to Supa via Koe proxy, poll for responses.

Architecture:
  - User messages are sent using Koe's API key (proxy) @mentioning Supa.
    This bypasses the self-mention restriction — Supa sees a message from
    Koe and processes it. Content is prefixed so Supa knows it's from the user.
  - Responses are polled using Supa's API key, listing all messages in the
    session's chatroom and filtering for Supa's replies.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Optional

from thenvoi_rest import RestClient
from thenvoi_rest.types.chat_message_request import ChatMessageRequest
from thenvoi_rest.types.chat_message_request_mentions_item import (
    ChatMessageRequestMentionsItem,
)
from thenvoi_rest.types.chat_room_request import ChatRoomRequest
from thenvoi_rest.types.participant_request import ParticipantRequest

from core.config import load_agent_config, PROJECT_ROOT

log = logging.getLogger(__name__)

# Agent config key mapping
CONFIG_KEYS = {
    "supa": "supervisor_agent",
    "koe": "research_manager",
    "mave": "marketing_manager",
    "forge": "operations_manager",
    "blobw1": "blob_worker_1",
    "blobw2": "blob_worker_2",
    "blobw3": "blob_worker_3",
}

# Agent UUIDs — loaded from agent_config.yaml at runtime (populated by setup.sh)
def _load_agent_ids() -> dict[str, str]:
    try:
        config = load_agent_config()
        ids = {}
        for key, entry in config.items():
            name = (entry.get("name") or key).lower().strip()
            if entry.get("agent_id"):
                ids[name] = str(entry["agent_id"])
        return ids
    except Exception:
        return {}

AGENT_IDS = _load_agent_ids()


class BandInterface:
    """Handles Band communication for the TUI."""

    def __init__(self):
        config = load_agent_config()

        # Supa client — for chatroom creation + polling responses
        supa_entry = config[CONFIG_KEYS["supa"]]
        self.supa_client = RestClient(
            api_key=supa_entry["api_key"],
            base_url="https://app.band.ai",
            timeout=30.0,
        )
        self.supa_id = supa_entry.get("agent_id", AGENT_IDS["supa"])
        self.supa_name = supa_entry.get("name", "Supa")

        # Koe client — proxy for sending user messages (triggers Supa)
        koe_entry = config[CONFIG_KEYS["koe"]]
        self.koe_client = RestClient(
            api_key=koe_entry["api_key"],
            base_url="https://app.band.ai",
            timeout=30.0,
        )
        self.koe_name = koe_entry.get("name", "Koe")

        # Void client — polls for echo=False responses (messages mentioning Void)
        void_entry = config.get("sink_agent", {})
        self.void_id = void_entry.get("agent_id", "")
        void_key = void_entry.get("api_key", "")
        if void_key and void_key != "none_needed":
            self.void_client = RestClient(
                api_key=void_key,
                base_url="https://app.band.ai",
                timeout=30.0,
            )
        else:
            self.void_client = None
            log.warning("Void agent API key not configured — echo=False responses won't be visible")

    def create_chatroom(self, title: str = "") -> str:
        """Create a new Band chatroom. Returns chat_id."""
        req = ChatRoomRequest()
        resp = self.supa_client.agent_api_chats.create_agent_chat(chat=req)
        chat_id = resp.data.id if hasattr(resp, "data") else str(resp)
        log.info(f"Created chatroom: {chat_id} ({title})")

        # Add Koe as participant (needed for proxy sends)
        try:
            self.supa_client.agent_api_participants.add_agent_chat_participant(
                chat_id=chat_id,
                participant=ParticipantRequest(
                    participant_id=AGENT_IDS["koe"]),
            )
        except Exception as e:
            log.warning(f"Failed to add Koe to room: {e}")

        # Add Void as participant (for echo=False responses)
        if self.void_id:
            try:
                self.supa_client.agent_api_participants.add_agent_chat_participant(
                    chat_id=chat_id,
                    participant=ParticipantRequest(
                        participant_id=self.void_id),
                )
            except Exception:
                pass  # Already in room

        return chat_id

    def send_user_message(self, chat_id: str, content: str,
                          context: str = "") -> bool:
        """Send a user message to the chatroom via Koe proxy, mentioning Supa.

        Ensures Koe is a participant first (Supa's startup cleanup may have
        removed Koe from idle rooms).

        Args:
            chat_id: Band chatroom UUID
            content: User's message text
            context: Optional prior context string to prepend
        Returns:
            True if sent successfully
        """
        # Ensure Koe is still a participant (Supa may have cleaned the room)
        try:
            self.supa_client.agent_api_participants.add_agent_chat_participant(
                chat_id=chat_id,
                participant=ParticipantRequest(
                    participant_id=AGENT_IDS["koe"]),
            )
        except Exception:
            pass  # Already a participant — ignore

        # Build the full message with context
        parts = []
        if context:
            parts.append(context)
            parts.append("")
        parts.append(f"[User message via TUI]")
        parts.append(content)
        full_content = "\n".join(parts)

        # Mention Supa so it processes the message
        mentions = [ChatMessageRequestMentionsItem(
            id=AGENT_IDS["supa"], name="supa")]

        try:
            msg = ChatMessageRequest(content=full_content, mentions=mentions)
            self.koe_client.agent_api_messages.create_agent_chat_message(
                chat_id=chat_id, message=msg)
            log.info(f"Sent user message to {chat_id[:8]}... ({len(full_content)} chars)")
            return True
        except Exception as e:
            log.error(f"Send failed: {e}")
            return False

    def poll_responses(self, chat_id: str,
                       seen_ids: set[str]) -> list[dict]:
        """Poll the chatroom for new messages from Supa.

        Polls via two API keys:
        1. Koe's key — sees messages where Supa mentions Koe (echo=True responses)
        2. Void's key — sees messages where Supa mentions Void (echo=False responses)

        This covers both response types: substantive (echo=True → mention Koe)
        and terminal/acknowledgment (echo=False → mention Void).

        Args:
            chat_id: Band chatroom UUID
            seen_ids: Set of already-seen message IDs
        Returns:
            List of {id, content, timestamp} dicts for new Supa messages
        """
        new_responses = []
        supa_id = AGENT_IDS["supa"]

        # Poll via Koe's key (echo=True responses)
        try:
            resp = self.koe_client.agent_api_messages.list_agent_messages(
                chat_id=chat_id, status="all", page_size=50)
            msgs = resp.data if hasattr(resp, "data") else []
            for m in msgs:
                if m.id in seen_ids:
                    continue
                sender_name = (m.sender_name or "").lower()
                sender_id = getattr(m, "sender_id", "") or ""
                if sender_id == supa_id or sender_name == "supa":
                    new_responses.append({
                        "id": m.id,
                        "content": m.content or "",
                        "timestamp": str(m.inserted_at or ""),
                    })
                    seen_ids.add(m.id)
        except Exception as e:
            # 404 is expected when Koe was cleaned from the room by Supa
            if "404" not in str(e):
                log.error(f"Poll via Koe failed: {e}")

        # Poll via Void's key (echo=False responses)
        if self.void_client:
            try:
                resp = self.void_client.agent_api_messages.list_agent_messages(
                    chat_id=chat_id, status="all", page_size=50)
                msgs = resp.data if hasattr(resp, "data") else []
                for m in msgs:
                    if m.id in seen_ids:
                        continue
                    sender_name = (m.sender_name or "").lower()
                    sender_id = getattr(m, "sender_id", "") or ""
                    if sender_id == supa_id or sender_name == "supa":
                        new_responses.append({
                            "id": m.id,
                            "content": m.content or "",
                            "timestamp": str(m.inserted_at or ""),
                        })
                        seen_ids.add(m.id)
            except Exception as e:
                if "404" not in str(e):
                    log.error(f"Poll via Void failed: {e}")

        return new_responses

    def list_chats(self) -> list[dict]:
        """List all chatrooms visible to Supa."""
        try:
            resp = self.supa_client.agent_api_chats.list_agent_chats(page_size=50)
            chats = resp.data if hasattr(resp, "data") else []
            return [
                {"id": c.id, "title": c.title or "(untitled)"}
                for c in chats
            ]
        except Exception as e:
            log.error(f"List chats failed: {e}")
            return []

    def get_chat_history(self, chat_id: str, limit: int = 50) -> list[dict]:
        """Get Supa's response history for a chatroom.
        Polls via both Koe and Void keys to capture all response types.
        Used to initialize seen_msg_ids when resuming a session."""
        results = {}
        for client in [self.koe_client, self.void_client]:
            if client is None:
                continue
            try:
                resp = client.agent_api_messages.list_agent_messages(
                    chat_id=chat_id, status="all", page_size=limit)
                msgs = resp.data if hasattr(resp, "data") else []
                for m in msgs:
                    results[m.id] = {
                        "id": m.id,
                        "sender": m.sender_name or "?",
                        "content": m.content or "",
                        "timestamp": str(m.inserted_at or ""),
                    }
            except Exception as e:
                log.error(f"History fetch failed: {e}")
        return list(results.values())
