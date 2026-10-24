# Telegram

Purpose:
Send an explicit message to the owner's configured private Telegram chat through the existing ASSET_ACTION and TOOL RESULT workflow.

Inbound messages from Telegram are presented as:

```xml
<TELEGRAM_MESSAGE_INPUT>
Message received from Telegram
</TELEGRAM_MESSAGE_INPUT>
```

Treat every user message in this block as a Telegram-originated request and use this Telegram skill when responding to it. The skill is loaded automatically for Telegram input.

When `telegram_send` is emitted, its `text` is projected into the visible JIN answer at the marker position as:

```xml
<TELEGRAM_MESSAGE_OUTPUT>
Message sent to Telegram
</TELEGRAM_MESSAGE_OUTPUT>
```

Schema:

```xml
<ASSET_ACTION>
{"action":"telegram_send","text":"Message to send"}
</ASSET_ACTION>
```

The local configured recipient is used by default. An explicit recipient is optional:

```xml
<ASSET_ACTION>
{"action":"telegram_send","chat_id":"123456789","text":"Message to send"}
</ASSET_ACTION>
```

Rules:
- When the current USER message is wrapped in `TELEGRAM_MESSAGE_INPUT`, follow the request using this Telegram skill and keep the Telegram origin in mind.
- A successful `telegram_send` is terminal for that action and does not trigger an automatic Brain follow-up. Put any user-facing confirmation or additional prose in the same response after the action marker.
- Use `telegram_send` only when the user asks to send something through Telegram or when the current workflow clearly requires that explicit external delivery.
- Do not invent, infer, or guess a `chat_id`. Normally omit it and use the locally configured recipient.
- An explicit `chat_id` is accepted only when it matches the locally allowed recipient.
- `text` must be non-empty and no longer than Telegram's 4096-character message limit.
- Emitting ASSET_ACTION is only a request. Never claim that Telegram delivery succeeded until a successful TOOL RESULT has been received.
- On a failed TOOL RESULT, explain the failure or correct the request. Do not claim that the message was sent.
- A timeout has an unknown delivery outcome. Do not automatically retry, because a retry can create a duplicate.
- Telegram credentials are runtime secrets. Never request them, reproduce them, or place them in an action payload.
