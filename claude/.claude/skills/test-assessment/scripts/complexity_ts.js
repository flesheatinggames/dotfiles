#!/usr/bin/env node
/**
 * Exact cyclomatic complexity for TypeScript and JavaScript, via a real parse.
 *
 * Uses the TypeScript compiler's own parser, resolved from the TARGET repository's
 * node_modules. Nothing is installed. If the target repository has no `typescript`
 * dependency installed, this exits with code 3 and the caller falls back to the token
 * scanner in complexity.py, which is an estimate and is labelled as one.
 *
 * Why this exists: the token scanner it replaces could not parse TypeScript. It invented
 * functions from `const x = ...` statements in semicolon-free source by scanning past the
 * end of a statement for an unrelated `=>`, and it folded expression-bodied arrow
 * functions into their enclosing function so the counts came out roughly three times
 * lower than Istanbul's. A parser has neither problem.
 *
 * Input : newline-separated file paths on stdin, relative to --repo.
 * Output: JSON on stdout, same schema as complexity.py, with basis "exact".
 *
 * Usage:
 *   find . -name '*.ts' | node complexity_ts.js --repo /path/to/repo
 */

'use strict'

const fs = require('fs')
const path = require('path')

function arg(name, fallback) {
  const i = process.argv.indexOf(name)
  return i !== -1 && process.argv[i + 1] ? process.argv[i + 1] : fallback
}

const repo = path.resolve(arg('--repo', process.cwd()))

let ts
try {
  ts = require(require.resolve('typescript', { paths: [repo, __dirname, process.cwd()] }))
} catch (err) {
  process.stderr.write(
    'typescript not resolvable from ' + repo + '; caller should fall back to the token scanner\n'
  )
  process.exit(3)
}

// ---------------------------------------------------------------- node classification

function isFunctionLike(node) {
  return (
    ts.isFunctionDeclaration(node) ||
    ts.isFunctionExpression(node) ||
    ts.isArrowFunction(node) ||
    ts.isMethodDeclaration(node) ||
    ts.isConstructorDeclaration(node) ||
    ts.isGetAccessorDeclaration(node) ||
    ts.isSetAccessorDeclaration(node)
  )
}

/** Each of these introduces one independent path through the enclosing function. */
function decisionCount(node) {
  if (
    ts.isIfStatement(node) ||
    ts.isConditionalExpression(node) ||
    ts.isForStatement(node) ||
    ts.isForInStatement(node) ||
    ts.isForOfStatement(node) ||
    ts.isWhileStatement(node) ||
    ts.isDoStatement(node) ||
    ts.isCatchClause(node)
  ) {
    return 1
  }
  // `case` adds a path; `default` does not, it is the fall-through.
  if (ts.isCaseClause(node)) return 1
  if (ts.isBinaryExpression(node)) {
    const k = node.operatorToken.kind
    if (
      k === ts.SyntaxKind.AmpersandAmpersandToken ||
      k === ts.SyntaxKind.BarBarToken ||
      k === ts.SyntaxKind.QuestionQuestionToken
    ) {
      return 1
    }
  }
  return 0
}

/** Best available human-readable name for a function-like node. */
function nameOf(node) {
  if (node.name && ts.isIdentifier(node.name)) return node.name.text
  if (ts.isConstructorDeclaration(node)) return 'constructor'

  const p = node.parent
  if (p) {
    if (ts.isVariableDeclaration(p) && ts.isIdentifier(p.name)) return p.name.text
    if (ts.isPropertyAssignment(p) && p.name && ts.isIdentifier(p.name)) return p.name.text
    if (ts.isPropertyDeclaration(p) && p.name && ts.isIdentifier(p.name)) return p.name.text
    if (ts.isExportAssignment(p)) return 'default'
    // A callback: name it for the call it is passed to, e.g. useCallback / map.
    if (ts.isCallExpression(p)) {
      const callee = p.expression
      if (ts.isIdentifier(callee)) return '<arg of ' + callee.text + '>'
      if (ts.isPropertyAccessExpression(callee) && ts.isIdentifier(callee.name)) {
        return '<arg of .' + callee.name.text + '>'
      }
    }
  }
  return '<anonymous>'
}

function scriptKind(file) {
  if (file.endsWith('.tsx')) return ts.ScriptKind.TSX
  if (file.endsWith('.jsx')) return ts.ScriptKind.JSX
  if (file.endsWith('.js') || file.endsWith('.mjs') || file.endsWith('.cjs')) return ts.ScriptKind.JS
  return ts.ScriptKind.TS
}

// ------------------------------------------------------------------------ analysis

function analyze(relPath) {
  const abs = path.join(repo, relPath)
  let src
  try {
    src = fs.readFileSync(abs, 'utf8')
  } catch (err) {
    return null
  }
  if (!src.trim()) return null

  const sf = ts.createSourceFile(abs, src, ts.ScriptTarget.Latest, true, scriptKind(relPath))

  const functions = []
  const stack = []
  let fileDecisions = 0

  function lineOf(pos) {
    return sf.getLineAndCharacterOfPosition(pos).line + 1
  }

  function walk(node) {
    const d = decisionCount(node)
    if (d) {
      fileDecisions += d
      // Attribute the decision to the innermost enclosing function.
      if (stack.length) stack[stack.length - 1].decisions += d
    }

    if (isFunctionLike(node)) {
      const rec = {
        name: nameOf(node),
        line: lineOf(node.getStart(sf)),
        end_line: lineOf(node.getEnd()),
        decisions: 0,
        is_async: !!(
          node.modifiers &&
          node.modifiers.some((m) => m.kind === ts.SyntaxKind.AsyncKeyword)
        ),
        exported: !!(
          node.modifiers &&
          node.modifiers.some((m) => m.kind === ts.SyntaxKind.ExportKeyword)
        ),
      }
      functions.push(rec)
      stack.push(rec)
      ts.forEachChild(node, walk)
      stack.pop()
      return
    }

    ts.forEachChild(node, walk)
  }

  ts.forEachChild(sf, walk)

  return {
    path: relPath,
    language: /\.tsx?$|\.mts$|\.cts$/.test(relPath) ? 'typescript' : 'javascript',
    basis: 'exact',
    basis_note: 'Parsed with the TypeScript compiler API v' + ts.version,
    lines: src.split('\n').length,
    file_complexity: fileDecisions + 1,
    functions: functions
      .map((f) => ({
        name: f.name,
        line: f.line,
        end_line: f.end_line,
        complexity: f.decisions + 1,
        is_async: f.is_async,
        exported: f.exported,
      }))
      .sort((a, b) => a.line - b.line),
  }
}

// ---------------------------------------------------------------------------- main

let input = ''
process.stdin.setEncoding('utf8')
process.stdin.on('data', (c) => (input += c))
process.stdin.on('end', () => {
  const files = input
    .split('\n')
    .map((s) => s.trim())
    .filter(Boolean)

  const results = []
  const errors = []
  for (const f of files) {
    try {
      const r = analyze(f)
      if (r) results.push(r)
    } catch (err) {
      errors.push({ path: f, error: String((err && err.message) || err) })
    }
  }

  process.stdout.write(
    JSON.stringify(
      {
        parser: 'typescript@' + ts.version,
        basis: 'exact',
        files: results,
        parse_errors: errors,
      },
      null,
      2
    ) + '\n'
  )
})
