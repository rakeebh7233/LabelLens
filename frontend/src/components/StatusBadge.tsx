import type { Status } from "../api/types";

// Status is always shown as icon + word, never color alone.
export const STATUS_TEXT: Record<Status, string> = {
  pass: "Pass",
  review: "Needs review",
  fail: "Fail",
};

export const STATUS_STYLES: Record<Status, { badge: string; border: string; panel: string; icon: string }> = {
  pass: {
    badge: "bg-green-100 text-green-900 ring-green-700",
    border: "border-green-700",
    panel: "border-green-700 bg-green-50 text-green-950",
    icon: "text-green-800",
  },
  review: {
    badge: "bg-amber-100 text-amber-950 ring-amber-700",
    border: "border-amber-600",
    panel: "border-amber-600 bg-amber-50 text-amber-950",
    icon: "text-amber-800",
  },
  fail: {
    badge: "bg-red-100 text-red-900 ring-red-700",
    border: "border-red-700",
    panel: "border-red-700 bg-red-50 text-red-950",
    icon: "text-red-800",
  },
};

export function StatusIcon({ status, className = "h-6 w-6" }: { status: Status; className?: string }) {
  const common = {
    className: `${className} shrink-0 ${STATUS_STYLES[status].icon}`,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 2.5,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    "aria-hidden": true,
  };
  if (status === "pass") {
    return (
      <svg {...common}>
        <circle cx="12" cy="12" r="10" />
        <path d="m7.5 12.5 3 3 6-6.5" />
      </svg>
    );
  }
  if (status === "review") {
    return (
      <svg {...common}>
        <path d="M12 3 2 20h20L12 3Z" />
        <path d="M12 10v4" />
        <path d="M12 17.5h.01" />
      </svg>
    );
  }
  return (
    <svg {...common}>
      <circle cx="12" cy="12" r="10" />
      <path d="m8.5 8.5 7 7m0-7-7 7" />
    </svg>
  );
}

export default function StatusBadge({ status }: { status: Status }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-base font-semibold ring-1 ${STATUS_STYLES[status].badge}`}
    >
      <StatusIcon status={status} className="h-5 w-5" />
      {STATUS_TEXT[status]}
    </span>
  );
}
