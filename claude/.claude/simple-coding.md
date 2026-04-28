<coding_philosophy>
  <principle>Simple is objective (one fold, not interleaved). Easy is relative (familiar, at-hand). Always choose simple over easy.</principle>
</coding_philosophy>

<core_rules>
  <rule id="decompose_and_separate">
    <name>Decompose and Separate</name>
    <description>Break problems into single-responsibility components. Avoid "complecting" (interweaving) concerns that should be independent. Each function/class should have one reason to change (SRP).</description>
    <implementation>
      - Separate what (operations) from how (implementation) from when/where (timing/location)
      - Prefer composition over inheritance
      - Keep data structures separate from business logic
    </implementation>
  </rule>

  <rule id="plan_before_building">
    <name>Plan Before Building</name>
    <description>Always create a step-by-step plan before implementation. Identify and separate what/how/when/where/why concerns explicitly.</description>
    <implementation>
      - Request acceptance criteria and constraints upfront
      - Outline which files will be modified and why
      - Get plan approval before writing implementation code
      - Commit small, reviewable changes frequently
    </implementation>
  </rule>

  <rule id="choose_simple_constructs">
    <name>Choose Simple Constructs</name>
    <description>Prefer constructs that produce simple, composable artifacts. Avoid complecting multiple concerns in a single construct.</description>
    <implementation>
      - Values over state and objects (state complects value + time)
      - Functions over methods (methods complect function + state)
      - Data over syntax (represent information as data)
      - Declarative over imperative approaches
      - Interfaces/abstractions over concrete implementations (DIP)
    </implementation>
  </rule>

  <rule id="test_incrementally">
    <name>Test and Validate Incrementally</name>
    <description>Build, test, and validate small pieces rather than large complex systems. Implement feedback loops for self-correction.</description>
    <implementation>
      - Write tests first when possible (TDD)
      - Run tests after each significant change
      - Use compiler/linter feedback as a quality gate
      - Ask for human validation of plans and key decisions
    </implementation>
  </rule>
</core_rules>

<anti_patterns>
  <avoid>God classes or functions that do multiple unrelated things</avoid>
  <avoid>Tightly coupled components that cannot be changed independently</avoid>
  <avoid>Hidden dependencies and global state</avoid>
  <avoid>Premature optimization that adds complexity</avoid>
  <avoid>Large, monolithic changes that are hard to review</avoid>
</anti_patterns>

<decision_framework>
  <question>Does this solution have a single, clear responsibility?</question>
  <question>Can I change one part without affecting unrelated parts?</question>
  <question>Am I choosing simple constructs over familiar but complex ones?</question>
  <question>Can I test this incrementally?</question>
</decision_framework>
