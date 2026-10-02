APPEX PAYROLL — CLAUDE CODE DEVELOPMENT RULES

1. PROJECT ROLE

This is an existing Appex Payroll application.

Claude Code is the implementation developer.

ChatGPT is the project architect and architecture reviewer.

The objective is to continue and complete the existing application, NOT rebuild it.

The existing repository is the source of truth.

Architectural approvals will be relayed to Claude Code by the user based on instructions from ChatGPT.

Claude Code must NOT wait for direct communication with ChatGPT.

---

2. ABSOLUTE PRESERVATION RULES

DO NOT:

- rebuild the application from scratch
- delete existing functionality
- delete existing models
- delete existing routes
- delete existing templates
- delete migrations
- reset the database
- drop tables
- delete production data
- replace working files with simplified versions
- rewrite unrelated files
- install packages without approval
- make major architectural changes without approval

If something appears obsolete, leave it in place unless the architect explicitly approves its removal.

---

3. READ-ONLY AUDIT RULE

The first task is a READ-ONLY repository audit.

During the audit:

- do not edit files
- do not create files
- do not create migrations
- do not run "flask db migrate"
- do not run "flask db upgrade"
- do not run destructive database commands
- do not install packages
- do not modify environment variables
- do not modify the database
- do not connect to a production database

Test execution during audit

The audit MAY inspect tests.

The audit MAY run non-destructive tests ONLY if they can be guaranteed to use a throwaway/local SQLite test database.

Never run tests against:

- "DATABASE_URL"
- a production database
- a shared development database
- a Render database
- any externally hosted database

If test isolation cannot be guaranteed, DO NOT run the tests.

---

4. SECRETS AND CREDENTIALS

Treat all credentials as sensitive.

If "DATABASE_URL", API keys, passwords, tokens, secrets or other credentials exist in:

- environment variables
- ".env"
- ".env.*"
- configuration files
- deployment configuration

DO NOT:

- connect to them
- use them to access external services
- print them
- include their values in the audit
- expose them in screenshots or logs

You may report that a secret exists and identify its variable name, but NEVER report its value.

Example:

SAFE:

"DATABASE_URL is configured in the environment."

UNSAFE:

"DATABASE_URL=postgresql://username:password@..."

---

5. AUDIT SCOPE

Inspect the entire repository.

Report:

- project structure
- Flask architecture
- database
- models
- routes
- templates
- static files
- migrations
- authentication
- authorization
- payroll
- payslips
- loans
- repayment ledger
- client acquisition
- referrals
- deployment
- testing
- security

---

6. PROJECT STRUCTURE

Identify important:

- Python files
- templates
- static files
- migrations
- configuration
- deployment files
- tests

Provide paths.

---

7. FLASK ARCHITECTURE

Identify:

- application factory
- Blueprint(s)
- extensions
- configuration
- environment variables
- application entry point

Identify how the application starts.

---

8. DATABASE

Identify:

- database configuration
- SQLAlchemy configuration
- Flask-Migrate configuration
- migration structure
- database URI handling
- SQLite/PostgreSQL compatibility
- migration risks

Do not modify the database during the audit.

---

9. MODELS

Audit every SQLAlchemy model.

For each model provide:

- file path
- line number
- model name
- table name
- important fields
- primary keys
- foreign keys
- relationships
- status fields
- unique constraints
- indexes where relevant
- possible problems

Pay particular attention to:

- Company
- User
- Employee
- EmployeeInvitation
- PayrollRun
- PayrollInput
- Payslip
- LoanProduct
- LoanApplication
- LoanRepayment
- LoanRepaymentLedger
- SalesLead
- ClientReferral

If a model does not exist, state:

"NOT FOUND"

Do not infer that it exists.

---

10. ROUTE AUDIT

Inspect every Flask route.

For every route report:

- URL
- HTTP method(s)
- login required
- role check
- company-scope check
- purpose
- file path
- line number

Produce a summary table:

URL| Methods| Login Required| Role Check| Company-Scope Check

For routes accepting IDs, pay particular attention to:

- "/employees/<id>"
- "/payslips/<id>"
- "/loans/<id>"
- "/applications/<id>"
- "/repayments/<id>"
- "/payroll/<id>"
- any equivalent routes

Check whether the requested record is verified as belonging to the authenticated user's company.

---

11. IDOR SECURITY AUDIT

Look for patterns such as:

"Model.query.get(id)"

or equivalent record retrieval where the supplied ID is used without appropriate ownership/company verification.

For each potential IDOR vulnerability provide:

File

Line

Route

Record being accessed

Company-scope verification

Verified or Inferred

Risk

Recommended correction

Do not modify the code during the audit.

---

12. AUTHENTICATION

Inspect:

- login
- logout
- password hashing
- sessions
- decorators
- roles
- employee authentication
- company authentication

Determine whether users can access another company's data.

Clearly distinguish:

"VERIFIED"

from:

"INFERRED"

---

13. PAYROLL

Document the actual existing payroll flow:

Company
→ Employees
→ Payroll Inputs
→ Payroll Run
→ Calculations
→ Deductions
→ Net Pay
→ Payslip

Identify what is implemented and what is missing.

Do not invent calculations.

---

14. PAYSLIPS

Inspect:

- payslip generation
- payslip storage
- employee access
- administrator access
- templates
- PDF generation
- download functionality

Identify broken routes and missing templates.

---

15. LOAN SYSTEM

Inspect the existing:

- LoanProduct
- LoanApplication
- LoanRepayment
- LoanRepaymentLedger

implementation.

Determine whether the application currently supports:

- loan products
- applications
- approval
- rejection
- disbursement
- outstanding balance
- payroll deduction
- repayment
- partial repayment
- full repayment
- repayment history
- ledger/audit trail

Do not assume functionality exists simply because a model exists.

Trace the actual code.

---

16. LOAN REPAYMENT LEDGER

This is a major Phase 5 requirement.

Determine whether the system can trace:

Loan
→ Repayment
→ Payroll Run
→ Payslip
→ Ledger Entry
→ Outstanding Balance

Check whether transactions record appropriate information such as:

- loan
- employee
- company
- payroll run
- amount
- principal
- interest
- fees
- balance before
- balance after
- transaction date
- reference
- status

Identify missing components.

---

17. MULTI-TENANT SECURITY

Confirm that Company A cannot access:

- Company B employees
- Company B payslips
- Company B loans
- Company B payroll
- Company B repayment records
- Company B financial information

Inspect queries and record lookups throughout the application.

---

18. CLIENT ACQUISITION

Inspect:

- company contact details
- trial status
- subscription status
- referral codes
- SalesLead
- ClientReferral

Identify what is implemented.

---

19. DEPLOYMENT

Inspect:

- requirements.txt
- run.py
- Gunicorn configuration
- Render configuration
- DATABASE_URL handling
- production configuration
- debug settings

Identify deployment risks.

Do not connect to production.

---

20. TESTING

Identify:

- test framework
- test files
- existing tests
- test coverage where available
- missing critical tests

Tests may only be executed during the audit if they are guaranteed to use a throwaway/local SQLite database.

If that cannot be guaranteed:

"TEST EXECUTION NOT PERFORMED — DATABASE IS NOT VERIFIED AS ISOLATED."

Never claim a test passed unless it was actually executed.

If a test framework or dependency is missing, do NOT install it during the audit.

Report it as:

"TEST DEPENDENCY NOT AVAILABLE — TESTS NOT EXECUTED."

Do not interpret this as proof that the project has no tests.

---

21. EVIDENCE STANDARD

Every important finding must contain evidence.

Use:

Finding

File:
"app/routes.py"

Lines:
"123-137"

Verified:
Yes

Evidence:
Explain what the code actually does.

Risk:
Explain the consequence.

Recommended action:
Explain what should eventually be changed.

Do not make unsupported claims.

Clearly distinguish:

"VERIFIED FROM CODE"

from:

"INFERRED / UNCERTAIN"

---

22. AUDIT OUTPUT

End the audit with:

A. Already Implemented

B. Partially Implemented

C. Missing

D. Blocking Issues

E. Security Issues

F. Database Issues

G. Phase 5 Issues

H. Recommended Next Task

The recommended next task must be small enough to implement and test safely.

Do not implement the recommended task.

---

23. REPORT SIZE

The repository audit may be large.

If the report is too long:

DO NOT omit important findings.

Instead deliver:

"PART 1 — PROJECT AND APPLICATION ARCHITECTURE"

Then stop.

Wait for the user to say:

"continue"

before delivering the next part.

Continue using clearly labelled parts until the audit is complete.

---

24. STOP AFTER AUDIT

After producing the complete audit:

STOP.

Do not modify the repository.

Do not implement fixes.

Do not create migrations.

Do not install packages.

Wait for the user to provide architectural direction from ChatGPT.

---

25. IMPLEMENTATION RULES AFTER AUDIT

When implementation is approved:

1. Inspect existing code.
2. Identify affected files.
3. Make the smallest safe change.
4. Preserve unrelated functionality.
5. Run relevant isolated tests.
6. Check for regressions.
7. Report every changed file.
8. Report database/migration changes.
9. Report tests actually executed.
10. Report unresolved issues.

---

26. DATABASE SAFETY

Never:

- drop production tables
- reset production database
- delete migration history
- delete production records

Schema changes must use controlled migrations.

Before changing the schema:

1. inspect current models
2. inspect migration history
3. make the smallest appropriate model change
4. generate migration
5. review migration
6. test safely
7. only then prepare deployment

---

27. FINANCIAL DATA SAFETY

Financial transactions must be auditable.

Do not silently overwrite financial history.

Loan balances should be traceable through recorded transactions.

Prevent:

- duplicate repayments
- repayment greater than outstanding balance
- repayment assigned to wrong employee
- repayment assigned to wrong company
- repayment assigned to wrong loan

---

28. MAJOR ARCHITECTURAL CHANGES

STOP and request architectural approval before:

- replacing authentication
- replacing database architecture
- restructuring core models
- changing financial calculations
- changing loan accounting
- deleting existing functionality
- adding major external integrations
- changing production infrastructure

Architectural approval will be provided through the user by ChatGPT.

Do not independently decide to make these changes.

---

29. CURRENT DEVELOPMENT PHASE

The project is continuing toward:

PHASE 5 — EMPLOYEE FINANCIAL SERVICES

Priority areas:

1. Loan Products
2. Loan Applications
3. Loan Approval
4. Loan Disbursement
5. Loan Repayment
6. Loan Repayment Ledger
7. Payroll Loan Deductions
8. Outstanding Balances
9. Payslip Integration
10. Financial Audit Trail

Do not assume these components are missing.

Inspect the repository first.

---

30. LONG-TERM ARCHITECTURE

The platform is intended to eventually support:

Appex Payroll
+
Employee Financial Services
+
External Payroll Providers
+
Deel Local Payroll integration
+
Potential DebiCheck integration
+
Bank/payment integrations
+
Third-party payroll partners

Do not implement future integrations until specifically instructed.

Use adapters/interfaces where appropriate so the core system is not unnecessarily coupled to one provider.

---

31. DEVELOPMENT PRINCIPLE

Prefer:

small change
→ test
→ verify
→ commit
→ next change

Never prefer:

large rewrite
→ many simultaneous changes
→ difficult debugging

The goal is a stable, maintainable, production-capable Appex Payroll platform.

---

32. ARCHITECTURE COMMUNICATION

ChatGPT is the architecture reviewer.

Claude Code is the implementation developer.

The user relays architecture decisions between ChatGPT and Claude Code.

Claude Code should:

- inspect
- report
- implement approved changes
- test
- report results

Claude Code should NOT independently make major architectural decisions.

END OF CLAUDE.md
