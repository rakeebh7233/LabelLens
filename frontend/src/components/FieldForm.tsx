import { useId, useState } from "react";
import { STANDARD_GOVERNMENT_WARNING, type ApplicationFields } from "../api/types";

export const EMPTY_FIELDS: ApplicationFields = {
  brand_name: "",
  class_type: "",
  alcohol_content: "",
  net_contents: "",
  government_warning: STANDARD_GOVERNMENT_WARNING,
};

type RequiredField = "brand_name" | "class_type" | "alcohol_content" | "net_contents";

const REQUIRED: { key: RequiredField; label: string; hint: string }[] = [
  { key: "brand_name", label: "Brand name", hint: "For example: Old Tom Distillery" },
  { key: "class_type", label: "Class / type", hint: "For example: Kentucky Straight Bourbon Whiskey" },
  { key: "alcohol_content", label: "Alcohol content", hint: "For example: 45% Alc./Vol. (90 Proof)" },
  { key: "net_contents", label: "Net contents", hint: "For example: 750 mL" },
];

/** Names of the required fields that are still blank, in form order. */
export function missingFields(fields: ApplicationFields): string[] {
  return REQUIRED.filter(({ key }) => !fields[key].trim()).map(({ label }) => label.toLowerCase());
}

interface FieldFormProps {
  fields: ApplicationFields;
  onChange: (fields: ApplicationFields) => void;
  disabled?: boolean;
}

export default function FieldForm({ fields, onChange, disabled = false }: FieldFormProps) {
  const [warningOpen, setWarningOpen] = useState(false);
  const baseId = useId();
  const warningId = `${baseId}-warning`;
  const isStandardWarning = fields.government_warning.trim() === STANDARD_GOVERNMENT_WARNING;

  function set(key: keyof ApplicationFields, value: string) {
    onChange({ ...fields, [key]: value });
  }

  return (
    <fieldset disabled={disabled}>
      <legend className="text-2xl font-bold">2. Application details</legend>
      <div className="mt-3 space-y-5">
        {REQUIRED.map(({ key, label, hint }) => {
          const id = `${baseId}-${key}`;
          return (
            <div key={key}>
              <label htmlFor={id} className="block text-lg font-semibold">
                {label}
              </label>
              <p id={`${id}-hint`} className="text-base text-slate-700">
                {hint}
              </p>
              <input
                id={id}
                type="text"
                value={fields[key]}
                onChange={(event) => set(key, event.target.value)}
                aria-describedby={`${id}-hint`}
                aria-required="true"
                autoComplete="off"
                className="mt-1 block min-h-12 w-full rounded-lg border-2 border-slate-500 bg-white px-3 py-2 text-lg focus-visible:border-blue-700 focus-visible:outline-4 focus-visible:outline-offset-1 focus-visible:outline-blue-700/40 disabled:bg-slate-100"
              />
            </div>
          );
        })}

        <div>
          <p className="text-lg font-semibold">Government warning</p>
          <p className="text-base text-slate-700">
            {isStandardWarning
              ? "Using the standard warning text. Most labels need exactly this."
              : "Using edited warning text."}
          </p>
          <button
            type="button"
            onClick={() => setWarningOpen((open) => !open)}
            aria-expanded={warningOpen}
            aria-controls={warningId}
            className="mt-2 min-h-12 rounded-lg border-2 border-slate-500 bg-white px-4 py-2 text-lg font-medium hover:bg-slate-50 focus-visible:outline-4 focus-visible:outline-offset-2 focus-visible:outline-blue-700"
          >
            {warningOpen ? "Hide warning text" : "Edit warning text"}
          </button>
          <div id={warningId} hidden={!warningOpen} className="mt-3">
            <label htmlFor={`${warningId}-text`} className="block text-lg font-semibold">
              Warning text
            </label>
            <textarea
              id={`${warningId}-text`}
              value={fields.government_warning}
              onChange={(event) => set("government_warning", event.target.value)}
              rows={6}
              className="mt-1 block w-full rounded-lg border-2 border-slate-500 bg-white px-3 py-2 text-lg focus-visible:border-blue-700 focus-visible:outline-4 focus-visible:outline-offset-1 focus-visible:outline-blue-700/40"
            />
            {!isStandardWarning && (
              <button
                type="button"
                onClick={() => set("government_warning", STANDARD_GOVERNMENT_WARNING)}
                className="mt-2 min-h-12 rounded-lg px-2 text-lg font-medium text-blue-900 underline hover:text-blue-700 focus-visible:outline-4 focus-visible:outline-blue-700"
              >
                Reset to the standard text
              </button>
            )}
          </div>
        </div>
      </div>
    </fieldset>
  );
}
