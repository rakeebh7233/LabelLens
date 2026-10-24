// Mirrors backend/app/schemas.py. Keep the two in step.

export type Status = "pass" | "review" | "fail";

export type FieldName =
  | "brand_name"
  | "class_type"
  | "alcohol_content"
  | "net_contents"
  | "government_warning";

export interface FieldResult {
  field: FieldName;
  status: Status;
  expected: string;
  // null means the value was not found on the label at all.
  found: string | null;
  reason: string | null;
  ocr_confidence: number;
}

export interface LabelResult {
  label_id: string;
  filename: string | null;
  fields: FieldResult[];
  timings_ms: Record<string, number>;
  preprocessing: string[];
  ocr_confidence: number | null;
  warnings: string[];
  // Set when the label could not be processed at all (e.g. unreadable image).
  error: string | null;
  overall_status: Status;
}

export interface ApplicationFields {
  brand_name: string;
  class_type: string;
  alcohol_content: string;
  net_contents: string;
  government_warning: string;
}

export const STANDARD_GOVERNMENT_WARNING =
  "GOVERNMENT WARNING: (1) According to the Surgeon General, women should not drink alcoholic " +
  "beverages during pregnancy because of the risk of birth defects. (2) Consumption of " +
  "alcoholic beverages impairs your ability to drive a car or operate machinery, and may " +
  "cause health problems.";

export const FIELD_LABELS: Record<FieldName, string> = {
  brand_name: "Brand name",
  class_type: "Class / type",
  alcohol_content: "Alcohol content",
  net_contents: "Net contents",
  government_warning: "Government warning",
};
