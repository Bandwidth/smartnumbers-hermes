from transcript_listener.extractor import validate_facts
from transcript_listener.parser import parse_transcript_payload


def _transcript():
    return parse_transcript_payload(
        {
            "conversation_id": "call-facts",
            "turns": [
                {"speaker": "FROM", "text": "The project meeting is Friday at three."},
                {"speaker": "TO", "text": "Yes, Friday at three works for me."},
                {"speaker": "FROM", "text": "The delivery address is 10 Main Street."},
                {"speaker": "FROM", "text": "The account owner is Alex."},
                {"speaker": "TO", "text": "I prefer meetings before lunch."},
            ],
        },
        metadata={"user_speaker": "TO"},
    )


def _fact(**overrides):
    fact = {
        "target": "memory",
        "content": "The project meeting is Friday at 3 PM.",
        "confidence": "high",
        "source": "The project meeting is Friday at three.",
        "assertion_turn_index": 0,
        "confirmation_turn_index": 1,
    }
    fact.update(overrides)
    return fact


def test_accepts_fact_stated_by_caller_and_confirmed_by_user():
    assert validate_facts([_fact()], _transcript()) == [_fact()]


def test_accepts_fact_stated_directly_by_user():
    fact = _fact(
        target="user",
        content="The user prefers meetings before lunch.",
        source="I prefer meetings before lunch.",
        assertion_turn_index=4,
        confirmation_turn_index=4,
    )

    assert validate_facts([fact], _transcript()) == [fact]


def test_rejects_unconfirmed_caller_fact():
    fact = _fact(
        content="The delivery address is 10 Main Street.",
        source="The delivery address is 10 Main Street.",
        assertion_turn_index=2,
        confirmation_turn_index=3,
    )

    assert validate_facts([fact], _transcript()) == []


def test_rejects_fabricated_turn_index_or_source_quote():
    facts = [
        _fact(assertion_turn_index=99),
        _fact(source="The delivery address is 10 Main Street."),
    ]

    assert validate_facts(facts, _transcript()) == []


def test_rejects_confirmation_before_assertion_and_mismatched_user_confirmation():
    facts = [
        _fact(assertion_turn_index=2, source="The delivery address is 10 Main Street.", confirmation_turn_index=1),
        _fact(assertion_turn_index=4, source="I prefer meetings before lunch.", confirmation_turn_index=1),
    ]

    assert validate_facts(facts, _transcript()) == []


def test_rejects_trivial_source_quote():
    assert validate_facts([_fact(source="project")], _transcript()) == []
