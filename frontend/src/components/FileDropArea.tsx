import { useState, type ReactNode } from "react";
import { filesFromDrop } from "../lib/files";

interface FileDropAreaProps {
  onFiles: (files: File[]) => void;
  disabled?: boolean;
  children: ReactNode;
}

/** A dashed drop target that accepts files and folders. The children carry the visible buttons. */
export default function FileDropArea({ onFiles, disabled = false, children }: FileDropAreaProps) {
  const [dragging, setDragging] = useState(false);

  return (
    <div
      onDragOver={(event) => {
        event.preventDefault();
        if (!disabled) setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={async (event) => {
        event.preventDefault();
        setDragging(false);
        if (disabled) return;
        onFiles(await filesFromDrop(event.dataTransfer));
      }}
      className={`mt-3 flex min-h-44 flex-col items-center justify-center gap-4 rounded-xl border-4 border-dashed p-6 text-center transition-colors ${
        dragging ? "border-blue-700 bg-blue-50" : "border-slate-400 bg-white"
      }`}
    >
      {children}
    </div>
  );
}
