import { useEffect, useId, useRef, useState, type DragEvent } from "react";

const ACCEPTED_EXTENSIONS = [".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"];
const ACCEPT_ATTR = ACCEPTED_EXTENSIONS.join(",") + ",image/jpeg,image/png,image/webp,image/tiff";

export function isSupportedImage(file: File): boolean {
  const name = file.name.toLowerCase();
  return ACCEPTED_EXTENSIONS.some((ext) => name.endsWith(ext));
}

interface DropZoneProps {
  file: File | null;
  onFileChange: (file: File | null) => void;
  disabled?: boolean;
}

export default function DropZone({ file, onFileChange, disabled = false }: DropZoneProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [previewFailed, setPreviewFailed] = useState(false);
  const hintId = useId();

  useEffect(() => {
    setPreviewFailed(false);
    if (!file) {
      setPreviewUrl(null);
      return;
    }
    const url = URL.createObjectURL(file);
    setPreviewUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  function accept(candidate: File | undefined) {
    if (!candidate) return;
    if (!isSupportedImage(candidate)) {
      setProblem(`${candidate.name} is not a supported photo type. Please use JPEG, PNG, WebP or TIFF.`);
      return;
    }
    setProblem(null);
    onFileChange(candidate);
  }

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    if (disabled) return;
    accept(event.dataTransfer.files[0]);
  }

  function openPicker() {
    inputRef.current?.click();
  }

  return (
    <div>
      <h2 className="text-2xl font-bold">1. Label photo</h2>
      <div
        onDragOver={(event) => {
          event.preventDefault();
          if (!disabled) setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
        className={`mt-3 flex min-h-72 flex-col items-center justify-center gap-4 rounded-xl border-4 border-dashed p-6 text-center transition-colors ${
          dragging ? "border-blue-700 bg-blue-50" : "border-slate-400 bg-white"
        }`}
      >
        {file ? (
          <>
            {previewUrl && !previewFailed ? (
              <img
                src={previewUrl}
                alt={`Preview of ${file.name}`}
                onError={() => setPreviewFailed(true)}
                className="max-h-80 w-auto max-w-full rounded-lg object-contain shadow"
              />
            ) : (
              <p className="text-lg text-slate-700">This browser cannot preview this photo, but it can still be checked.</p>
            )}
            <p className="break-all text-lg font-medium">{file.name}</p>
          </>
        ) : (
          <>
            <svg
              className="h-14 w-14 text-slate-500"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth={1.8}
              aria-hidden="true"
            >
              <rect x="3" y="4" width="18" height="16" rx="2" />
              <circle cx="9" cy="10" r="2" />
              <path d="m21 16-5-5-9 9" />
            </svg>
            <p className="text-xl">Drag a photo of the label here</p>
            <p className="text-lg text-slate-700">or</p>
          </>
        )}
        <button
          type="button"
          onClick={openPicker}
          disabled={disabled}
          aria-describedby={hintId}
          className="min-h-12 rounded-lg border-2 border-blue-800 bg-white px-6 py-2 text-lg font-semibold text-blue-900 hover:bg-blue-50 focus-visible:outline-4 focus-visible:outline-offset-2 focus-visible:outline-blue-700 disabled:opacity-50"
        >
          {file ? "Choose a different file" : "Choose a file"}
        </button>
        <p id={hintId} className="text-base text-slate-700">
          JPEG, PNG, WebP or TIFF
        </p>
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPT_ATTR}
          className="sr-only"
          tabIndex={-1}
          aria-hidden="true"
          data-testid="file-input"
          onChange={(event) => {
            accept(event.target.files?.[0]);
            // Allow choosing the same file again after an error.
            event.target.value = "";
          }}
        />
      </div>
      {problem && (
        <p role="alert" className="mt-3 text-lg font-medium text-red-800">
          {problem}
        </p>
      )}
    </div>
  );
}
