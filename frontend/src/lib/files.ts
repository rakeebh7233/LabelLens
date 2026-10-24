// Collect files from a drop, walking into any dropped folders.

// Minimal typings for the File and Directory Entries API (not in TypeScript's DOM lib).
interface Entry {
  isFile: boolean;
  isDirectory: boolean;
}
interface FileEntry extends Entry {
  file(success: (file: File) => void, failure: (error: unknown) => void): void;
}
interface DirectoryEntry extends Entry {
  createReader(): { readEntries(success: (entries: Entry[]) => void, failure: (error: unknown) => void): void };
}

async function readEntry(entry: Entry): Promise<File[]> {
  if (entry.isFile) {
    return [await new Promise<File>((resolve, reject) => (entry as FileEntry).file(resolve, reject))];
  }
  if (!entry.isDirectory) return [];
  const reader = (entry as DirectoryEntry).createReader();
  const files: File[] = [];
  // readEntries returns at most ~100 entries per call; keep reading until it returns none.
  for (;;) {
    const batch = await new Promise<Entry[]>((resolve, reject) => reader.readEntries(resolve, reject));
    if (!batch.length) return files;
    for (const child of batch) files.push(...(await readEntry(child)));
  }
}

export async function filesFromDrop(data: DataTransfer): Promise<File[]> {
  const entries = Array.from(data.items ?? [])
    .map((item) => (item.webkitGetAsEntry?.() as Entry | null | undefined) ?? null)
    .filter((entry): entry is Entry => entry !== null);
  if (!entries.length) return Array.from(data.files);
  const nested = await Promise.all(entries.map(readEntry));
  return nested.flat();
}
