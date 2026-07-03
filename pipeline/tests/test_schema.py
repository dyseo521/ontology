from ontoquant.core.schema import get_schema


def test_schema_loads():
    schema = get_schema()
    assert len(schema.objectTypes) >= 13
    assert len(schema.linkTypes) >= 14
    assert "Event" in schema.interfaces
    assert "ProposedAction" in schema.interfaces


def test_event_interface_injection():
    schema = get_schema()
    for impl in schema.interfaces["Event"].implementedBy:
        ot = schema.objectTypes[impl]
        for shared in ("eventId", "eventType", "occurredAt", "title", "severity"):
            assert shared in ot.properties, f"{impl}에 {shared} 미주입"
        assert ot.primaryKey == "eventId"


def test_resolve_types():
    schema = get_schema()
    types = schema.resolve_types("Event")
    assert "DisclosureEvent" in types and "MacroEvent" in types
    assert schema.resolve_types("Instrument") == ["Instrument"]


def test_action_types_loaded():
    schema = get_schema()
    for name in ("editPosition", "proposeRebalance", "approveProposal",
                 "setRiskLimit", "promoteModel", "editInsightNarrative"):
        assert name in schema.actionTypes
    ap = schema.actionTypes["approveProposal"]
    assert ap.submissionCriteria and ap.rules
    assert any(r.type == "functionRule" for r in ap.rules)


def test_ownership_declared():
    schema = get_schema()
    pos = schema.objectTypes["Position"]
    assert pos.properties["quantity"].owner == "USER"
    assert pos.properties["weight"].owner == "PIPELINE"
