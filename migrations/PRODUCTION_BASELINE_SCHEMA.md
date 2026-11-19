# Appex Payroll — Historical Production Schema Baseline

**Snapshot identity:** `appex_payroll_db_zgdz`
**Database engine:** PostgreSQL 18.6
**Snapshot date:** 2026-11-13
**Alembic revision:** `p6_prod_base_01`
**Purpose:** describe the inspected production schema for a fresh-database baseline.

## Safety and interpretation

- This specification records the inspected production structure, not the current ORM model structure.
- The baseline revision is intended for a fresh database rehearsal.
- It must not be run as an ordinary upgrade against the existing production database.
- Production adoption by stamping is a separate operation and requires explicit approval.
- No production data is included in this specification.
- No production schema or data was changed while authoring these files.
- `payslip.pay_period` is deliberately nullable here because that is how the production column was defined in the inspected metadata. The newer application model declares it non-nullable; that difference must be handled in a separately reviewed reconciliation migration.
- The production check found 102 payslip rows, zero NULL `pay_period` values, and zero values longer than 50 characters. That data result does not alter the historical column definition.

## Inventory totals

| Object | Production snapshot |
|---|---:|
| Tables | 12 |
| Columns | 153 |
| Constraints | 101 |
| Foreign keys | 21 |
| Indexes, including PK and unique-constraint indexes | 29 |
| Owned integer ID sequences | 12 |
| Non-sequence server defaults | 16 |

All 21 foreign keys were inspected with `NO ACTION` on update and delete.

## Tables and columns

Notation: `NN` = NOT NULL; `NULL` = nullable. Unless otherwise stated, columns have no server default. All timestamps are `timestamp without time zone`.

### `company` — 13 columns

| Column | Production type | Nullability |
|---|---|---|
| id | integer / serial | NN |
| name | varchar(200) | NN |
| registration_number | varchar(100) | NULL |
| payroll_provider | varchar(100) | NULL |
| created_at | timestamp | NULL |
| contact_person | varchar(200) | NULL |
| contact_phone | varchar(50) | NULL |
| contact_email | varchar(200) | NULL |
| client_status | varchar(50) | NULL |
| subscription_plan | varchar(100) | NULL |
| subscription_status | varchar(50) | NULL |
| onboarding_completed | boolean | NULL |
| referral_code | varchar(50) | NULL |

### `user` — 8 columns

| Column | Production type | Nullability |
|---|---|---|
| id | integer / serial | NN |
| company_id | integer | NN |
| name | varchar(200) | NN |
| email | varchar(200) | NN |
| password_hash | varchar(255) | NN |
| role | varchar(50) | NN |
| is_active | boolean | NULL |
| created_at | timestamp | NULL |

### `employee` — 13 columns

| Column | Production type | Nullability |
|---|---|---|
| id | integer / serial | NN |
| company_id | integer | NN |
| employee_number | varchar(100) | NN |
| first_name | varchar(100) | NN |
| last_name | varchar(100) | NN |
| email | varchar(200) | NULL |
| job_title | varchar(200) | NULL |
| monthly_salary | double precision | NULL |
| status | varchar(50) | NULL |
| created_at | timestamp | NULL |
| user_id | integer | NULL |
| deel_employee_id | varchar(200) | NULL |
| date_of_birth | date | NULL |

### `employee_invitation` — 6 columns

| Column | Production type | Nullability |
|---|---|---|
| id | integer / serial | NN |
| employee_id | integer | NN |
| token | varchar(255) | NN |
| expires_at | timestamp | NN |
| used | boolean | NULL |
| created_at | timestamp | NULL |

### `loan_product` — 11 columns

| Column | Production type | Nullability |
|---|---|---|
| id | integer / serial | NN |
| company_id | integer | NN |
| name | varchar(150) | NN |
| description | text | NULL |
| minimum_amount | double precision | NN |
| maximum_amount | double precision | NN |
| interest_rate | double precision | NN |
| repayment_term_months | integer | NN |
| active | boolean | NN |
| created_at | timestamp | NN |
| updated_at | timestamp | NN |

### `loan_application` — 22 columns

| Column | Production type | Nullability |
|---|---|---|
| id | integer / serial | NN |
| employee_id | integer | NN |
| reference | varchar(50) | NN |
| requested_amount | double precision | NN |
| approved_amount | double precision | NULL |
| loan_purpose | varchar(255) | NULL |
| repayment_term | varchar(100) | NULL |
| monthly_income | double precision | NULL |
| monthly_expenses | double precision | NULL |
| status | varchar(50) | NN |
| reviewed_at | timestamp | NULL |
| reviewed_by | integer | NULL |
| approval_notes | text | NULL |
| disbursed_at | timestamp | NULL |
| disbursement_reference | varchar(100) | NULL |
| total_repayable | double precision | NULL |
| total_paid | double precision | NULL |
| outstanding_balance | double precision | NULL |
| next_payment_date | date | NULL |
| created_at | timestamp | NN |
| updated_at | timestamp | NN |
| product_id | integer | NULL |

### `payroll_run` — 12 columns

| Column | Production type | Nullability | Server default |
|---|---|---|---|
| id | integer / serial | NN | sequence |
| company_id | integer | NN | — |
| pay_period | varchar(50) | NN | — |
| pay_date | date | NULL | — |
| status | varchar(50) | NULL | — |
| total_gross | double precision | NULL | — |
| total_net | double precision | NULL | — |
| deel_payroll_id | varchar(200) | NULL | — |
| created_at | timestamp | NULL | — |
| total_deductions | double precision | NULL | 0 |
| total_employer_uif | double precision | NULL | 0 |
| total_employer_cost | double precision | NULL | 0 |

### `payroll_input` — 10 columns

| Column | Production type | Nullability | Server default |
|---|---|---|---|
| id | integer / serial | NN | sequence |
| payroll_run_id | integer | NN | — |
| employee_id | integer | NN | — |
| basic_salary | double precision | NULL | — |
| overtime | double precision | NULL | — |
| bonus | double precision | NULL | — |
| commission | double precision | NULL | — |
| other_earnings | double precision | NULL | — |
| other_deductions | double precision | NULL | — |
| loan_repayment | double precision | NULL | 0 |

### `payslip` — 22 columns

| Column | Production type | Nullability | Server default |
|---|---|---|---|
| id | integer / serial | NN | sequence |
| employee_id | integer | NN | — |
| payroll_run_id | integer | NULL | — |
| pay_period | varchar(50) | NULL | — |
| pay_date | date | NULL | — |
| gross_pay | double precision | NULL | — |
| net_pay | double precision | NULL | — |
| pdf_url | varchar(500) | NULL | — |
| deel_payslip_id | varchar(200) | NULL | — |
| created_at | timestamp | NULL | — |
| basic_salary | double precision | NULL | 0 |
| other_earnings | double precision | NULL | 0 |
| tax_deductions | double precision | NULL | 0 |
| other_deductions | double precision | NULL | 0 |
| total_deductions | double precision | NULL | 0 |
| overtime | double precision | NULL | 0 |
| bonus | double precision | NULL | 0 |
| commission | double precision | NULL | 0 |
| uif | double precision | NULL | 0 |
| employer_uif | double precision | NULL | 0 |
| employer_cost | double precision | NULL | 0 |
| loan_repayment | double precision | NULL | 0 |

### `loan_repayment` — 12 columns

| Column | Production type | Nullability |
|---|---|---|
| id | integer / serial | NN |
| loan_application_id | integer | NN |
| employee_id | integer | NN |
| payroll_run_id | integer | NULL |
| payslip_id | integer | NULL |
| amount | double precision | NN |
| repayment_date | date | NN |
| payment_method | varchar(50) | NN |
| reference | varchar(100) | NULL |
| status | varchar(50) | NN |
| notes | text | NULL |
| created_at | timestamp | NN |

### `sales_lead` — 14 columns

| Column | Production type | Nullability |
|---|---|---|
| id | integer / serial | NN |
| company_name | varchar(200) | NN |
| registration_number | varchar(100) | NULL |
| contact_person | varchar(200) | NN |
| email | varchar(200) | NN |
| phone | varchar(50) | NULL |
| number_of_employees | integer | NULL |
| status | varchar(50) | NN |
| source | varchar(100) | NN |
| notes | text | NULL |
| assigned_to | integer | NULL |
| converted_company_id | integer | NULL |
| created_at | timestamp | NN |
| updated_at | timestamp | NN |

### `client_referral` — 10 columns

| Column | Production type | Nullability |
|---|---|---|
| id | integer / serial | NN |
| referrer_company_id | integer | NN |
| referred_company_name | varchar(200) | NN |
| referred_contact_person | varchar(200) | NN |
| referred_email | varchar(200) | NN |
| referred_phone | varchar(50) | NULL |
| status | varchar(50) | NN |
| converted_company_id | integer | NULL |
| created_at | timestamp | NN |
| updated_at | timestamp | NN |

## Foreign keys

All inspected foreign keys use `NO ACTION` for both `ON DELETE` and `ON UPDATE`.

| Constraint | Source | Target |
|---|---|---|
| user_company_id_fkey | user.company_id | company.id |
| employee_company_id_fkey | employee.company_id | company.id |
| employee_user_id_fkey | employee.user_id | user.id |
| employee_invitation_employee_id_fkey | employee_invitation.employee_id | employee.id |
| loan_product_company_id_fkey | loan_product.company_id | company.id |
| loan_application_employee_id_fkey | loan_application.employee_id | employee.id |
| loan_application_reviewed_by_fkey | loan_application.reviewed_by | user.id |
| fk_loan_application_product | loan_application.product_id | loan_product.id |
| payroll_run_company_id_fkey | payroll_run.company_id | company.id |
| payroll_input_employee_id_fkey | payroll_input.employee_id | employee.id |
| payroll_input_payroll_run_id_fkey | payroll_input.payroll_run_id | payroll_run.id |
| payslip_employee_id_fkey | payslip.employee_id | employee.id |
| payslip_payroll_run_id_fkey | payslip.payroll_run_id | payroll_run.id |
| loan_repayment_loan_application_id_fkey | loan_repayment.loan_application_id | loan_application.id |
| loan_repayment_employee_id_fkey | loan_repayment.employee_id | employee.id |
| loan_repayment_payroll_run_id_fkey | loan_repayment.payroll_run_id | payroll_run.id |
| loan_repayment_payslip_id_fkey | loan_repayment.payslip_id | payslip.id |
| sales_lead_assigned_to_fkey | sales_lead.assigned_to | user.id |
| sales_lead_converted_company_id_fkey | sales_lead.converted_company_id | company.id |
| client_referral_referrer_company_id_fkey | client_referral.referrer_company_id | company.id |
| client_referral_converted_company_id_fkey | client_referral.converted_company_id | company.id |

## Unique constraints and unique indexes

- `user_email_key`: UNIQUE constraint on `user.email`.
- `employee_invitation_token_key`: UNIQUE constraint on `employee_invitation.token`.
- `ix_company_referral_code_unique`: partial unique index on `company.referral_code` where the value is not NULL.
- `ix_employee_user_id_unique`: partial unique index on `employee.user_id` where the value is not NULL.
- `ix_loan_application_reference`: unique index on `loan_application.reference`.
- `ix_loan_repayment_reference`: unique index on `loan_repayment.reference`.

## Explicit non-primary-key indexes

- `ix_client_referral_referrer_company_id`
- `ix_client_referral_status`
- `ix_company_referral_code_unique`
- `ix_employee_user_id_unique`
- `ix_loan_application_employee_id`
- `ix_loan_application_product_id`
- `ix_loan_application_reference`
- `ix_loan_application_status`
- `ix_loan_product_company_id`
- `ix_loan_repayment_employee_id`
- `ix_loan_repayment_loan_application_id`
- `ix_loan_repayment_payroll_run_id`
- `ix_loan_repayment_payslip_id`
- `ix_loan_repayment_reference`
- `ix_sales_lead_status`

The two unique-constraint indexes above, 12 primary-key indexes, and these 15 explicit indexes account for 29 indexes in total.

## Server defaults

The 16 non-sequence server defaults are numeric zero:

- `payroll_input.loan_repayment`
- `payroll_run.total_deductions`
- `payroll_run.total_employer_uif`
- `payroll_run.total_employer_cost`
- `payslip.basic_salary`
- `payslip.other_earnings`
- `payslip.tax_deductions`
- `payslip.other_deductions`
- `payslip.total_deductions`
- `payslip.overtime`
- `payslip.bonus`
- `payslip.commission`
- `payslip.uif`
- `payslip.employer_uif`
- `payslip.employer_cost`
- `payslip.loan_repayment`

## ID sequences

All 12 tables use integer ID sequences owned by their respective `id` columns. Inspected settings:

- Start: 1
- Minimum: 1
- Maximum: 2,147,483,647
- Increment: 1
- Cycle: false
- Cache: 1

The baseline uses integer autoincrement primary keys so PostgreSQL creates the corresponding owned serial sequences.

## Known model reconciliation items

The ORM source has received several source-only corrections to better represent the inspected production schema. These changes do not alter the historical baseline or any database.

### Source corrections already applied

- `employee.employee_number`, `user.role`, and `payroll_run.pay_period` now match the inspected production nullability and length definitions.
- Partial unique indexes on `company.referral_code` and `employee.user_id` are explicitly represented in the model source.
- Five nullable `created_at` fields were added to the corresponding ORM models to reflect production metadata.
- Backend pay-period validation and both payroll form inputs enforce the 50-character limit.

### Phase 6 additive migration chain

The following revisions were created and successfully applied to the
isolated Phase 6 PostgreSQL rehearsal database:

1. `p6_prod_base_01` — historical production schema baseline.
2. `p6_loan_repay_01` — adds four `loan_repayment` fields:
   `balance_before`, `balance_after`, `payment_number`, and `source`.
3. `p6_loan_app_01` — adds three `loan_product` fields and eight
   `loan_application` fields.

The 15 model-only loan fields identified in the earlier comparison are
therefore represented by the two additive revisions following the
baseline. The rehearsal database reached `p6_loan_app_01`, and the
expected columns were verified there.

These rehearsal results do not mean that production has been migrated
or stamped. The baseline is intended for a fresh database and must not
be run as an ordinary upgrade against the existing production database.
Any production adoption, baseline stamping, or subsequent upgrade
requires a separate schema review and explicit approval.

### Outstanding reconciliation

- `payslip.pay_period` remains nullable in the historical production
  schema, while the current ORM model declares it non-nullable. This
  difference requires a separately reviewed data and schema migration
  before changing production.
- A final full comparison of the current ORM metadata against the live
  production schema is still required before production migration
  adoption. This must include columns, types, nullability, defaults,
  indexes, unique constraints, foreign keys, and sequences.
- No production migration, baseline stamp, or production schema change
  is authorised by the rehearsal results documented here.

## Verification status

This specification was checked against the isolated PostgreSQL Phase 6 rehearsal database. The baseline revision and subsequent Phase 6.2 and Phase 6.3 revisions were applied and their expected schema objects verified there. This verification applies only to the rehearsal database; it does not establish that production has been migrated, stamped, or reconciled.
