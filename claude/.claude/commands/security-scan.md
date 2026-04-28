# Security Scan

<command>
    <instructions>
        Following your best practices, run a security scan on the current project. Resolve any security issues that are reported.
    </instructions>
    <process>
        1. Use `security-auditor` agent to run a complete security scan on the current code base. If no issues are found, go to step 5. If issues are found, go to step 2.
          - Your prompt to the agent should be, verbatim, "Run a comprehensive security audit of this application." Don't add any additional instruction or hints.
        2. Fix all findings from this audit report. If a finding requires a code change, make the change. Only list a finding as "requires user action" if it genuinely requires access to external systems (credential rotation, dashboard configuration, third-party service setup) or a product decision.
            - **DO NOT BE LAZY** about fixing issues. 
            - **RESEARCH IF YOU NEED TO**, you aren't restricted to your training knowledge, browse the web, etc.
            - **DO NOT PUNT** issues to the user that you could actually fix yourself.
            - If you just need a piece of information from the user to implement a fix, **ASK THE USER** for the information, then make the fix yourself.
        3. Rerun `security-auditor` to verify the security issues are resolved. If all issues are resolved, go to step 4. If issues remain, go to step 2.
        4. Prepare a report outlining any security findings and the resolution actions taken and present your report to the user.
    </process>
</command>
