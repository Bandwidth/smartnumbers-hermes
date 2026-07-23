# Smartnumbers Hermes Plugin

Hermes plugin for ingesting Smartnumbers conversation transcripts.

The plugin receives normalized JSON transcripts, stores the raw data locally,
renders speaker-labelled transcript text for model extraction, imports reference
sessions into Hermes history, and exposes a `transcript_search` tool.

## Presigned URL WebSocket Flow

Hermes keeps an outbound WebSocket connection open to the AWS application. The
plugin sends its API key in the WebSocket upgrade request:

```http
Authorization: Bearer <TRANSCRIPT_LISTENER_API_KEY>
```

After connecting, Hermes sends a hello frame with protocol metadata only. The AWS
application maps the API key to the user through auth-server introspection:

```json
{
  "type": "hello",
  "protocol_version": 1,
  "client": "hermes-transcript-listener"
}
```

The AWS application receives API requests containing S3 transcript locations,
creates presigned GET URLs, and sends one transcript URL per WebSocket message:

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

Hermes downloads the URL, expects the response body to be Markdown transcript
blocks or the legacy transcript JSON shape below, and then runs the existing
import pipeline. `conversation_id`, `source`, and `user_speaker` are read from
the WebSocket frame for Markdown transcripts. Direct transcript JSON messages
are still accepted for local development.

Markdown transcript blocks use this shape:

```md
1
[00:00:02,200 --> 00:00:13,079]
**TO**: Column's scheduling business. This is Erica speaking.

2
[00:00:14,609 --> 00:00:16,450]
**FROM**: Hello, I'd like to schedule an appointment.
```

When `archive_raw` is enabled, processed transcripts are stored in the
plugin-owned SQLite archive at `$HERMES_HOME/transcript_listener/transcripts.db`
and are available through `transcript_search`. When `archive_raw` is disabled,
the plugin skips that SQLite archive write but can still import transcripts into
Hermes SessionDB and run memory extraction.

Set `TRANSCRIPT_LISTENER_API_KEY` to the Labs Auth API key issued for the user
whose reserved smart numbers should receive transcript events.

## Initial Transcript JSON

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

The parser converts this provisional shape into an internal normalized model so
the wire format can evolve later.

## Installation

Install directly from GitHub with access to this private repository:

```bash
hermes plugins install Bandwidth/smartnumbers-hermes --enable
```

Hermes clones the repository but does not install Python dependencies. Run the
following command in the Python environment that runs Hermes if `websockets`
is not already available:

```bash
python -m pip install 'websockets>=14,<16'
```

The installer prompts for `TRANSCRIPT_LISTENER_API_KEY`. In non-interactive
environments, set it in `$HERMES_HOME/.env` before starting Hermes.

Configure the plugin in `$HERMES_HOME/config.yaml`:

```yaml
plugins:
  enabled:
    - smartnumbers
  entries:
    smartnumbers:
      run_listener: true
      stream_url: "wss://your-app.example.com/transcripts/ws"
      user_speaker: "TO"
      archive_raw: true
      download_timeout_seconds: 15
      max_download_bytes: 5242880
      allow_insecure_transcript_urls: false
```

Restart Hermes after installation or configuration changes:

```bash
hermes gateway restart
```

Verify installation with:

```bash
hermes plugins list
```

## Local Development

Run tests with `uv`:

```bash
uv run --extra dev pytest
```

To test the repository as a directory plugin without GitHub:

```bash
hermes plugins install file:///absolute/path/to/smartnumbers-hermes --force --enable
```

The plugin configuration key is `smartnumbers`:

```yaml
plugins:
  enabled:
    - smartnumbers
  entries:
    smartnumbers:
      run_listener: true
      stream_url: "wss://your-app.example.com/transcripts/ws"
      user_speaker: "TO"
      archive_raw: true
      download_timeout_seconds: 15
      max_download_bytes: 5242880
      allow_insecure_transcript_urls: false
```

Set `TRANSCRIPT_LISTENER_API_KEY` in the Hermes environment before starting the listener.
