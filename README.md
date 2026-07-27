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

Browser setup writes every required connection value. No new environment
variables or configuration entries are required for normal production use.
The following optional settings are the common behavior overrides:

```yaml
plugins:
  enabled:
    - smartnumbers
  entries:
    smartnumbers:
      run_listener: true
      auto_review_transcripts: true
      auto_review_deliver: "local"
      # Omit auto_review_toolsets to preserve Hermes' full cron toolset.
      # Set it when a post-call job should be restricted.
```

Advanced overrides are optional: `activation_names` adds STT aliases;
`user_speaker_by_direction` changes the default inbound `TO` and outbound
`FROM` authority mapping; `trust_event_direction` accepts authenticated provider
direction metadata; `auto_review_toolsets` restricts post-call tool access; and
`allowed_transcript_hosts` pins production transcript storage hosts. Setup saves
the approved stream host automatically.

When `archive_raw` is enabled, transcripts are stored at
`$HERMES_HOME/transcript_listener/transcripts.db`. The plugin exposes:

- `transcript_search` to search archived transcript turns.
- `transcript_review_config` to show, set, or clear automatic review
  instructions.

When review instructions are present and `auto_review_transcripts` is enabled,
the plugin schedules a one-shot Hermes cron task for each new transcript.

## Post-Call Automation

Post-call behavior is generic. There are no callback types for calendars,
email, tasks, or other services. A callback is user-authorized natural-language
instructions that Hermes evaluates after a new call, with the same configured
cron tool access as the existing automatic review job.

`transcript_review_config` retains its existing actions:

- `show`, `set`, and `clear` manage the `default-review` callback.

It also supports independent callbacks:

- `list`
- `register` with a new `id`, `name`, and `instructions`
- `update` with an existing `id`, `name`, and `instructions`
- `enable`, `disable`, and `remove` with `id`

For example, Hermes can register an arbitrary callback after a normal user
request:

```text
Whenever I agree to attend an event on a call, add it to my calendar.
```

### Named Call Commands

The configured user speaker can issue a one-time arbitrary Hermes command at
any point in a turn by directly addressing Hermes with its active branding name
or its first word. If the branding name is `Ares Agent`, both forms are
accepted:

```text
TO: Ares, add that event to my calendar.
TO: Hey Ares Agent, research that company and send me a summary.
TO: Friday sounds good. Ares, add that to my calendar. What time should I arrive?
```

Commands from the other party and incidental mentions of the name do not
authorize work. The local direction mapping determines the authoritative
speaker; a payload cannot select it. Current inbound calls use `TO` by default.
Hermes extracts the verbatim command span without requiring it to consume the
rest of the speaker turn. Multiple direct addresses in one turn are independent
commands.

Named command jobs and generic callback jobs keep `auto_review_toolsets` as-is.
When it is omitted, Hermes' cron default toolsets are preserved. Hermes' normal
approval configuration, including `approvals.mode` and `approvals.cron_mode`,
continues to control tool approvals.

Callback changes from a scheduled job require a short-lived authorization token
issued only to a named-command job. This prevents a normal callback or call
participant from silently modifying future callback behavior.

### Trust Boundary

Transcript turns are external call data. They can provide dates, contacts,
locations, and context, but they do not independently authorize Hermes actions.
Only a named command from the configured user speaker or an already registered
callback creates an action goal. When a user intentionally grants a generic
callback broad Hermes tool access, its instructions should be reviewed as
carefully as any other autonomous Hermes automation.

Durable-fact extraction accepts facts stated directly by the configured user
speaker. A fact stated by another participant is eligible only when a later
turn from the configured user speaker clearly agrees with or verifies it. Each
fact must cite the numbered assertion turn and exact source text; caller facts
must also cite the later user-confirmation turn. Unconfirmed caller statements
remain available through transcript search but are not written to memory.

`transcript_search` returns `source_trust: "external-untrusted"` and supports
pagination through `offset` and `next_offset` so long calls can be retrieved
without silently truncating the result set.

Transcript size is not capped by default. Complete transcripts are archived,
and durable-fact extraction processes every turn in bounded LLM batches using
the existing `batch_max_chars` setting. Optional size limits exist only as
explicit deployment overrides.

## Network And Storage Safety

The listener requires an approved `wss://` stream host before sending its API
key. Setup records the provider-approved stream host. Custom plaintext streams
are supported only for explicit local development configuration.

Transcript URL downloads reject redirects and private, loopback, link-local,
multicast, reserved, and metadata-network addresses. Set
`allowed_transcript_hosts` when production transcript storage has a stable host
list.

The archive directory, database, SQLite sidecars, and listener lock are created
with private owner-only permissions. Archive execution records prevent replayed
events from scheduling duplicate callback or named-command jobs.

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
