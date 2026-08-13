# Hermes Smartnumbers

Hermes plugin for receiving and archiving Smartnumbers conversation transcripts,
extracting durable memory, and queuing tool-capable post-call agent reviews.

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
      # Omit auto_review_toolsets to preserve Hermes' configured cron toolset.
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
- `transcript_review_config` to manage automatic post-call callbacks.

When review instructions are present and `auto_review_transcripts` is enabled,
the plugin asynchronously queues a one-shot Hermes cron task for each new
transcript. The gateway scheduler runs that task in a fresh agent session with
the configured model, toolsets, and cron approval policy. The plugin does not
require Hermes' OpenAI-compatible API server or any additional local API
authentication.

The transcript archive is the review job's reference source. The agent reads it
through `transcript_search`; the plugin does not create an inert SessionDB
conversation or inject a message into an interactive CLI session. A review is
recorded as `queued` only after the cron tool confirms success and returns a
non-empty job ID. Invalid or unsuccessful creation responses are recorded as
retryable review errors rather than successful dispatches.

## Post-Call Automation

Post-call behavior is generic. There are no callback types for calendars,
email, tasks, or other services. A callback is user-authorized natural-language
instructions that Hermes evaluates after a new call, with the same configured
cron tool access as the existing automatic review job.

Each enabled callback runs as its own one-shot cron job in a fresh agent
session. Each job is scheduled immediately before it is dispatched, keeping it
as close as possible to transcript processing time while allowing the scheduler
to run independent callbacks concurrently. Keeping one goal per job also avoids
requiring the model to separate or coordinate unrelated callback instructions.
When multiple actions belong together, the user should put them in the same
callback instructions.

`transcript_review_config` retains its existing actions:

- `show`, `set`, and `clear` manage the `default-review` callback.

It also supports independent callbacks:

- `list`
- `register` with a new `id`, `name`, and `instructions`, plus an optional
  `deliver` target
- `update` with an existing `id`, `name`, and `instructions`, plus an optional
  `deliver` target
- `enable`, `disable`, and `remove` with `id`

The callback `deliver` value accepts `local`, `all`, or a configured gateway
platform such as `telegram`, including explicit targets such as
`telegram:-1001234567890:17585`. When it is omitted, the callback inherits
`auto_review_deliver`; an empty `deliver` value on update clears an existing
override. The `set` action also accepts `deliver` for the `default-review`
callback. Explicit overrides are validated when the callback is created or
updated against the live Hermes gateway configuration. Any built-in or plugin
platform is accepted when it is configured, enabled, and connected; an
unconfigured platform is rejected even if Hermes has built-in support for it.
Platform-only routes also require a configured home delivery location, while
an explicit `platform:destination` route only requires the platform itself to
be configured. `local` and `all` are always valid routing values, but neither
accepts an explicit destination. `origin` is not supported for transcript
callbacks because jobs are created by the background plugin rather than an
originating gateway conversation. An invalid route returns an error without
saving the callback change.

The transcript acknowledgement retains the backward-compatible review
`job_id` field and also returns `job_ids`, containing every independently
queued callback and named-command job associated with the transcript. Duplicate
events and partial-failure retries return the complete known list rather than
only the jobs created by the latest attempt.

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

Named command jobs and individual callback jobs keep `auto_review_toolsets` as-is.
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

Downloaded transcript size is not capped by default. Complete transcripts are
archived, and durable-fact extraction evaluates the complete finished transcript
in one structured LLM request. WebSocket event envelopes
are capped at 1 MiB by default through `max_websocket_message_bytes`; deployments
can raise that limit explicitly without limiting the referenced S3 transcript.

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
