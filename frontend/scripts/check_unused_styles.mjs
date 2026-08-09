/**
 * P3-2: unused-CSS-class audit (round11-code-redundancy.md §8.2).
 *
 * Collects class selectors from src/styles/theme.css + global.css and checks
 * them against class references in src (all .vue/.js files). A frozen baseline
 * records the current unused stock; --check fails only when NEW unused
 * classes appear (dead styles must not grow).
 *
 * Reference matching is conservative (string tokens only) to avoid false
 * positives: a class counts as "used" if any string literal in source equals
 * it, or it appears inside a class= / :class= attribute.
 *
 * Usage:
 *   node scripts/check_unused_styles.mjs --baseline   # (re)generate baseline
 *   node scripts/check_unused_styles.mjs              # --check mode (gate)
 *   node scripts/check_unused_styles.mjs --print      # dump unused list
 */
import { readFileSync, readdirSync, statSync, writeFileSync, existsSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const STYLE_FILES = [join(ROOT, 'src/styles/theme.css'), join(ROOT, 'src/styles/global.css')]
const SRC_DIR = join(ROOT, 'src')
const BASELINE_FILE = join(ROOT, 'scripts/.unused_styles.baseline.json')

const CLASS_RE = /\.([a-zA-Z_][a-zA-Z0-9_-]*)/g

function walk(dir) {
  const out = []
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    if (statSync(p).isDirectory()) {
      if (name === 'node_modules' || name === 'dist' || name === 'test') continue
      out.push(...walk(p))
    } else if (/\.(vue|js)$/.test(name)) {
      out.push(p)
    }
  }
  return out
}

function collectCssClasses() {
  const classes = new Set()
  for (const f of STYLE_FILES) {
    if (!existsSync(f)) continue
    const css = readFileSync(f, 'utf8')
    for (const m of css.matchAll(CLASS_RE)) {
      // 跳过 CSS 变量类前缀（--foo）与数字开头
      if (/^\d/.test(m[1])) continue
      classes.add(m[1])
    }
  }
  return classes
}

function collectUsedClasses() {
  const used = new Set()
  const files = walk(SRC_DIR)
  for (const f of files) {
    const src = readFileSync(f, 'utf8')
    // class= / :class= attribute contents
    for (const m of src.matchAll(/(?:class|className)\s*=\s*["'`]([^"'`]*)["'`]/g)) {
      for (const tok of m[1].split(/\s+/)) {
        if (/^[a-zA-Z_][a-zA-Z0-9_-]*$/.test(tok)) used.add(tok)
      }
    }
    // string literals (covers :class="{ active: ... }" and ternaries)
    for (const m of src.matchAll(/['"`]([a-zA-Z_][a-zA-Z0-9_-]*)['"`]/g)) {
      used.add(m[1])
    }
  }
  return used
}

function scan() {
  const classes = collectCssClasses()
  const used = collectUsedClasses()
  const unused = [...classes].filter((c) => !used.has(c)).sort()
  return unused
}

function main() {
  const mode = process.argv.includes('--baseline') ? 'baseline'
    : process.argv.includes('--print') ? 'print' : 'check'
  const unused = scan()

  if (mode === 'print') {
    console.log(JSON.stringify(unused, null, 2))
    return 0
  }
  if (mode === 'baseline') {
    writeFileSync(BASELINE_FILE, JSON.stringify(unused, null, 2), 'utf8')
    console.log(`[P3-2] baseline written: ${unused.length} unused classes -> ${BASELINE_FILE}`)
    return 0
  }
  if (!existsSync(BASELINE_FILE)) {
    console.error('[P3-2] no baseline; run --baseline first')
    return 1
  }
  const baseline = new Set(JSON.parse(readFileSync(BASELINE_FILE, 'utf8')))
  const fresh = unused.filter((c) => !baseline.has(c))
  if (fresh.length) {
    console.log(`[P3-2] FAIL: ${fresh.length} NEW unused class(es) (stock ${unused.length})`)
    console.log(fresh.slice(0, 20).join('\n  '))
    console.log('  Remove dead styles or add real usage; purge baseline after cleanup.')
    return 1
  }
  console.log(`[P3-2] OK: unused stock ${unused.length} (no growth vs baseline)`)
  return 0
}

process.exit(main())
