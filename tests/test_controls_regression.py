"""Regression oracle: the four generic controls must find the four schemes on the sample
and clear the honest-twin decoy — using generic logic, without sample-specific constants."""

from __future__ import annotations

from audit_compiler.pipeline import compile_engagement


def test_four_schemes_confirmed_and_honest_twin_dismissed(sample_dossier):
    bundle = compile_engagement(sample_dossier, name="regression")
    counts = bundle["engagement"]["counts"]
    confirmed = {c["control_id"] for c in bundle["cases"] if c["verdict"] == "CONFIRMED"}

    # All four methodology controls produce a confirmed finding.
    assert {"vendor_sod", "split_payment", "capitalisation", "cutoff"} <= confirmed
    assert counts["confirmed"] == 4

    # The honest-twin vendor (independent approval + real deliveries) is dismissed, not accused.
    dismissed = [c for c in bundle["cases"] if c["verdict"] == "DISMISSED"]
    assert dismissed, "the honest-twin decoy must be dismissed"
    twin = dismissed[0]
    cleared = [c for c in twin["counter_tests"] if c["outcome"] == "present"]
    assert cleared, "a dismissed case must record the counter-test that cleared it"

    # Precision guardrail: no confirmed case may exist without a cited calculation.
    for case in bundle["cases"]:
        if case["verdict"] in {"CONFIRMED", "HUMAN_REVIEW"}:
            assert case["evidence_chain"], "published case must carry an evidence chain"
            assert case["calculation"]["inputs"], "published exposure must be cited"


def test_every_published_number_resolves_to_evidence(sample_dossier):
    bundle = compile_engagement(sample_dossier, name="regression")
    for case in bundle["cases"]:
        available = {e["evidence_id"] for step in case["evidence_chain"] for e in step["evidence"]}
        available |= {e["evidence_id"] for e in case["calculation"]["evidence"]}
        for calc_input in case["calculation"]["inputs"]:
            assert calc_input["evidence_id"] in available, "a cited number lacks its evidence"
