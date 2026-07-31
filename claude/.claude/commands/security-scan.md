---
description: Security review of the entire repository, not just pending changes
argument-hint: [optional paths or globs to limit the scan]
---

You are a senior security engineer conducting a security audit of this entire repository. Unlike a diff-based review, the scope is every source file currently in the repository, regardless of when it was written or by whom. Do not skip a finding because it predates recent changes — pre-existing vulnerabilities are exactly what this scan exists to catch.

## Scope

If arguments were provided ("$ARGUMENTS"), treat them as paths or globs limiting the scan. Otherwise the scope is the whole repository.

1. Enumerate candidate files: use `git ls-files` in a git repository; otherwise list files recursively, skipping dependency, build, and VCS directories (`node_modules`, `vendor`, `dist`, `build`, `target`, `.git`, and similar).
2. Exclude: documentation (markdown and similar), lockfiles, generated code, vendored third-party code, and files that are only tests or test fixtures.
3. Group the remaining files into logical areas (per service, package, or top-level module) so each area can be reviewed in one focused pass.

## Phase 1 — Repository context research

Before hunting for vulnerabilities, build context:

- Identify the languages, frameworks, and security-relevant libraries in use.
- Find the established secure-coding patterns in this codebase (authentication middleware, input-validation helpers, ORM/parameterized-query usage, sanitization utilities) so you can spot code that bypasses them.
- Map the trust boundaries: where untrusted input enters (HTTP/RPC handlers, message queues, file parsing, CLI input from untrusted sources) and what privileged resources exist (databases, filesystem, shell execution, credentials, internal services).

## Phase 2 — Vulnerability identification

For each area from the Scope step, launch a sub-task to identify vulnerabilities in that area's files. Launch the area sub-tasks in parallel. Include everything from this section, "Hard exclusions", and "Signal-to-noise assumptions" in each sub-task's prompt.

Identify HIGH-CONFIDENCE security vulnerabilities with real exploitation potential. This is not a general code review — focus only on security.

Core principles:

1. MINIMIZE FALSE POSITIVES: Only flag issues where you are more than 80% confident of actual exploitability.
2. AVOID NOISE: Skip theoretical issues, style concerns, and low-impact findings.
3. FOCUS ON IMPACT: Prioritize vulnerabilities that could lead to unauthorized access, data breaches, or system compromise.

Vulnerability classes to look for:

- Injection: SQL injection, command injection, code injection (eval/deserialization of untrusted data)
- XSS vulnerabilities in web applications (reflected, stored, DOM-based)
- Authentication and authorization flaws: missing server-side permission checks, broken session handling, privilege escalation paths
- Path traversal and unsafe file handling with untrusted paths
- SSRF where untrusted input controls the host or protocol of a request
- Cryptographic misuse: hardcoded keys, broken algorithms, predictable tokens used for security decisions
- Secrets or credentials exposed to untrusted parties (logged in plaintext, returned in responses, committed with active use)
- Unsafe deserialization or parsing of untrusted formats

Even if something is only exploitable from the local network, it can still be a HIGH severity issue.

Sub-tasks should read code to determine whether a vulnerability is real. They do not need to run commands to reproduce it, and they must not write to any files.

## Hard exclusions

Automatically exclude findings matching these patterns:

1. Denial of Service (DoS) vulnerabilities or resource exhaustion attacks.
2. Secrets or credentials stored on disk if they are otherwise secured.
3. Lack of input validation on non-security-critical fields without proven security impact.
4. A lack of hardening measures. Code is not expected to implement all security best practices; flag only concrete vulnerabilities.
5. Race conditions or timing attacks that are theoretical rather than practical. Only report a race condition if it is concretely problematic.
6. Vulnerabilities that exist solely in outdated third-party libraries; dependency versions are managed separately.
7. Memory safety issues in memory-safe languages (Rust, Go, Java, Python, JavaScript, and similar).
8. Files that are only unit tests or only used as part of running tests.
9. Log spoofing. Outputting unsanitized user input to logs is not a vulnerability.
10. SSRF that only controls the path of a URL. SSRF is only a concern if it can control the host or protocol.
11. Including user-controlled content in AI system prompts.
12. Regex injection.
13. Findings in documentation files such as markdown.
14. Input sanitization concerns in GitHub Actions workflows unless clearly triggerable by untrusted input with a very specific attack path.

## Signal-to-noise assumptions

1. Logging high-value secrets in plaintext is a vulnerability. Logging URLs is assumed safe.
2. UUIDs can be assumed unguessable and do not need validation.
3. Environment variables and CLI flags are trusted values. Any attack that relies on the attacker controlling an environment variable is invalid.
4. Resource management issues such as memory or file descriptor leaks are not valid findings.
5. Subtle or low-impact web issues (tabnabbing, XS-Leaks, prototype pollution, open redirects) should not be reported unless extremely high confidence.
6. React and Angular are generally secure against XSS. Do not report XSS in these frameworks unless the code uses `dangerouslySetInnerHTML`, `bypassSecurityTrustHtml`, or similar unsafe methods.
7. A lack of permission checking or authentication in client-side code is not a vulnerability; the server side is responsible for validation.
8. Command injection in shell scripts is generally not exploitable in practice; report it only with a concrete, specific attack path for untrusted input.
9. Vulnerabilities in Jupyter notebooks (`.ipynb`) are rarely exploitable; require a concrete attack path where untrusted input triggers them.
10. Only include MEDIUM findings if they are obvious and concrete issues.

## Phase 3 — False-positive filtering

For each vulnerability found in Phase 2, launch a sub-task to independently validate it. Launch these validation sub-tasks in parallel. Each validator must answer:

1. Is there a concrete, exploitable vulnerability with a clear attack path?
2. Does this represent a real security risk versus a theoretical best practice?
3. Are there specific code locations and reproduction steps?

Each validator assigns a confidence score from 1 to 10:

- 9–10: Certain exploit path identified.
- 8–9: Clear vulnerability pattern with known exploitation methods.
- 7–8: Suspicious pattern requiring specific conditions to exploit.

Discard every finding with a validated confidence below 8. Include the "Hard exclusions" and "Signal-to-noise assumptions" sections in each validator's prompt. Validators read code only; they must not use the bash tool or write files.

## Report

Output the surviving findings as a markdown report and nothing else. For each finding include:

* File and line number
* Severity: HIGH (directly exploitable, leading to remote code execution, data breach, or authentication bypass), MEDIUM (requires specific conditions but significant impact), or LOW (defense-in-depth) — report HIGH and MEDIUM only
* Category (for example `sql_injection`, `xss`, `command_injection`, `auth_bypass`)
* Description: what the flaw is and why it is exploitable
* Exploit scenario: concrete attack an adversary could carry out
* Recommendation: specific fix

Order findings by severity, highest first. If no findings survive filtering, state plainly that the scan found no high-confidence vulnerabilities and summarize what was reviewed (areas and file counts) so the empty result is verifiable. Better to miss a theoretical issue than to flood the report with false positives — each finding should be something a security engineer would confidently raise.
