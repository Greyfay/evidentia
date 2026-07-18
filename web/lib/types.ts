export type SourceFileType = "gdpdu" | "csv" | "xlsx" | "docx" | "pdf";
export type SourceFileStatus = "parsed" | "warning" | "failed";

export interface SourceFile {
  path: string;
  type: SourceFileType;
  bytes: number;
  sha256: string;
  status: SourceFileStatus;
  source_rows: number;
  parsed_rows: number;
  warnings: string[];
}

export interface EngagementCounts {
  source_files: number;
  evidence_records: number;
  entities: number;
  events: number;
  confirmed: number;
  human_review: number;
  dismissed: number;
  rejected: number;
}

export interface Engagement {
  name: string;
  dossier_root: string;
  compiled_at: string;
  methodology_version: string;
  counts: EngagementCounts;
  source_files: SourceFile[];
}

export type SourceType =
  | "text_row"
  | "csv_row"
  | "xlsx_cell"
  | "docx_paragraph"
  | "pdf_passage"
  | "xml_node";

export interface EvidenceLocator {
  row: number | null;
  sheet: string | null;
  cell: string | null;
  page: number | null;
  passage: string | null;
}

export interface Evidence {
  evidence_id: string;
  source_path: string;
  source_type: SourceType;
  locator: EvidenceLocator;
  raw_value: string;
  file_sha256: string;
}

export interface EvidenceChainStep {
  step: string;
  evidence: Evidence[];
}

export interface CalculationInput {
  label: string;
  value: string;
  evidence_id: string;
}

export interface Calculation {
  expression: string;
  inputs: CalculationInput[];
  result: string;
  sql: string;
}

export type CounterTestOutcome = "absent" | "present" | "not_applicable";

export interface CounterTest {
  name: string;
  outcome: CounterTestOutcome;
  detail: string;
  evidence: Evidence[];
}

export type Verdict = "CONFIRMED" | "HUMAN_REVIEW" | "DISMISSED" | "REJECTED";
export type Severity = "high" | "medium" | "low" | "control";

export interface FinancialExposure {
  amount: string;
  currency: string;
  label: string;
}

export interface Case {
  case_id: string;
  title: string;
  control_id: string;
  control_version: string;
  verdict: Verdict;
  severity: Severity;
  assertion: string;
  narrative: string;
  financial_exposure: FinancialExposure;
  evidence_chain: EvidenceChainStep[];
  calculation: Calculation;
  counter_tests: CounterTest[];
  uncertainty: string | null;
  recommended_action: string;
  reviewer_decision: string | null;
}

export interface CasesDocument {
  engagement: Engagement;
  cases: Case[];
}
