#!/usr/bin/env node
// Skillspector CLI wrapper — adapts the browser/offline Skill Scanner engine to the
// JSON-on-stdout contract expected by deepagent_skill_guardrails.SubprocessSkillScanner.
//
// Usage:
//   node scripts/scan_skill.mjs [--engine <path-to-engine.js>] [--pretty] <skill-dir>
//
// Engine resolution order:
//   1. --engine argument
//   2. SKILLSPECTOR_ENGINE environment variable
//   3. <repo>/references/Skill Scanner/src/engine.js   (relative to this script)
//   4. /Users/spider/Code/REPOS/Skill Scanner/src/engine.js
//
// Output: a single JSON object on stdout with top-level `findings` (normalized keys:
// rule_id, severity, category, message, location, excerpt) plus `score`, `grade`,
// `summary`, `capabilities`, and the raw per-skill reports under `skills`.
//
// Exit codes: 0 = scan ok, no critical/high findings; 1 = critical/high present
// (both are treated as success by SubprocessSkillScanner); 2 = execution error.
//
// Requires node >= 18. Symlinks are not followed (hostile-input safety). Single files
// larger than 30 MB are skipped with a warning on stderr.

import { readdir, readFile, realpath, stat } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { pathToFileURL } from "node:url";

const MAX_FILE_BYTES = 30 * 1024 * 1024;
const GRADE_RANK = { A: 4, B: 3, C: 2, D: 1, F: 0 };

function fail(message) {
  process.stderr.write(`scan_skill: ${message}\n`);
  process.exit(2);
}

function parseArgs(argv) {
  const args = { engine: null, pretty: false, target: null };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--engine") args.engine = argv[++i];
    else if (a === "--pretty") args.pretty = true;
    else if (a === "--help" || a === "-h") {
      process.stdout.write(
        "usage: node scan_skill.mjs [--engine <engine.js>] [--pretty] <skill-dir>\n"
      );
      process.exit(0);
    } else if (!args.target) args.target = a;
    else fail(`unexpected argument: ${a}`);
  }
  if (!args.target) fail("missing <skill-dir> argument");
  return args;
}

async function resolveEngine(cliPath) {
  const here = path.dirname(new URL(import.meta.url).pathname);
  const candidates = [
    cliPath,
    process.env.SKILLSPECTOR_ENGINE,
    path.join(here, "..", "references", "Skill Scanner", "src", "engine.js"),
    "/Users/spider/Code/REPOS/Skill Scanner/src/engine.js",
  ].filter(Boolean);
  for (const candidate of candidates) {
    try {
      const st = await stat(candidate);
      if (st.isFile()) return path.resolve(candidate);
    } catch {
      /* keep looking */
    }
  }
  fail(
    "Skillspector engine.js not found. Pass --engine or set SKILLSPECTOR_ENGINE.\n" +
      `  tried:\n  ${candidates.join("\n  ")}`
  );
}

// Recursive walk producing FileEntry[] { path, bytes } with posix paths rooted at the
// skill directory's basename (so the engine can verify name-matches-directory rules).
async function collectFiles(rootDir) {
  const rootName = path.basename(rootDir);
  const entries = [];

  async function walk(dir, rel) {
    let dirents;
    try {
      dirents = await readdir(dir, { withFileTypes: true });
    } catch (err) {
      process.stderr.write(`scan_skill: warning: cannot read ${dir}: ${err.message}\n`);
      return;
    }
    for (const dirent of dirents.sort((a, b) => a.name.localeCompare(b.name))) {
      const abs = path.join(dir, dirent.name);
      const relPath = rel ? `${rel}/${dirent.name}` : dirent.name;
      if (dirent.isSymbolicLink()) {
        process.stderr.write(`scan_skill: warning: skipping symlink ${relPath}\n`);
        continue;
      }
      if (dirent.isDirectory()) {
        await walk(abs, relPath);
      } else if (dirent.isFile()) {
        try {
          const st = await stat(abs);
          if (st.size > MAX_FILE_BYTES) {
            process.stderr.write(
              `scan_skill: warning: skipping ${relPath} (${st.size} bytes > ${MAX_FILE_BYTES})\n`
            );
            continue;
          }
          const buf = await readFile(abs);
          entries.push({
            path: `${rootName}/${relPath}`,
            bytes: new Uint8Array(buf.buffer, buf.byteOffset, buf.byteLength),
          });
        } catch (err) {
          process.stderr.write(`scan_skill: warning: cannot read ${relPath}: ${err.message}\n`);
        }
      }
    }
  }

  await walk(rootDir, "");
  return entries;
}

function normalizeFinding(f) {
  const message = f.detail ? `${f.title} — ${f.detail}` : f.title;
  return {
    rule_id: f.ruleId,
    severity: f.severity,
    category: f.category,
    message,
    location: f.line != null ? `${f.file}:${f.line}` : f.file || null,
    excerpt: f.excerpt ?? null,
  };
}

// One skill dir can technically contain nested skill roots; a malicious nested skill
// still counts against the bundle being admitted, so merge: concat findings, take the
// minimum score and the worst grade, sum severity counts, merge capabilities by id.
function mergeReports(reports) {
  if (reports.length === 1) return { ...reports[0] };
  const merged = {
    name: reports.map((r) => r.name).join(" + "),
    score: Math.min(...reports.map((r) => r.score)),
    grade: reports.reduce(
      (worst, r) => ((GRADE_RANK[r.grade] ?? 0) < (GRADE_RANK[worst] ?? 0) ? r.grade : worst),
      "A"
    ),
    summary: { critical: 0, high: 0, medium: 0, low: 0, info: 0 },
    findings: [],
    capabilities: [],
  };
  const caps = new Map();
  for (const r of reports) {
    for (const key of Object.keys(merged.summary)) merged.summary[key] += r.summary[key] ?? 0;
    merged.findings.push(...r.findings);
    for (const cap of r.capabilities ?? []) {
      const existing = caps.get(cap.id);
      if (existing) existing.evidence.push(...(cap.evidence ?? []));
      else caps.set(cap.id, { ...cap, evidence: [...(cap.evidence ?? [])] });
    }
  }
  merged.capabilities = [...caps.values()];
  return merged;
}

async function main() {
  const args = parseArgs(process.argv.slice(2));

  let targetDir;
  try {
    targetDir = await realpath(args.target);
    const st = await stat(targetDir);
    if (!st.isDirectory()) fail(`not a directory: ${args.target}`);
  } catch (err) {
    fail(`cannot access ${args.target}: ${err.message}`);
  }

  const enginePath = await resolveEngine(args.engine);
  let engine;
  try {
    const mod = await import(pathToFileURL(enginePath).href);
    engine = mod.scanFiles ? mod : globalThis.SkillScanner;
  } catch (err) {
    fail(`cannot load engine ${enginePath}: ${err.message}`);
  }
  if (!engine || typeof engine.scanFiles !== "function") {
    fail(`engine at ${enginePath} does not expose scanFiles()`);
  }

  const entries = await collectFiles(targetDir);
  if (entries.length === 0) fail(`no files found under ${targetDir}`);

  let result;
  try {
    result = await engine.scanFiles(entries);
  } catch (err) {
    fail(`engine scan failed: ${err.message}`);
  }

  const merged = mergeReports(result.skills ?? []);
  const findings = (merged.findings ?? []).map(normalizeFinding);

  const output = {
    scanner: "skillspector",
    engine_version: result.version,
    engine_path: enginePath,
    scanned_at: result.scannedAt,
    target: targetDir,
    skill_count: (result.skills ?? []).length,
    name: merged.name,
    score: merged.score,
    grade: merged.grade,
    summary: merged.summary,
    capabilities: (merged.capabilities ?? []).map(({ id, label, evidence }) => ({
      id,
      label,
      evidence,
    })),
    findings,
    skills: result.skills,
  };

  process.stdout.write(JSON.stringify(output, null, args.pretty ? 2 : 0) + "\n");
  const hasBlocker = findings.some((f) => f.severity === "critical" || f.severity === "high");
  process.exit(hasBlocker ? 1 : 0);
}

main().catch((err) => fail(err.stack || String(err)));
