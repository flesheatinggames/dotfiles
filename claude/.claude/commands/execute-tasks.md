<task_execution_rules alwaysApply="false" encoding="UTF-8">
    <ai_meta>
        <parsing_rules>
            - Process XML blocks first for structured data
            - Execute instructions in sequential order
            - Use templates as exact patterns
            - Request missing data rather than assuming
        </parsing_rules>
        <file_conventions>
            - encoding: UTF-8
            - line_endings: LF
            - indent: 2 spaces
            - markdown_headers: no indentation
        </file_conventions>
    </ai_meta>
    <mandatory
        priority="critical">
        <first_step priority="non-negotiable">
            **STOP**. Your best practices were just updated. Whatever you have in memory is wrong. Before you do anything else, you **MUST** re-read your best practices. Do that, and then continue.
        </first_step>
        <orchetrator>
            You are to act as an **ORCHESTRATOR ONLY** for this task 
            execution. You will delegate all work to appropriate agents.
        </orchetrator>
        <agent_usage>
            **ALWAYS** communicate with agents appropriately as defined in your best practices!

            - Step 1: Identify which specialized agents are needed
            - Step 2: Use appropriate agents before any direct implementation
            - Step 3: Use documentation-specialist where appropriate
            - Step 4: Use code-reviewer agent after completion
        </agent_usage>
        <task_management>
            - This is an **Agent OS** task. You **MUST** use Agent OS for spec and task management.
            - **ALWAYS** mark each subtask complete as you complete and verify it. **DO NOT** wait until
            the entire task is complete before you mark the subtasks complete.
        </task_management>
    </mandatory>
    ## Overview
    <purpose>
        - Execute spec tasks systematically
        - Follow TDD development workflow
        - Ensure quality through testing and review
    </purpose>
    <context>
    - Part of Agent OS framework
        - Executed after spec planning is complete
        - Follows tasks defined in spec tasks.md
    </context>
    <prerequisites>
    - Spec documentation exists in @.agent-os/specs/
        - Tasks defined in spec's tasks.md
        - Development environment configured
        - Git repository initialized
    </prerequisites>
    <process_flow>
        <step number="1" name="task_assignment"> ### Step 1: Task Assignment
            <step_metadata>
                <inputs>
                    - spec_srd_reference: file path
                    - specific_tasks: array[string] (optional)
                </inputs>
                <default>next uncompleted parent task</default>
            </step_metadata>
            <task_selection>
                <explicit>user specifies exact task(s)</explicit>
                <implicit>find next uncompleted task in tasks.md</implicit>
            </task_selection>
            <instructions>
                **ACTION:** Identify task(s) to execute
                **DEFAULT:** Select next uncompleted parent task if not specified
                **CONFIRM:** Task selection with user
            </instructions>
        </step>
        <step number="2" name="context_analysis"> ### Step 2: Context Analysis
            <step_metadata>
                <reads>
                    - spec SRD file
                    - spec tasks.md
                    - all files in spec sub-specs/ folder
                    - @.agent-os/product/mission.md
                </reads>
                <purpose>complete understanding of requirements</purpose>
            </step_metadata>
            <context_gathering>
                <spec_level>
                    - requirements from SRD
                    - technical specs
                    - test specifications
                </spec_level>
                <product_level>
                    - overall mission alignment
                    - technical standards
                    - best practices
                </product_level>
            </context_gathering>
            <instructions>
                **ACTION:** Read all spec documentation thoroughly
                **ANALYZE:** Requirements and specifications for current task
                **UNDERSTAND:** How task fits into overall spec goals
            </instructions>
        </step>
        <step number="3" name="implementation_planning"> ### Step 3: Implementation Planning
            <step_metadata>
                <creates>execution plan</creates>
                <requires>user approval</requires>
            </step_metadata>
            <plan_structure>
                <format>numbered list with sub-bullets</format>
                <includes>
                    - all subtasks from tasks.md
                    - implementation approach
                    - dependencies to install
                    - test strategy
                </includes>
            </plan_structure>
            <plan_template>
                ## Implementation Plan for [TASK_NAME]

                1. **[MAJOR_STEP_1]**
                - [SPECIFIC_ACTION]
                - [SPECIFIC_ACTION]

                2. **[MAJOR_STEP_2]**
                - [SPECIFIC_ACTION]
                - [SPECIFIC_ACTION]

                **Dependencies to Install:**
                - [LIBRARY_NAME] - [PURPOSE]

                **Test Strategy:**
                - [TEST_APPROACH]
</plan_template>
            <approval_request>
    I've prepared the above implementation plan.
                Please review and confirm before I proceed with execution.
</approval_request>
            <instructions>
    ACTION: Create detailed execution plan
                DISPLAY: Plan to user for review
                WAIT: For explicit approval before proceeding
                BLOCK: Do not proceed without affirmative permission
</instructions>
        </step>
        <step number="4" name="development_server_check">
            <step_metadata>
                <checks>running development server</checks>
                <prevents>port conflicts</prevents>
            </step_metadata>
            <server_check_flow>
                <if_running>
                    ASK user to shut down
                    WAIT for response
                </if_running>
                <if_not_running>
                    PROCEED immediately
                </if_not_running>
            </server_check_flow>
            <user_prompt>
                A development server is currently running.
                Should I shut it down before proceeding? (yes/no)
</user_prompt>
            <instructions>
                ACTION: Check for running local development server
                CONDITIONAL: Ask permission only if server is running
                PROCEED: Immediately if no server detected
</instructions>
        </step>
        <step number="6" name="development_execution">
            <step_metadata>
                <follows>approved implementation plan</follows>
                <adheres_to>all spec standards</adheres_to>
            </step_metadata>
            <execution_standards>
                <follow_exactly>
                    - approved implementation plan
                    - spec specifications
                    - @.agent-os/product/code-style.md
                    - @.agent-os/product/dev-best-practices.md
                </follow_exactly>
                <approach>test-driven development (TDD)</approach>
            </execution_standards>
            <tdd_workflow>
                1. Write failing tests first
                2. Implement minimal code to pass
                3. Refactor while keeping tests green
                4. Repeat for each feature
</tdd_workflow>
            <instructions>
                ACTION: Execute development plan systematically
                FOLLOW: All coding standards and specifications
                IMPLEMENT: TDD approach throughout
                MAINTAIN: Code quality at every step
</instructions>
        </step>
        <step number="7" name="task_status_updates">
            <step_metadata>
                <updates>tasks.md file</updates>
                <timing>immediately after completion</timing>
            </step_metadata>
            <update_format>
                <completed>- [x] Task description</completed>
                <incomplete>- [ ] Task description</incomplete>
                <blocked>
                    - [ ] Task description
                    ⚠️ Blocking issue: [DESCRIPTION]
                </blocked>
            </update_format>
            <blocking_criteria>
                <attempts>maximum 3 different approaches</attempts>
                <action>document blocking issue</action>
                <emoji>⚠️</emoji>
            </blocking_criteria>
            <instructions>
                ACTION: Update tasks.md after each subtask completion
                MARK: [x] for completed items immediately
                DOCUMENT: Blocking issues with ⚠️ emoji
                LIMIT: 3 attempts before marking as blocked
</instructions>
        </step>
        <step number="8" name="test_suite_verification">
            <step_metadata>
                <runs>entire test suite</runs>
                <ensures>no regressions</ensures>
            </step_metadata>
            <test_execution>
                <order>
                    1. Verify new tests pass
                    2. Run entire test suite
                    3. Fix any failures
                </order>
                <requirement>100% pass rate</requirement>
            </test_execution>
            <failure_handling>
                <action>troubleshoot and fix</action>
                <priority>before proceeding</priority>
            </failure_handling>
            <instructions>
                ACTION: Run complete test suite
                VERIFY: All tests pass including new ones
                FIX: Any test failures before continuing
                BLOCK: Do not proceed with failing tests
</instructions>
        </step>
        <step number="9" name="roadmap_progress_check">
            <step_metadata>
                <checks>@.agent-os/product/roadmap.md</checks>
                <updates>if spec completes roadmap item</updates>
            </step_metadata>
            <roadmap_criteria>
                <update_when>
                    - spec fully implements roadmap feature
                    - all related tasks completed
                    - tests passing
                </update_when>
                <caution>only mark complete if absolutely certain</caution>
            </roadmap_criteria>
            <instructions>
                ACTION: Review roadmap.md for related items
                EVALUATE: If current spec completes roadmap goals
                UPDATE: Mark roadmap items complete if applicable
                VERIFY: Certainty before marking complete
</instructions>
        </step>
        <step number="10" name="completion_notification">
            <step_metadata>
                <plays>system sound</plays>
                <alerts>user of completion</alerts>
            </step_metadata>
            <notification_command>
                afplay /System/Library/Sounds/Glass.aiff
</notification_command>
            <instructions>
                ACTION: Play completion sound
                PURPOSE: Alert user that task is complete
</instructions>
        </step>
        <step number="11" name="completion_summary">
            <step_metadata>
                <creates>summary message</creates>
                <format>structured with emojis</format>
            </step_metadata>
            <summary_template>
                ## ✅ What's been done

                1. **[FEATURE_1]** - [ONE_SENTENCE_DESCRIPTION]
                2. **[FEATURE_2]** - [ONE_SENTENCE_DESCRIPTION]

                ## ⚠️ Issues encountered

                [ONLY_IF_APPLICABLE]
                - **[ISSUE_1]** - [DESCRIPTION_AND_REASON]

                ## 👀 Ready to test in browser

                [ONLY_IF_APPLICABLE]
                1. [STEP_1_TO_TEST]
                2. [STEP_2_TO_TEST]

            </summary_template>
            <summary_sections>
                <required>
                    - functionality recap
                    - pull request info
                </required>
                <conditional>
                    - issues encountered (if any)
                    - testing instructions (if testable in browser)
                </conditional>
            </summary_sections>
            <instructions>
                ACTION: Create comprehensive summary
                INCLUDE: All required sections
                ADD: Conditional sections if applicable
                FORMAT: Use emoji headers for scannability
</instructions>
        </step>
    </process_flow>
    <development_standards>
        <code_style>
            <follow>@.agent-os/product/code-style.md</follow>
            <enforce>strictly</enforce>
        </code_style>
        <best_practices>
            <follow>@.agent-os/product/dev-best-practices.md</follow>
            <apply>all directives</apply>
        </best_practices>
        <testing>
            <coverage>comprehensive</coverage>
            <approach>test-driven development</approach>
        </testing>
        <documentation>
            <commits>clear and descriptive</commits>
            <pull_requests>detailed descriptions</pull_requests>
        </documentation>
    </sdevelopment_standards>
    <error_handling_protocols>
        <blocking_issues>
            - document in tasks.md
            - mark with ⚠️ emoji
            - include in summary
        </blocking_issues>
        <test_failures>
            - fix before proceeding
            - never commit broken tests
        </test_failures>
        <technical_roadblocks>
            - attempt 3 approaches
            - document if unresolved
            - seek user input
        </technical_roadblocks>
    </error_handling_protocols>
    <final_checklist>
        <verify>
            - [ ] Task implementation complete
            - [ ] All tests passing
            - [ ] tasks.md updated
            - [ ] Code committed and pushed
            - [ ] Pull request created
            - [ ] Roadmap checked/updated
            - [ ] Summary provided to user
        </verify>
    </final_checklist>
</task_execution_rules>