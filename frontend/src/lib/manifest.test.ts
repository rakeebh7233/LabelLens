import { ManifestProblem, headerKey, pairPhotos, parseCsv, readManifest } from "./manifest";

const HEADER = "filename,brand_name,class_type,alcohol_content,net_contents,government_warning";
const photo = (name: string) => new File(["x"], name, { type: "image/png" });

test("parseCsv handles quoted delimiters, doubled quotes, newlines and CRLF", () => {
  expect(parseCsv('a,"b, c","say ""hi"""\r\n"multi\nline",x,\n')).toEqual([
    ["a", "b, c", 'say "hi"'],
    ["multi\nline", "x", ""],
  ]);
});

test("headerKey mirrors the server's friendly column names", () => {
  expect(headerKey("File Name")).toBe("filename");
  expect(headerKey("BRAND-NAME")).toBe("brand_name");
  expect(headerKey(" ABV ")).toBe("alcohol_content");
  expect(headerKey("Class/Type")).toBe("class_type");
});

test("readManifest strips the BOM, detects semicolons and drops blank lines", () => {
  const text = "﻿File;Brand;Class;ABV;Volume\r\nlabels/01.png;Old Tom;Bourbon;45%;750 mL\r\n;;;;\r\n";
  const manifest = readManifest(text);
  expect(manifest.rows).toHaveLength(1);
  expect(manifest.rows[0]).toMatchObject({ filename: "01.png", brand: "Old Tom" });
});

test("readManifest names missing columns", () => {
  expect(() => readManifest("filename,brand_name\na.png,X\n")).toThrow(ManifestProblem);
  expect(() => readManifest("filename,brand_name\na.png,X\n")).toThrow(
    /missing these columns: class_type, alcohol_content and net_contents/,
  );
  expect(() => readManifest(`${HEADER}\n`)).toThrow(/no rows/);
  expect(() => readManifest("  ")).toThrow(/empty/);
});

test("pairPhotos matches by file name ignoring case and lists both kinds of mismatch", () => {
  const manifest = readManifest(
    `${HEADER}\nA.png,Old Tom,Bourbon,45%,750 mL,\nb.png,"Stone's Throw, Inc",Gin,40%,1 L,\nc.png,X,Y,1%,1 L,\n`,
  );
  const pairing = pairPhotos([photo("a.PNG"), photo("b.png"), photo("extra.png")], manifest);
  expect(pairing.matched.map((f) => f.name)).toEqual(["a.PNG", "b.png"]);
  expect(pairing.photosWithoutRow).toEqual(["extra.png"]);
  expect(pairing.rowsWithoutPhoto).toEqual(["c.png"]);

  const rebuilt = readManifest(pairing.matchedManifest);
  expect(rebuilt.rows.map((row) => row.filename)).toEqual(["A.png", "b.png"]);
  expect(rebuilt.rows[1].brand).toBe("Stone's Throw, Inc");
});
