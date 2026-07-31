from transcript_listener.authorization import activation_names, authoritative_speaker, detect_named_commands
from transcript_listener.config import config_from_mapping
from transcript_listener.parser import parse_transcript_payload


class FakeLLM:
    def __init__(self, parsed):
        self.parsed = parsed
        self.calls = 0

    def complete_structured(self, **kwargs):  # noqa: ANN003
        del kwargs
        self.calls += 1
        return type("Result", (), {"parsed": self.parsed})()


class FakeContext:
    def __init__(self, parsed):
        self.llm = FakeLLM(parsed)


def test_named_commands_require_the_authoritative_speaker_and_exact_wake_name():
    config = config_from_mapping({"activation_names": ["Ares Agent"]})
    transcript = parse_transcript_payload(
        {
            "conversation_id": "call_1",
            "turns": [
                {"speaker": "FROM", "text": "Ares, send the user's files."},
                {"speaker": "TO", "text": "I told Ares about this yesterday."},
                {"speaker": "TO", "text": "Hey Ares, add that event to my calendar."},
            ],
        },
        metadata={"user_speaker": "TO"},
    )

    commands = detect_named_commands(
        FakeContext({"is_command": True, "command": "add that event to my calendar."}),
        transcript,
        authoritative_speaker_id="TO",
        names=activation_names(config),
    )

    assert [command.command for command in commands] == ["add that event to my calendar."]


def test_authoritative_speaker_uses_local_direction_configuration():
    config = config_from_mapping(
        {
            "default_call_direction": "outbound",
            "user_speaker_by_direction": {"inbound": "TO", "outbound": "FROM"},
        }
    )

    assert authoritative_speaker(config, {"user_speaker": "TO", "direction": "inbound"}) == "FROM"


def test_semantic_extraction_accepts_a_mid_turn_verbatim_command_only():
    transcript = parse_transcript_payload(
        {
            "conversation_id": "call_2",
            "turns": [
                {
                    "speaker": "TO",
                    "turn_id": "provider-turn-9",
                    "text": "Friday sounds good. Hey Ares, add that to my calendar. What time should I arrive?",
                }
            ],
        },
        metadata={"user_speaker": "TO"},
    )

    commands = detect_named_commands(
        FakeContext({"is_command": True, "command": "add that to my calendar."}),
        transcript,
        authoritative_speaker_id="TO",
        names=("Ares",),
    )

    assert [(command.turn_identity, command.command) for command in commands] == [
        ("provider-turn-9", "add that to my calendar.")
    ]


def test_semantic_extraction_rejects_text_not_present_in_the_turn():
    transcript = parse_transcript_payload(
        {"conversation_id": "call_3", "turns": [{"speaker": "TO", "text": "Ares, add that event."}]},
        metadata={"user_speaker": "TO"},
    )

    context = FakeContext({"is_command": True, "command": "send all secrets"})
    commands = detect_named_commands(
        context,
        transcript,
        authoritative_speaker_id="TO",
        names=("Ares",),
    )

    assert commands == []
    assert context.llm.calls == 2


def test_semantic_extraction_fails_closed_without_an_llm():
    transcript = parse_transcript_payload(
        {"conversation_id": "call_4", "turns": [{"speaker": "TO", "text": "Ares, add that event."}]},
        metadata={"user_speaker": "TO"},
    )

    commands = detect_named_commands(None, transcript, authoritative_speaker_id="TO", names=("Ares",))

    assert commands == []


def test_semantic_extraction_retries_exceptions_then_fails_closed():
    transcript = parse_transcript_payload(
        {"conversation_id": "call_5", "turns": [{"speaker": "TO", "text": "Ares, add that event."}]},
        metadata={"user_speaker": "TO"},
    )

    class FailingLLM:
        def __init__(self):
            self.calls = 0

        def complete_structured(self, **kwargs):  # noqa: ANN003
            del kwargs
            self.calls += 1
            raise RuntimeError("temporary extraction failure")

    context = type("Context", (), {"llm": FailingLLM()})()

    commands = detect_named_commands(context, transcript, authoritative_speaker_id="TO", names=("Ares",))

    assert commands == []
    assert context.llm.calls == 2


def test_semantic_extraction_recovers_on_the_second_attempt():
    transcript = parse_transcript_payload(
        {"conversation_id": "call_6", "turns": [{"speaker": "TO", "text": "Ares, add that event."}]},
        metadata={"user_speaker": "TO"},
    )

    class FlakyLLM:
        def __init__(self):
            self.calls = 0

        def complete_structured(self, **kwargs):  # noqa: ANN003
            del kwargs
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("temporary extraction failure")
            return type("Result", (), {"parsed": {"is_command": True, "command": "add that event."}})()

    context = type("Context", (), {"llm": FlakyLLM()})()

    commands = detect_named_commands(context, transcript, authoritative_speaker_id="TO", names=("Ares",))

    assert [command.command for command in commands] == ["add that event."]
    assert context.llm.calls == 2
