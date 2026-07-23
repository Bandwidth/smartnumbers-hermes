# Hermes Smartnumbers

Hermes plugin for receiving Smartnumbers conversation transcripts, importing
them into Hermes history and memory, and exposing transcript search and review
tools.

## Install

Install and enable the plugin from GitHub:

```bash
hermes plugins install Bandwidth/smartnumbers-hermes --enable
```

Git plugin installation does not install Python dependencies. If `websockets`
is not already available in the Python environment that runs Hermes, install
it there:

```bash
python -m pip install 'websockets>=14,<16'
```

Connect the installed plugin to Smartnumbers:

```bash
hermes smartnumbers setup
```

The browser setup flow obtains an API key, saves it to Hermes' `.env` as
`TRANSCRIPT_LISTENER_API_KEY`, enables the listener, and writes the connection
settings under `plugins.entries.smartnumbers`.

### Remote Or Docker Setup

When Hermes and the browser run on different machines, use manual callback
paste instead of publishing a temporary callback port:

```bash
hermes smartnumbers setup --manual-paste --no-browser
```

Open the printed URL in a browser, approve the connection, then copy the
complete redirect URL from the browser address bar and paste it into the
Hermes terminal. The browser showing a connection error for the loopback
callback is expected. Hermes validates the callback state and exchanges the
one-time code using the same PKCE flow as local setup.

Manual setup uses `http://127.0.0.1:3021/callback` by default. Set a different
browser-visible loopback port with `--callback-port` if needed.

Restart the gateway to load the saved connection:

```bash
hermes gateway restart
```

Confirm that the plugin is installed and enabled:

```bash
hermes plugins list
hermes smartnumbers status
```

To inspect or clear setup state:

```bash
hermes smartnumbers status
hermes smartnumbers clear
```

## Configuration

Browser setup writes the required connection values. Additional behavior can
be configured in `$HERMES_HOME/config.yaml`:

```yaml
plugins:
  enabled:
    - smartnumbers
  entries:
    smartnumbers:
      run_listener: true
      stream_url: "wss://connections.smartnumbers.labs.bandwidth.com/ws/hermes"
      app_url: "https://smartnumbers.labs.bandwidth.com"
      user_speaker: "TO"
      archive_raw: true
      import_to_session_db: true
      extract_to_memory: true
      register_transcript_search_tool: true
      notify_cli: true
      auto_review_transcripts: true
      auto_review_deliver: "local"
      download_timeout_seconds: 15
      max_download_bytes: 5242880
      allow_insecure_transcript_urls: false
```

When `archive_raw` is enabled, transcripts are stored at
`$HERMES_HOME/transcript_listener/transcripts.db`. The plugin exposes:

- `transcript_search` to search archived transcript turns.
- `transcript_review_config` to show, set, or clear automatic review
  instructions.

When review instructions are present and `auto_review_transcripts` is enabled,
the plugin schedules a one-shot Hermes cron task for each new transcript.

## WebSocket Flow

Hermes maintains an outbound WebSocket connection to Smartnumbers and sends
the API key in the upgrade request:

```http
Authorization: Bearer <TRANSCRIPT_LISTENER_API_KEY>
```

After connecting, Hermes sends protocol metadata:

```json
{
  "type": "hello",
  "protocol_version": 1,
  "client": "hermes-transcript-listener"
}
```

Smartnumbers sends a presigned transcript URL:

```json
{
  "type": "transcript_url",
  "event_id": "evt_123",
  "conversation_id": "call_123",
  "source": "bandwidth-call-recording",
  "user_speaker": "TO",
  "url": "https://presigned-s3-url...",
  "expires_at": "2026-06-02T18:00:00Z"
}
```

The downloaded response can contain Markdown transcript blocks:

```md
1
[00:00:02,200 --> 00:00:13,079]
**TO**: Column's scheduling business. This is Erica speaking.

2
[00:00:14,609 --> 00:00:16,450]
**FROM**: Hello, I'd like to schedule an appointment.
```

Direct transcript JSON messages are also accepted for local development:

```json
{
  "conversation_id": "conv_001",
  "source": "test-fixture",
  "participants": {
    "user": "Damien",
    "person_x": "Alex"
  },
  "turns": [
    {
      "speaker": "user",
      "text": "I prefer getting the short version first, then details if I ask."
    },
    {
      "speaker": "person_x",
      "text": "That makes sense. You usually want to move quickly."
    }
  ]
}
```

## Local Development

Run the test suite from the repository root:

```bash
uv run --extra dev pytest
```

The setup flow supports local Smartnumbers services with:

```bash
hermes smartnumbers setup --local
```

Use `--app-url`, `--setup-url`, and the callback options shown by
`hermes smartnumbers setup --help` when the local services run in containers.
