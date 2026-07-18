# `cases.json` contract

The pipeline emits a single `cases.json` describing one compiled engagement. The UI
renders it read-only. Every displayed number must resolve to an `evidence_id` present in
the same document. Amounts are JSON **strings** (exact decimals, never floats).

```jsonc
{
  "engagement": {
    "name": "string",
    "dossier_root": "string",
    "compiled_at": "ISO-8601",
    "methodology_version": "string",
    "counts": {
      "source_files": 0, "evidence_records": 0, "entities": 0, "events": 0,
      "confirmed": 0, "human_review": 0, "dismissed": 0, "rejected": 0
    },
    "source_files": [
      { "path": "string", "type": "gdpdu|csv|xlsx|docx|pdf",
        "bytes": 0, "sha256": "hex", "status": "parsed|warning|failed",
        "source_rows": 0, "parsed_rows": 0, "warnings": ["string"] }
    ]
  },
  "cases": [
    {
      "case_id": "uuid",
      "title": "string",
      "control_id": "string",
      "control_version": "string",
      "verdict": "CONFIRMED|HUMAN_REVIEW|DISMISSED|REJECTED",
      "severity": "high|medium|low|control",
      "assertion": "string",                     // audit assertion tested
      "narrative": "string",                      // plain-language allegation
      "financial_exposure": { "amount": "0.00", "currency": "EUR", "label": "net|gross|control" },
      "evidence_chain": [
        { "step": "string",
          "evidence": [ { "evidence_id": "uuid", "source_path": "string",
            "source_type": "text_row|csv_row|xlsx_cell|docx_paragraph|pdf_passage|xml_node",
            "locator": { "row": null, "sheet": null, "cell": null, "page": null, "passage": null },
            "raw_value": "string", "file_sha256": "hex" } ] }
      ],
      "calculation": {
        "expression": "45000 + 60000",           // human-readable
        "inputs": [ { "label": "string", "value": "0.00", "evidence_id": "uuid" } ],
        "result": "0.00",
        "sql": "string"                           // the deterministic query that produced it
      },
      "counter_tests": [
        { "name": "string", "outcome": "absent|present|not_applicable",
          "detail": "string", "evidence": [ /* evidence objects */ ] }
      ],
      "uncertainty": "string|null",
      "recommended_action": "string",
      "reviewer_decision": null                   // set by human review; null when unreviewed
    }
  ]
}
```

## Invariants (enforced by the admission gate, not the UI)

- A published (`CONFIRMED`/`HUMAN_REVIEW`) case has ≥1 `evidence_chain` step, ≥1 control
  result, and all required `counter_tests` run.
- A `DISMISSED` case carries the counter-test whose `outcome: "present"` cleared it.
- No number in `financial_exposure`/`calculation`/`narrative` may lack a resolving `evidence_id`.
