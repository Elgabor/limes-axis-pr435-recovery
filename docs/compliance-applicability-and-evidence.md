# Compliance Applicability And Evidence Matrix

Last source review: 2026-08-29. Repository evidence owner at this baseline:
`@metaforismo`.

This is a readiness and scoping record. It is not legal advice, an ISO audit,
certification, conformity assessment or a claim that Limes Axis, Limes Labs or a
customer is compliant. Applicability depends on the organization, deployment,
data, intended purpose, jurisdiction and contracts. A product control is only
one possible evidence item; it cannot prove the organizational obligations by
itself.

## Primary Sources And Interpretation Boundary

| Framework | Primary source used | Interpretation boundary |
| --- | --- | --- |
| ISO/IEC 27001 | [ISO/IEC 27001:2022 official page](https://www.iso.org/standard/27001) | Voluntary management-system scope selected by an organization. ISO states that certification is a separate choice; this matrix does not reproduce the copyrighted standard or assert conformity. |
| GDPR | [Regulation (EU) 2016/679](https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX%3A32016R0679), [European Commission controller/processor guidance](https://commission.europa.eu/law/law-topic/data-protection/information-business-and-organisations/application-gdpr_en), [EDPB Guidelines 07/2020](https://www.edpb.europa.eu/documents/guideline/guidelines-072020-on-the-concepts-of-controller-and-processor-in-the-gdpr_en) | Material/territorial scope and controller/processor roles follow actual processing, not the software label. |
| EU AI Act | [Regulation (EU) 2024/1689](https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX%3A32024R1689), [current Commission implementation timeline](https://digital-strategy.ec.europa.eu/en/policies/regulatory-framework-ai) | Role, risk class and duties depend on how an AI system is provided, deployed, modified and used. Use the current consolidated law and guidance at each review. |
| NIS2 | [Directive (EU) 2022/2555](https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX%3A32022L2555), [European Commission NIS2 FAQ](https://digital-strategy.ec.europa.eu/en/faqs/directive-measures-high-common-level-cybersecurity-across-union-nis2-directive-faqs) | Scope depends on entity type, sector, size/designation, establishment and national transposition. A repository is not independently “NIS2 compliant.” |

[ISO/IEC 42001](https://www.iso.org/standard/42001) may later support the AI
management-system workstream, but it is not silently substituted for the
ISO/IEC 27001 scope requested here. Adding it requires its own applicability
decision and qualified review.

## Applicability Baseline

| Framework | Baseline decision | Trigger to evaluate | What Axis evidence can support | What remains outside the repository |
| --- | --- | --- | --- | --- |
| ISO/IEC 27001:2022 | Voluntary or contract-driven; candidate scope for Limes Labs and Hosted operations, not automatically for every customer deployment | Management selects an ISMS scope or a contract/tender requires certification/readiness | Secure-development, access, audit, vulnerability, incident and resilience evidence | ISMS scope, risk method/register, treatment plan, Statement of Applicability, policies, competence, internal audit, management review and accredited certification |
| GDPR | Likely relevant whenever Axis processes personal data; exact Limes/customer role changes by deployment and purpose | Identity/session data, actor audit data, uploaded documents, connected records, support data or telemetry contain information about people and EU scope is met | Data-flow boundaries, tenant isolation, access controls, retention/legal-hold mechanisms, export/deletion foundations, security and audit evidence | Lawful basis, notices, records of processing, contracts, subprocessors, rights operations, DPIA, transfer mechanism, breach decisions and regulator/data-subject communications |
| EU AI Act | Conditional; Axis model routing or agents do not make every deployment high-risk and do not by themselves make Limes a GPAI model provider | Axis is placed on the market/put into service as an AI system; intended purpose falls into a regulated use; Limes/customer changes role or substantially modifies a system | Model/system inventory fields, routing/egress policy, human approvals, logging, traceability and deployment evidence | Final provider/deployer/importer/distributor role, prohibited/high-risk classification, fundamental-rights or conformity work where required, registration, post-market duties and customer intended-use controls |
| NIS2 | Entity- and jurisdiction-dependent; relevant directly only after sector/size/designation and national-law analysis, and indirectly through customer supply-chain duties | Limes acts as an in-scope cloud/MSP or other listed entity, is designated, or an in-scope customer imposes supplier controls | Risk, vulnerability, supply-chain, access, incident, continuity and recovery evidence | Entity registration/classification, management approvals/training, national authority/CSIRT process, statutory notifications and customer/organization-wide measures |

## Roles By Deployment

The role assignment is a review starting point, not a contractual conclusion.
“Limes independent controller” means only data used for Limes's own account,
security, support or commercial purposes; it does not automatically include
customer operational data.

| Deployment | GDPR starting point | AI Act starting point | ISO/IEC 27001 scope | NIS2 starting point | Required decision owner |
| --- | --- | --- | --- | --- | --- |
| Local evaluation operated only by the customer | Customer controller; Limes normally has no processor role unless it receives data/support access | Customer deployer; Limes may be provider of the packaged AI system, but not automatically provider of the routed GPAI model | Customer-selected; repository evidence is supporting material only | Customer entity analysis; Limes may be a product supplier | Customer privacy, AI governance and security owners |
| Future OSS self-hosting | User/controller; publishing software alone does not make Limes processor for deployment data | User/deployer; provider/modifier status depends on packaging, branding and changes | User-selected; no certification inherited from the project | User/entity analysis; software supply-chain relevance may remain | OSS operator plus qualified counsel for the actual use |
| Limes Hosted multi-tenant | Customer usually controller and Limes usually processor for tenant data; Limes separate controller for its own account/security data; subprocessors conditional | Limes likely provider/hosted operator of the Axis AI system and customer deployer; model provider remains the external/self-hosted model owner unless facts change | Candidate Limes Hosted ISMS scope; certification not performed | Limes cloud/MSP and size/designation analysis required in every establishment; customer duties also apply | Limes privacy/legal, AI governance, security and Hosted operations owners |
| Limes-managed dedicated tenant | Same role split as Hosted, adjusted by the DPA and operational access | Limes/customer provider/deployer allocation follows branding, intended purpose and contract | Candidate Limes managed-service scope plus customer controls | Limes entity analysis plus customer supplier obligations | Limes and customer owners jointly |
| Customer private cloud or on-prem | Customer controller; Limes processor only for contracted remote operations/support that processes personal data; separate controller for its own support records | Limes may provide the Axis AI system; customer is deployer and may become provider after substantial modification or changed intended purpose | Customer ISMS scope; Limes evidence does not extend certification to the environment | Customer entity analysis; Limes is a supplier unless independently in scope | Customer owners, with Limes support/security owner for contracted controls |

## Control Catalog

| Control ID | Outcome | Current Axis boundary |
| --- | --- | --- |
| `GOV-01` | Scope, assets, roles, owners, risk decisions and review history are explicit | Architecture, threat model, editions and this matrix are versioned; organizational registers remain external |
| `IAM-01` | Identities, tenants, permissions, sessions and privileged actions fail closed | OIDC/session, tenant isolation, permission and approval contracts |
| `DAT-01` | Data purposes, minimization, lineage, retention, export and deletion are controlled | Metadata/lineage, audit retention/legal hold and export foundations; processing inventory and rights operations incomplete |
| `SUP-01` | Suppliers, subprocessors, connectors, models, credentials, transfers and egress are governed | Credential handles/leases, egress policies and provider boundaries; contractual registers external |
| `SEC-01` | Secure development, vulnerability, change, configuration and risk management produce reviewable proof | CI, threat model, dependency/container scans and deployment readiness; production risk acceptance external |
| `LOG-01` | Security, workflow, human and AI actions are traceable with protected evidence | Tenant-scoped append-only audit, correlation, model/connector evidence and export integrity foundations |
| `INC-01` | Incidents and personal-data/security breaches are detected, assessed, escalated and reported on time | Incident runbook and telemetry foundations; statutory decision/notification evidence external |
| `BCM-01` | Availability, backup, restore, continuity and disaster recovery are owned and rehearsed | Bounded deployment rehearsals; full production/customer evidence remains incomplete |
| `AI-01` | AI systems/models, intended purpose, roles, risk class, data and changes are inventoried | Model endpoint/invocation records and versioned contracts; organization-wide AI inventory/classification external |
| `AI-02` | Human oversight, transparency, instructions, limitations and intervention are effective | Propose/dry-run modes, approval gates, audit and console evidence; customer training/use policy external |
| `ASS-01` | Evidence is reviewed, gaps are resolved or accepted by an authorized owner, and claims are independently validated when required | PR review and automated evidence only; counsel, certification specialist and external assurance not completed |

## Framework-To-Control And Evidence Matrix

| Framework requirement group | Controls | Repository evidence candidates | Organizational/customer evidence required | Owner and minimum cadence | Current gap |
| --- | --- | --- | --- | --- | --- |
| ISO/IEC 27001 organizational context, leadership, scope and risk treatment | `GOV-01`, `ASS-01` | `E-ARCH`, `E-THREAT`, `E-GOV` | `O-ISMS`: scope, interested parties, risk method/register, treatment plan, Statement of Applicability, objectives and approvals | Security/ISMS owner; quarterly, material change and management-review cycle | `GAP-ISO-01`, `GAP-OWN-01` |
| ISO/IEC 27001 operational security-control themes | `IAM-01`, `DAT-01`, `SUP-01`, `SEC-01`, `LOG-01`, `INC-01`, `BCM-01` | `E-IAM`, `E-AUDIT`, `E-EGRESS`, `E-VULN`, `E-INC`, `E-BCM` | Policies, asset/supplier registers, access reviews, training, production records and risk-linked control operation | Control owners; per release/incident plus quarterly evidence review | `GAP-PROD-01` |
| ISO/IEC 27001 performance evaluation and improvement | `ASS-01` | CI/PR history and gap register | Internal audit, metrics, nonconformities/corrective actions, management review and accredited audit | ISMS owner; planned audit/review cycle | `GAP-ISO-01` |
| GDPR scope, roles, principles, lawful basis and accountability (Arts. 2-6, 24) | `GOV-01`, `DAT-01` | `E-ARCH`, `E-DATA`, deployment role table | `O-PRIV`: processing inventory, role record, lawful bases, purposes/notices and accountability decisions | Privacy/legal owner; before processing, quarterly and on purpose/data change | `GAP-GDPR-01`, `GAP-OWN-01` |
| GDPR data-subject rights, privacy by design, records and DPIA (Arts. 12-22, 25, 30, 35) | `DAT-01`, `IAM-01`, `LOG-01`, `ASS-01` | Export/deletion, authorization and audit foundations | Rights workflow/evidence, retention schedule, ROPA and DPIA where required | Privacy owner and product owner; per release/use case and annual program review | `GAP-GDPR-01`, `GAP-CUST-01` |
| GDPR processor, security, breach and transfer duties (Arts. 28, 32-34, 44+) | `SUP-01`, `SEC-01`, `INC-01`, `BCM-01` | `E-EGRESS`, `E-VULN`, `E-INC`, `E-BCM` | DPA, subprocessor/transfer register, SCC/transfer assessment where needed, breach assessment/notifications and incident records | Privacy/legal, security and operations owners; supplier change, incident and quarterly review | `GAP-GDPR-01`, `GAP-PROD-01` |
| AI Act scope, role, intended purpose and risk classification | `GOV-01`, `AI-01`, `SUP-01` | `E-AI`, architecture/model-routing evidence | `O-AI`: system/model inventory, provider/deployer chain, intended purpose, modification history, prohibited/high-risk assessment | Product/AI governance plus counsel; every system/use-case/release change and quarterly inventory review | `GAP-AI-01` |
| AI Act high-risk provider/deployer requirements when classification triggers them | `AI-01`, `AI-02`, `DAT-01`, `LOG-01`, `SEC-01`, `ASS-01` | Typed contracts, approvals, audit, model invocation and deployment tests | Risk/quality management, data governance, technical documentation, instructions, human-oversight plan, accuracy/robustness/cybersecurity evidence, assessment/registration and deployer controls as applicable | AI governance, engineering, security and customer deployer owner; before placing/putting into service and continuous monitoring | `GAP-AI-01`, `GAP-CUST-01` |
| AI Act transparency, logging, incident/post-market and literacy/use controls as applicable | `AI-02`, `LOG-01`, `INC-01`, `ASS-01` | Console/audit/invocation evidence and incident runbook | User disclosures, generated-content marking where required, instructions/training, monitoring and authority reporting | AI governance/operations; each release, incident and periodic monitoring review | `GAP-AI-01`, `GAP-PROD-01` |
| NIS2 entity/sector/size/designation and jurisdiction determination (Arts. 2-3, 26) | `GOV-01`, `ASS-01` | Architecture, edition/deployment profiles and supplier inventory candidates | `O-NIS`: national-law entity determination, registration/listing and authority/CSIRT contacts | Qualified counsel and security owner; annual and on entity/service/jurisdiction change | `GAP-NIS-01` |
| NIS2 management accountability and risk-management measures (Arts. 20-21) | `IAM-01`, `SUP-01`, `SEC-01`, `LOG-01`, `INC-01`, `BCM-01`, `ASS-01` | `E-THREAT`, `E-IAM`, `E-EGRESS`, `E-VULN`, `E-INC`, `E-BCM` | Management approval/training, organization-wide risk and supply-chain measures, effectiveness evidence and customer allocation | Management body, security and operations owners; per material risk and quarterly program review | `GAP-NIS-01`, `GAP-PROD-01` |
| NIS2 significant-incident reporting (Art. 23 and national law) | `INC-01`, `LOG-01` | Incident/telemetry/audit foundations | Significance decision, statutory timelines, CSIRT/authority communications and final report | Incident commander plus legal/security owner; every incident and annual exercise | `GAP-NIS-01` |

## Repository Evidence Register

`Automated` means source/contract evidence passed tests. It does not prove that a
customer or production environment operated the control.

| Evidence ID | Location | State | Owner | Review cadence | Limitation |
| --- | --- | --- | --- | --- | --- |
| `E-ARCH` | [Architecture](./architecture.md), [ADR records](./adr) | Reviewed repository evidence | Architecture/code owner | Material architecture change and quarterly | Describes source boundaries, not deployed configuration |
| `E-THREAT` | [Threat model](./threat-model.md), [security checklist](./security-review-checklist.md) | Reviewed repository evidence | Security owner | Material threat/change and quarterly | No independent penetration test or production validation |
| `E-GOV` | [Repository governance](./repository-governance.md), PR/CI history | Automated/reviewed | Repository owner | Every PR and quarterly | Hosted protection/approval limits remain documented |
| `E-IAM` | [Identity/tenancy](./platform-tenants.md), `services/api/tests/test_tenant_isolation.py`, session/OIDC tests | Automated source evidence | Identity/security owner | Every relevant PR/release and quarterly | No customer IdP access review or production session sample |
| `E-DATA` | [Data assets](./platform-data-assets.md), [persistence](./platform-persistence.md), [audit](./platform-audit.md) | Implemented/automated foundations | Data/product owner | Every data-contract change and quarterly | No complete ROPA, rights operation or production retention proof |
| `E-AUDIT` | [Audit](./platform-audit.md), audit/export/integrity tests | Implemented/automated foundations | Security/product owner | Every audit change/release and quarterly | No externally verified WORM/KMS operation in customer infrastructure |
| `E-EGRESS` | [Connectors](./platform-connectors.md), [model routing](./platform-model-routing.md), credential/egress tests | Implemented/automated foundations | Connector/model security owner | Provider/connector change and quarterly | Supplier, subprocessor and transfer contracts external |
| `E-AI` | [Agents](./platform-agents.md), [actions](./platform-actions.md), [model routing](./platform-model-routing.md), invocation tests | Implemented/automated foundations | Product/AI governance owner | Every AI system/model/use change and quarterly | No authoritative organization/customer AI system classification |
| `E-VULN` | Container/dependency security workflows, [threat model](./threat-model.md) | Automated source evidence | Security owner | Every build/dependency change and monthly triage | Scanner findings are not a complete organization risk program |
| `E-INC` | [Incident response runbook](./runbooks/incident-response.md), telemetry/audit contracts | Implemented baseline | Security/operations owner | Every incident and annual exercise | Statutory notification decision/exercise not performed |
| `E-BCM` | [Deployment](./deployment.md), backup/restore/HA/DR rehearsal documents and tests | Bounded automated/rehearsal evidence | Operations owner | Each release, quarterly bounded rehearsal and annual production exercise | Full customer-profile production recovery evidence incomplete |

## External Evidence Required

These records contain organizational, personal, customer or legal material and
must live in an approved evidence system, not public-safe API payloads or source
control.

| Evidence ID | Required record | Owner | Minimum cadence | Current state |
| --- | --- | --- | --- | --- |
| `O-ISMS` | ISMS scope, risk register/method, treatment plan, Statement of Applicability, policies, objectives, competence, audit and management review | Named Security/ISMS owner | Quarterly program review and defined audit cycle | Not collected / owner not formally assigned |
| `O-PRIV` | ROPA, controller/processor decisions, DPA/subprocessors, lawful bases/notices, rights log, DPIA, retention/transfers and breach log | Privacy/legal owner or DPO if required | Before processing, quarterly and on change/incident | Not collected in repository; external status unverified |
| `O-AI` | AI system/model inventory, intended purposes, roles, risk decisions, technical/user documentation, monitoring/incidents and required assessments | Product/AI governance owner | Per system/release/change and quarterly | Not collected as an authoritative organizational register |
| `O-NIS` | Entity/jurisdiction determination, management approval/training, risk/supplier program, authority contacts and incident reports | Management body, security and qualified counsel | Annual and on entity/service/jurisdiction change; per incident | Not determined |
| `O-CUST` | Customer data/use classification, IdP/access review, intended AI purpose/oversight, infrastructure, supplier, continuity and incident allocation | Customer control owner with Limes contract owner | Before go-live, each material change and agreed assurance cycle | Customer-dependent / not collected |

## Customer-Dependent Control Allocation

| Decision/control | Limes evidence contribution | Customer evidence required |
| --- | --- | --- |
| Personal-data purpose, lawful basis, notice, rights and DPIA | Product data flows, export/deletion and security capabilities | Actual data inventory, legal decision, notice, rights operation and DPIA outcome |
| Identity, roles and privileged access | OIDC, tenancy, permission and session controls | IdP configuration, joiner/mover/leaver process, access reviews and break-glass ownership |
| AI intended purpose, risk class and human oversight | System capabilities, model routing, approvals, logs and limitations | Use-case classification, operator competence, oversight procedure, prohibited-use and modification controls |
| Models, connectors, suppliers, transfers and egress | Provider/connector registry, credentials, leases and policy gates | Approved suppliers/subprocessors, contracts, transfer mechanism, credentials and destination allowlists |
| Production security, continuity and incidents | Deployment/readiness contracts, runbooks and bounded rehearsals | Network/platform configuration, backups, RPO/RTO, exercises, contacts and statutory/customer notifications |

## Gap, Risk And Review Register

| Gap ID | Gap or risk | Status | Blocking claim/action | Owner | Exit evidence |
| --- | --- | --- | --- | --- | --- |
| `GAP-ISO-01` | No qualified ISO/IEC 27001 scope/control mapping or certification audit | `NOT RUN` | ISO conformity/certification/readiness claim | Security/ISMS owner plus qualified certification specialist | Written scope/crosswalk review and, if pursued, accredited audit evidence |
| `GAP-GDPR-01` | No qualified GDPR applicability/role review or complete privacy program evidence | `NOT RUN` | GDPR-compliance claim or production processing without approved privacy basis/contracts | Privacy/legal owner plus qualified counsel | Signed role/scope review and `O-PRIV` records |
| `GAP-AI-01` | No deployment-specific AI Act role, prohibited/high-risk or obligation determination | `NOT RUN` | AI Act compliance/risk-class claim and unreviewed regulated use | Product/AI governance owner plus qualified counsel | Approved `O-AI` inventory and per-use classification |
| `GAP-NIS-01` | No NIS2 entity/national-transposition determination | `NOT RUN` | NIS2 compliance/out-of-scope claim | Security owner, management body and qualified counsel | Written jurisdiction/entity analysis and `O-NIS` records |
| `GAP-OWN-01` | Organizational privacy, ISMS and AI-governance roles are not formally assigned in repository evidence | Open | Program sign-off | Management body | Named role assignments and delegations in approved evidence system |
| `GAP-PROD-01` | Repository tests do not prove continuous production operation or statutory response | Open | Production/certification evidence claim | Operations and control owners | Environment-bound records, exercises, samples and independent review |
| `GAP-CUST-01` | Customer intended use, data, infrastructure and control allocation are unknown until onboarding | Customer-dependent | Customer deployment approval | Customer owner and Limes contract/product owner | Completed `O-CUST` control-allocation record |

No compliance risk is currently recorded as accepted. An accepted risk requires
an authorized owner, rationale, affected framework/control, residual risk,
compensating controls, approval date, expiry/review date and evidence link. A PR
author cannot silently convert a gap or failed control into accepted risk.

## Review Workflow And Claim Gate

1. Select the deployment profile and identify the contracting/operating entities.
2. Inventory data, AI systems/models, suppliers and intended purposes.
3. Assign GDPR and AI Act roles; determine ISO scope and NIS2 entity/jurisdiction.
4. Map applicable requirements to the control and evidence IDs above.
5. Collect environment/organization/customer evidence and record gaps or
   formally authorized, expiring accepted risks.
6. Obtain privacy/legal, security/ISMS, AI-governance, operations and customer
   owner review as applicable.
7. Obtain qualified counsel review for GDPR, AI Act and NIS2 scope/roles and a
   qualified certification specialist review for ISO/IEC 27001 before making
   external claims.
8. Re-review at the listed cadence and on material deployment, data, supplier,
   intended-purpose, legal or control changes.

Until steps 1-7 are evidenced, do not claim that Axis or a deployment is
ISO/IEC 27001 conformant/certified, GDPR compliant, AI Act compliant, NIS2
compliant or legally approved. “Automated,” “implemented” and “reviewed” in
this document describe evidence state only.

## Verification And Remaining Boundaries

- Focused documentation contract tests verify all four frameworks, deployment
  roles, control/evidence IDs, owner/cadence fields, customer allocation, gaps,
  accepted-risk rules and claim guardrails remain present.
- `make docs-check` verifies local evidence links.
- `NOT RUN`: qualified counsel review for GDPR, AI Act or NIS2 applicability,
  roles, national law or customer contracts.
- `NOT RUN`: qualified ISO/IEC 27001 certification-specialist review, ISMS
  implementation, internal audit, management review or accredited certification.
- `NOT RUN`: customer-specific control allocation, production evidence sampling,
  regulator/CSIRT notification exercise, DPIA or external penetration test.
