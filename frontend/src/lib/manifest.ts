// Client-side reading of the batch manifest, used only to warn about mismatches before upload.
// The server re-parses and stays the authority; the header rules mirror
// backend/app/services/manifest.py so both sides agree on what a column is called.

export const REQUIRED_COLUMNS = ["filename", "brand_name", "class_type", "alcohol_content", "net_contents"];

const HEADER_ALIASES: Record<string, string> = {
  file_name: "filename",
  file: "filename",
  image: "filename",
  photo: "filename",
  brand: "brand_name",
  class: "class_type",
  type: "class_type",
  alcohol: "alcohol_content",
  abv: "alcohol_content",
  net_content: "net_contents",
  volume: "net_contents",
  warning: "government_warning",
};

export const TEMPLATE_CSV =
  "filename,brand_name,class_type,alcohol_content,net_contents,government_warning\r\n" +
  'old_tom.png,OLD TOM DISTILLERY,Kentucky Straight Bourbon Whiskey,45% Alc./Vol. (90 Proof),750 mL,\r\n';

export class ManifestProblem extends Error {}

/** "Brand Name", "brand-name", "BRAND_NAME" and "Brand" all mean brand_name. */
export function headerKey(header: string): string {
  const key = header.trim().toLowerCase().replace(/[-/]/g, " ").split(/\s+/).filter(Boolean).join("_");
  return HEADER_ALIASES[key] ?? key;
}

/** Strip any folder path, so "labels/01.png" and "labels\\01.png" match "01.png". */
export function baseName(filename: string): string {
  const parts = filename.replace(/\\/g, "/").split("/");
  return (parts[parts.length - 1] ?? "").trim();
}

export function matchKey(filename: string): string {
  return baseName(filename).toLowerCase();
}

function detectDelimiter(firstLine: string): string {
  const counts = [",", ";", "\t"].map((d) => [d, firstLine.split(d).length] as const);
  return counts.reduce((best, next) => (next[1] > best[1] ? next : best))[0];
}

/** RFC 4180 CSV: quoted cells may hold delimiters, newlines and doubled quotes. */
export function parseCsv(text: string, delimiter = ","): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let quoted = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (quoted) {
      if (ch === '"' && text[i + 1] === '"') {
        cell += '"';
        i++;
      } else if (ch === '"') {
        quoted = false;
      } else {
        cell += ch;
      }
    } else if (ch === '"') {
      quoted = true;
    } else if (ch === delimiter) {
      row.push(cell);
      cell = "";
    } else if (ch === "\n" || ch === "\r") {
      if (ch === "\r" && text[i + 1] === "\n") i++;
      row.push(cell);
      rows.push(row);
      row = [];
      cell = "";
    } else {
      cell += ch;
    }
  }
  if (cell || row.length) {
    row.push(cell);
    rows.push(row);
  }
  return rows;
}

function quoteCell(value: string): string {
  return /[",\r\n]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value;
}

export function toCsv(rows: string[][]): string {
  return rows.map((row) => row.map(quoteCell).join(",")).join("\r\n") + "\r\n";
}

export interface Manifest {
  header: string[];
  // Data rows (blank lines dropped), each with its file name already pulled out.
  rows: { filename: string; brand: string; cells: string[] }[];
}

function joinWords(words: string[]): string {
  return words.length === 1 ? words[0] : `${words.slice(0, -1).join(", ")} and ${words[words.length - 1]}`;
}

export function readManifest(text: string): Manifest {
  const clean = text.replace(/^﻿/, "");
  if (!clean.trim()) throw new ManifestProblem("The spreadsheet is empty.");
  const [header, ...body] = parseCsv(clean, detectDelimiter(clean.split(/\r?\n/)[0]));
  const keys = header.map(headerKey);
  const missing = REQUIRED_COLUMNS.filter((column) => !keys.includes(column));
  if (missing.length) {
    throw new ManifestProblem(
      `The spreadsheet is missing ${missing.length === 1 ? "this column" : "these columns"}: ` +
        `${joinWords(missing)}. The first row must name the columns ${REQUIRED_COLUMNS.join(", ")} ` +
        "(government_warning is optional).",
    );
  }
  const fileCol = keys.indexOf("filename");
  const brandCol = keys.indexOf("brand_name");
  const rows = body
    .filter((cells) => cells.some((cell) => cell.trim()))
    .map((cells) => ({ filename: baseName(cells[fileCol] ?? ""), brand: (cells[brandCol] ?? "").trim(), cells }));
  if (!rows.length) throw new ManifestProblem("The spreadsheet has no rows after the column names.");
  return { header, rows };
}

export interface Pairing {
  matched: File[];
  photosWithoutRow: string[];
  rowsWithoutPhoto: string[];
  // Manifest rebuilt with only the matched rows, for "continue with the matches".
  matchedManifest: string;
}

/** Pair photos with rows by file name, ignoring folders and letter case (as the server does). */
export function pairPhotos(photos: File[], manifest: Manifest): Pairing {
  const rowKeys = new Set(manifest.rows.map((row) => matchKey(row.filename)).filter(Boolean));
  const photoKeys = new Set(photos.map((photo) => matchKey(photo.name)));
  const matched = photos.filter((photo) => rowKeys.has(matchKey(photo.name)));
  return {
    matched,
    photosWithoutRow: photos.filter((photo) => !rowKeys.has(matchKey(photo.name))).map((photo) => photo.name),
    rowsWithoutPhoto: manifest.rows
      .filter((row) => !photoKeys.has(matchKey(row.filename)))
      .map((row) => row.filename || "(row with no file name)"),
    matchedManifest: toCsv([
      manifest.header,
      ...manifest.rows.filter((row) => photoKeys.has(matchKey(row.filename))).map((row) => row.cells),
    ]),
  };
}
