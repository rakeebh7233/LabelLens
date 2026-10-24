import type { ApplicationFields, BatchCreated, BatchJob, LabelResult } from "./types";

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
function detailFrom(body: unknown): string {
  if (body && typeof body === "object" && "detail" in body && typeof body.detail === "string") {
    return body.detail;
  }
  return SERVER_MESSAGE;
}

async function errorMessage(response: Response): Promise<string> {
  try {
    return detailFrom(await response.json());
  } catch {
    return SERVER_MESSAGE; // Not JSON.
  }
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url, init);
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError("network", NETWORK_MESSAGE);
  }
  if (!response.ok) {
    throw new ApiError("server", await errorMessage(response), response.status);
  }
  return (await response.json()) as T;
}

export function verifyLabel(
  image: File,
  fields: ApplicationFields,
  signal?: AbortSignal,
): Promise<LabelResult> {
  const form = new FormData();
  form.append("image", image);
  for (const [key, value] of Object.entries(fields)) {
    form.append(key, value);
  }
  return request<LabelResult>("/api/verify", { method: "POST", body: form, signal });
}

/**
 * Upload photos and the manifest. Uses XMLHttpRequest rather than fetch because only XHR
 * reports upload progress, and a few hundred photos take a noticeable while to send.
 */
export function startBatch(
  images: File[],
  manifest: File,
  onUploadProgress?: (fraction: number) => void,
): Promise<BatchCreated> {
  const form = new FormData();
  for (const image of images) form.append("images", image);
  form.append("manifest", manifest);

  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/batch");
    xhr.responseType = "json";
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable && onUploadProgress) onUploadProgress(event.loaded / event.total);
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) resolve(xhr.response as BatchCreated);
      else reject(new ApiError("server", detailFrom(xhr.response), xhr.status));
    };
    xhr.onerror = () => reject(new ApiError("network", NETWORK_MESSAGE));
    xhr.send(form);
  });
}

export function getBatch(jobId: string, since = 0): Promise<BatchJob> {
  return request<BatchJob>(`/api/batch/${encodeURIComponent(jobId)}?since=${since}`);
}

export function cancelBatch(jobId: string): Promise<BatchJob> {
  return request<BatchJob>(`/api/batch/${encodeURIComponent(jobId)}`, { method: "DELETE" });
}

export function exportUrl(jobId: string): string {
  return `/api/batch/${encodeURIComponent(jobId)}/export.csv`;
}
