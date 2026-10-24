import type { ApplicationFields, LabelResult } from "./types";

// "network": the server could not be reached. "server": it answered with an error.
export type ApiErrorKind = "network" | "server";

export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  readonly status: number | null;

  constructor(kind: ApiErrorKind, message: string, status: number | null = null) {
    super(message);
    this.name = "ApiError";
    this.kind = kind;
    this.status = status;
  }
}

const NETWORK_MESSAGE =
  "Could not reach the LabelLens server. Check your connection and try again.";
const SERVER_MESSAGE = "Something went wrong on our side. Please try again.";

// The backend always answers errors with {"detail": "<plain sentence>"}; anything else
// (a proxy error page, a crash) falls back to a generic sentence.
async function errorMessage(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json();
    if (body && typeof body === "object" && "detail" in body && typeof body.detail === "string") {
      return body.detail;
    }
  } catch {
    // Not JSON.
  }
  return SERVER_MESSAGE;
}

export async function verifyLabel(
  image: File,
  fields: ApplicationFields,
  signal?: AbortSignal,
): Promise<LabelResult> {
  const form = new FormData();
  form.append("image", image);
  for (const [key, value] of Object.entries(fields)) {
    form.append(key, value);
  }

  let response: Response;
  try {
    response = await fetch("/api/verify", { method: "POST", body: form, signal });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError("network", NETWORK_MESSAGE);
  }
  if (!response.ok) {
    throw new ApiError("server", await errorMessage(response), response.status);
  }
  return (await response.json()) as LabelResult;
}
