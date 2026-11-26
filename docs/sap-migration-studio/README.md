# Meridian — SAP S/4HANA Migration Studio (AI Academia)

**An AI Academia executive tool · Co-created by PlanetAI LLP**

Live page: https://ai-university.co.in/sap-migration-studio.html · Source: `sap-migration-studio.html` · Listed in **Tools & Utilities** (`TOOLS` registry in `index.html`).

Meridian is a utility for teams moving from SAP ECC 6.0 to SAP S/4HANA. It is built around one idea: let tools take over the routine work, make complex analysis faster, and turn the results into recommended actions, so the team can spend its time on decisions.

It is a single self-contained HTML application. It runs fully in the browser with no server, no sign-in and no outbound calls, so landscape answers, ABAP source and master-data extracts never leave the user's machine. Work is kept in the browser's local storage and can be exported as JSON or CSV.

> Meridian is an independent planning and analysis aid. It does not replace SAP Readiness Check, Maintenance Planner, ATC with the S/4HANA readiness check variant, the Simplification Item Check, or the SAP Activate methodology. Use it to prepare for those tools, to make sense of their results and to plan around them. SAP, S/4HANA and related names are trademarks of SAP SE.

---

## 1. Modules

| Module | What it automates or speeds up | What you get |
|---|---|---|
| **Overview (command centre)** | Combines the results of every module | Readiness ring, live countdown to SAP maintenance deadlines, KPIs, and a ranked list of recommended actions |
| **Assess** | 18-question readiness assessment covering technical, custom code, data, finance and organisation | A score for each dimension, blockers and pre-projects, and a recommended approach (Brownfield, Greenfield or Selective Data Transition) with its reasons and a complexity rating |
| **Code** | Line-by-line ABAP scan for S/4HANA simplification patterns: Universal Journal (ACDOCA), MATDOC, VBUK/VBUP, KONV → PRCD_ELEMENTS, Business Partner/CVI, credit management, 40-character MATNR, LIS, native SQL, SELECT in LOOP, implicit sort order on HANA | Findings with severity, the recommended fix and an hours estimate; copy as CSV |
| **Data** | Profiles a customer or vendor CSV extract for Business Partner readiness | Readiness score, column completeness, invalid ISO codes and emails, names over 40 characters, missing tax numbers, likely duplicates, cleansing actions |
| **Mapping** | Upload an Excel (.xlsx/.xls) or CSV of ECC field mappings or an interface inventory; the type is detected from the headers and every sheet can be picked | A generated S/4HANA target for each row, its status (Unchanged, Changed, Custom, Replaced, Obsolete, Nearest, No match), a confidence score, and the **nearest S/4HANA equivalent** where the ECC object no longer exists or is not recommended; copy as CSV |
| **Roadmap** | Builds a plan from SAP Activate phases, scaled by approach, complexity, number of waves, mock conversions, hypercare length and contingency | Gantt chart with workstreams, milestones and SAP deadline lines, plus a table of phases, deliverables, owners and quality gates; copy as CSV for Excel or MS Project |
| **Risks** | A register pre-loaded with 15 risks seen on real programmes | Editable likelihood, impact and status, a 5×5 heat map, critical-risk count; copy as CSV |
| **Cutover** | Downtime estimator (SUM DMO, downtime-optimised DMO, downtime-optimised conversion) and a 19-step runbook | Downtime breakdown against the approved window, levers to shrink it, runbook progress |

### Getting started
1. Open https://ai-university.co.in/sap-migration-studio.html, or **Tools & Utilities → SAP S/4HANA Migration Studio** on AI Academia.
2. Work through **Assess** first. Its result drives the default approach and complexity in **Roadmap**.
3. Paste real ABAP (or load a `.abap`/`.txt` export) into **Code**, and a BP extract into **Data**.
4. Tune the **Roadmap** and **Cutover** inputs, review the **Risks**, then work from the **Overview** action list.
5. Use **Copy project JSON** to keep a snapshot or share it with the PMO.

---

## 2. Why the timing matters: SAP support deadlines

| Date | What happens |
|---|---|
| **31 Dec 2027** | Mainstream maintenance ends for SAP ERP 6.0 and the other Business Suite 7 core applications |
| **2028 – 2030** | Optional extended maintenance for EHP 6–8, at a premium of 2 percentage points on the maintenance basis |
| **After 2030** | Customer-specific maintenance only, for systems still on-premise |
| **2031 – 2033** | *SAP ERP, private edition, transition option*: a subscription for eligible large, complex customers. It requires EHP 8, a move to SAP ERP private edition on HANA before the end of 2030, and an SAP readiness check between 2028 and 2030. SAP states that it is **not** a maintenance extension. |

Industry surveys show how hard these projects are. A 2025 Horváth study of 200 companies found that more than 60% had deviations in budget, schedule or quality, and only 37 had finished their migration. Programmes that start late tend to finish after mainstream maintenance ends, so extended maintenance should be in the budget from the start.

---

## 3. Lessons from past migrations

| Case (public reporting) | What went wrong | Lesson built into Meridian |
|---|---|---|
| **Lidl (2011–2018)** | Abandoned an SAP programme after about €500M and seven years. A widely cited cause was refusing to adopt SAP's standard inventory valuation (retail price) and customising heavily to keep its own method (purchase price). | Fit-to-standard and clean core. Every deviation from standard goes to an executive design authority. *(Risk: "Re-customising S/4HANA to mirror legacy processes")* |
| **Haribo (2018)** | Converted 16 factories in 10 countries to S/4HANA. Supply-chain problems that followed contributed to a reported 25% drop in Gold Bear sales that year. | End-to-end, volume and supply-chain testing with key users; a phased roll-out; rehearsed cutover. *(Risks: testing, interfaces, hypercare)* |
| **Revlon (2018)** | An ERP consolidation after the Elizabeth Arden acquisition disrupted a major plant's shipments. The company disclosed material weaknesses and faced shareholder lawsuits. | A realistic timeline after a merger, readiness gates before go-live, and funded hypercare with exit criteria. *(Risk: "Weak hypercare")* |

Lessons that recur across many programmes:
- **It is a business transformation, not an IT upgrade.** Process owners have to own the design decisions.
- **Data is usually the critical path.** BP/CVI, Finance reconciliation and master-data quality decide whether the conversion can run at all.
- **Custom code is mostly dead weight.** Usage analysis often shows much of it is no longer used. Retire it before remediating it.
- **Downtime is measured, not guessed.** Only mock conversions on production-sized copies give numbers you can rely on.
- **Hypercare needs funding and exit criteria.** Stabilisation takes weeks, not days.

---

## 4. Best practices by phase (SAP Activate)

### Discover
- Run **SAP Readiness Check** and **Maintenance Planner** on a recent production copy. Repeat each quarter.
- Get the **Simplification Item list** for your release and map it to the modules you use.
- Decide the approach with business owners. Use Meridian's **Assess** to frame the trade-offs (Brownfield / Greenfield / Selective).
- Build a business case that includes the cost of extended maintenance if go-live could slip past 2027.

### Prepare
- Set up governance: an executive sponsor with decision rights, a design authority, a PMO and a change control board.
- **Start pre-projects early**: BP/CVI, new Asset Accounting, credit management migration, archiving, and Unicode conversion where needed.
- Switch on **SCMON / UPL** to measure custom code usage for 6–12 months.
- Convert a **sandbox** early. It shows the real issues sooner than any document can.

### Explore
- Run **fit-to-standard** workshops on the converted sandbox or a Best Practices system.
- Triage custom code into retire, adapt, replace with standard, or move to a BTP side-by-side extension (clean core).
- Agree data selection, cleansing rules and quality KPIs. Profile the data with Meridian's **Data** module.
- Design Fiori roles and authorisations alongside the processes, not afterwards.

### Realize
- Run a **remediation factory** using ATC findings and Meridian's **Code** report, and apply ABAP quick fixes where they are available.
- Plan **at least 2–3 mock conversions** on production-sized data. Record the timing of every step.
- Cover SIT, regression (automate it), integration contract tests, performance tests and UAT with real user roles.
- Reconcile Finance after every mock: balances, open items and asset values against baselines.

### Deploy
- Do a full **dress rehearsal** of the runbook, including business validation.
- Make the go/no-go call against evidence for each criterion, not on optimism.
- Finish role-based training before go-live and give access to the right users.

### Run
- Open a **hypercare war room** with KPIs (order-to-cash cycle time, open defects, interface backlog, job failures).
- Exit hypercare only when the criteria are met, then hand over to the run organisation.
- Keep an innovation backlog for after go-live, such as embedded analytics, AI scenarios and process mining.

---

## 5. Risks to plan for, and how to mitigate them

| # | Risk | Typical L × I | Mitigation |
|---|---|---|---|
| 1 | Custom code effort underestimated | 4 × 4 | ATC with the S/4 checks in Discover; retire unused code identified by SCMON/UPL; remediation factory |
| 2 | BP/CVI errors block the conversion | 4 × 5 | Run CVI as a pre-project; use the CVI cockpit; synchronise in production months ahead |
| 3 | Poor master data quality | 4 × 4 | Name data owners; set KPIs; profile and cleanse before each mock |
| 4 | Finance inconsistencies stop the FIN migration | 3 × 5 | Close periods; run reconciliation reports early; archive closed years; sign off each mock |
| 5 | Downtime exceeds the window | 3 × 5 | Archive first; use downtime-optimised DMO; measure in mocks; rehearse |
| 6 | Not enough E2E testing → supply disruption | 3 × 5 | Automated regression; volume and E2E tests with key users |
| 7 | Re-customising to mirror legacy | 3 × 5 | Fit-to-standard; clean core; executive sign-off on deviations |
| 8 | Interface failures | 3 × 4 | Interface inventory with an owner per interface; contract tests; monitoring |
| 9 | Add-ons not compatible | 2 × 4 | Check vendor certification early; uninstall or replace |
| 10 | Low Fiori adoption | 3 × 4 | OCM, a champions network, role-based training, adoption KPIs |
| 11 | Shortage of skills and SI capacity close to 2027 | 3 × 3 | Lock in capacity early; knowledge-transfer clauses |
| 12 | Scope creep | 4 × 3 | Convert technically first, innovate afterwards; change control board |
| 13 | Roles and authorisations not ready | 3 × 3 | Redesign roles from Explore; SoD checks; test with real roles |
| 14 | Weak hypercare | 3 × 4 | Funded 6–12 weeks; war room; exit criteria |
| 15 | Performance degradation | 2 × 3 | SQL Monitor; push code down to HANA; performance tests at production scale |

Scoring in Meridian: score = likelihood × impact. **15 or more** is critical, **8–14** high, **under 8** moderate. Critical open risks appear automatically in the Overview action list.

---

## 6. Configuring the roadmap

Meridian's **Roadmap** module produces the plan from these inputs:

| Input | Effect |
|---|---|
| **Start date** | Start of Discover |
| **Approach** | Base phase lengths in weeks (Discover / Prepare / Explore / Realize / Deploy): Brownfield 3/6/8/20/8 · Greenfield 4/8/12/28/8 · Selective 4/8/10/24/10. *Auto* uses the Assess result. |
| **Complexity** | Multiplies the base lengths: S ×0.7, M ×1.0, L ×1.35, XL ×1.7. *Auto* is derived from DB size, custom objects, interfaces, company codes and add-ons. |
| **Contingency** | Adds 0–20% to every phase |
| **Mock conversions** | 2–4 mocks spread across Realize, with the last one early in Deploy |
| **Rollout waves** | Each extra wave adds a roll-out window of roughly 12 weeks × the complexity factor after the first go-live |
| **Hypercare** | Length of the Run phase in weeks |

Workstreams generated alongside the phases: custom code remediation, BP/CVI and Finance pre-work (or data migration design for Greenfield), data cleansing, testing, change management and training, and cutover planning. Milestones: each mock, dress rehearsal, go-live and hypercare exit. Red dashed lines show **31 Dec 2027** and **31 Dec 2030** wherever they fall inside the plan.

The base durations are planning defaults taken from typical mid-size programmes. Calibrate them with your SI's estimates and your own sandbox results.

### Project plan template (what the generated table contains)

| Phase | Key deliverables (Brownfield) | Owner | Quality gate |
|---|---|---|---|
| Discover | Readiness Check, Maintenance Planner, simplification items, business case | Sponsor | Business case and approach signed off |
| Prepare | Set-up, SI onboarding, sandbox conversion, CVI/FIN pre-checks, ATC baseline, archiving | PMO + Basis | Sandbox converted; pre-checks green |
| Explore | Fit-to-standard, delta design, code triage, cleansing plan | Solution architect | Backlog baselined |
| Realize | Remediation, Fiori roles, integrations, mocks, SIT, regression, performance, UAT | Delivery lead | UAT exit; mock timings within the window |
| Deploy | Dress rehearsal, training, runbook, go/no-go, production conversion | Cutover manager | Go/no-go approved |
| Run | Hypercare, defect triage, KPIs, handover | Service delivery manager | Exit criteria met |

Greenfield and Selective variants are built in and switch with the approach.

---

## 7. Cutover and downtime model

Estimated downtime is the sum of these components:

- Ramp-down and backup: 4 h
- **Database migration** = DB size (GB) ÷ throughput (GB/h) × method factor (standard 1.0, downtime-optimised DMO 0.45, downtime-optimised conversion 0.3)
- SUM downtime phases: 6 h × factor
- **Finance data migration** = documents (M) ÷ rate (M/h) × factor
- Business validation, as entered
- Contingency %

This is a heuristic for early planning only. **Replace the defaults with the timings you measure in Mock 1 and Mock 2.** The runbook covers T−12 weeks through post go-live, and progress is saved as you tick off steps.

---

## 8. Code scanner coverage and limits

The scanner checks each line with regular expressions. Comment lines (starting with `*`) and text after `"` are ignored. It finds common patterns quickly, but it is not a parser and does not resolve dynamic SQL, includes or where-used. Its job is to triage code and estimate effort early. **ATC with the S/4HANA readiness check variant and the Simplification Item Check remain the authoritative checks.**

---

## 8a. Confidence scores

**Code conversion confidence** (Code module and Overview)
- Every finding has a *detection confidence*: how precise the matching rule is. Exact table or statement matches (VBUK, KONV, writes to FAGLFLEXT, EXEC SQL) score 90–95%. Heuristics such as LIS table names, NAST, 40-character MATNR buffers and SELECT-in-LOOP score 55–75%.
- *Conversion confidence* = 100 − Σ(severity weight × detection confidence), with weights High 6, Medium 3, Low 1, and a floor of 0.
- Above 80: light rework expected · 50–80: planned remediation · below 50: significant rework before Mock 1.

**Data conversion confidence** (Data module and Overview)
- Each record starts at 100 and loses points for problems: −25 per missing mandatory field, −30 if it is a likely duplicate and not the golden record, −15 for an invalid country code, −10 for an invalid email, −10 for a name over 40 characters, −10 for a missing tax number.
- Records are grouped as **Ready** (80 or more), **Review** (50–79) or **Blocked** (under 50). Dataset confidence is the average across records.
- Both scores feed the Overview action list when they fall below their thresholds.

---

## 8b. Data and interface mapping

**Field mapping** (columns: Table, Field, Description). Examples of the rules:
- BSIS/BSAS/BSID/BSAD/BSIK/BSAK, GLT0, FAGLFLEXT/A, COEP/COSP/COSS, ANEP/ANLC → **ACDOCA**, with field rules (BUKRS→RBUKRS, HKONT→RACCT, DMBTR→HSL, WRBTR→WSL, BUZEI→DOCLN, KOSTL→RCNTR, MONAT→POPER; HSL01–16 → HSL summed by POPER)
- MKPF/MSEG → **MATDOC** · KONV → **PRCD_ELEMENTS** · VBUK/VBUP → **VBAK/VBAP** (or LIKP/LIPS, VBRK/VBRP)
- KNA1/LFA1 → **Business Partner** (NAME1→BUT000-NAME_ORG1, STRAS→ADRC-STREET, STCD1→DFKKBPTAXNUM-TAXNUM, KUNNR→BUT000-PARTNER via CVI_CUST_LINK)
- KNKK/KNKA → **SAP Credit Management** (UKMBP_CMS_SGM / UKMBP_CMS) · KONA → condition contracts · CE1xxxx → account-based CO-PA in ACDOCA · LIS Sxxx → analytical CDS views
- Tables that are unchanged keep their name; MATNR is flagged for the 18 → 40 character extension; Z/Y tables and ZZ appends are marked Custom
- Unknown tables: the closest known table name (edit distance ≤ 2) or the description keywords give a **Nearest** suggestion at 45–50% confidence

**Interface inventory** (columns: Interface ID, Name, Technology, ECC object, Direction, Partner). Examples:
- DEBMAS/CREMAS → still processed through CVI; recommended **BusinessPartnerSUITEBulkReplicateRequest / API_BUSINESS_PARTNER**
- MATMAS → 40-character material fields · ORDERS, DESADV, INVOIC, ACC_DOCUMENT, MBGMCR → supported, with the matching released API given as the modern alternative
- BAPI_CUSTOMER/VENDOR_CREATE → **Replaced** by the Business Partner API · BAPI_PO_CREATE → BAPI_PO_CREATE1 · RFC_READ_TABLE → released CDS/OData · LSMW → **Migration Cockpit** · credit (FD32/KNKK) → **API_CRDTMBUSINESSPARTNER**
- Custom (Z/Y) or unrecognised objects: the interface name is checked for business keywords (customer, supplier, invoice, stock, sales order, purchase order, delivery, journal, price, credit, payment, profitability) to propose the nearest released API at 55–62% confidence

All suggestions should be validated in an S/4HANA sandbox and against the SAP Business Accelerator Hub. Excel files are read in the browser with SheetJS; nothing is uploaded anywhere.

---

## 9a. Quality and stress-test results (26 Nov 2026)

An automated Playwright suite (`docs/sap-migration-studio/stress_test.py`) was run against the build. **36 of 36 checks pass** after fixes.

| Area | What was tested | Result |
|---|---|---|
| Smoke | All 8 screens × desktop / tablet / 360 px phone × light / dark — render, no horizontal overflow, no script errors | Pass |
| Security | Script-injection payloads in ABAP, CSV cells, risk form, Excel cells **and** sheet names, search box | Pass: nothing executes, no markup injected |
| Volume | 50,000-line ABAP (≈ 1.0 s) · 20,000-record CSV (≈ 2.1 s) · 6,000-row Excel (≈ 0.5 s) · search over 6,000 rows (≈ 90 ms) | Pass. Lists cap at 500 cards; Copy exports everything |
| Robustness | Empty and header-only files, unclosed quotes, BOM + semicolon CSV (EU Excel), tab-separated paste, CRLF, ragged rows, corrupt .xlsx, title rows above the header, negative/zero/extreme cutover and plan inputs, deleting every risk | Pass |
| Storage | Corrupted or wrong-shaped saved data; storage blocked (private mode / strict iframe); reload round trip | Pass: bad data is repaired to defaults |
| Logic | Mapping and scanner rules spot-checked; comments, variable names and string literals are not flagged as findings | Pass |
| Accessibility | axe-core WCAG 2.0/2.1 A + AA on every screen, both themes | Pass: no violations |
| Hosting | Run under a strict content-security policy inside a sandboxed frame; Excel library loads from `vendor/` | Pass. When the clipboard is blocked, a copy window opens instead |
| Performance | Single 108 KB file; ready in ≈ 0.4 s | Pass |

**Defects found and fixed during testing:** DOM overload on very large inputs; semicolon CSV and BOM not parsed; Excel title rows treated as data and a 5,000-row cap; slow mapping search; corrupted saved data crashed the app; table names inside string literals flagged as findings; negative cutover inputs accepted; failed copying gave no way to get the export; colour contrast on blue buttons, tags and coloured figures below WCAG AA.

**Known limits:** rule-based, not a parser: confirm with ATC, Readiness Check and an S/4HANA sandbox. Data stays in one browser (use Copy project JSON to move it). Re-run `docs/sap-migration-studio/stress_test.py` after every change.

---

## 9. Technical notes
- One HTML file in AI Academia house style (ivory, cardinal #8C1515, gold #B8962E, EB Garamond/Georgia headings) with the liquid-glass layout kept.
- **No external requests.** The Excel reader (SheetJS 0.18.5, Apache-2.0) is vendored at `vendor/xlsx.full.min.js` and loaded only when someone uploads an .xlsx/.xls file, so the page stays light and works on locked-down corporate networks.
- Opens inside an iframe cleanly: the “← AI Academia” links hide themselves when framed, as on the other tools.
- State is kept in `localStorage` under keys starting `meridian.`. It stays in the browser and is never sent anywhere.
- The UI follows Apple-style glass design: translucent panels, ambient light, a sidebar that becomes a bottom tab bar on phones, and light and dark modes.
- Accessibility: 44 px touch targets, visible focus, and reduced motion respected.

---

## 10. Sources
- SAPinsider — SAP support deadlines 2027, 2030, 2033: https://sapinsider.org/blogs/sap-support-deadlines-2027-2030-2033/
- SAP News — SAP ERP, private edition, transition option: https://news.sap.com/?p=231556
- Crowe — SAP ECC support ends in 2027: https://www.crowe.com/id/insights/sap-ecc-support-ends-in-2027-what-leaders-should-do
- Forrester — SAP's additional support until 2033, with conditions: https://www.forrester.com/blogs/sap-offers-on-prem-erp-customers-additional-3-year-support-till-2033-with-conditions
- CIO.com — SAP customers struggle with S/4HANA migration (Horváth study): https://www.cio.com/article/3851772/sap-users-struggle-with-s4-hana-migration.html
- TechRepublic — Haribo S/4HANA migration: https://www.techrepublic.com/article/how-a-troubled-sap-s4hana-migration-caused-a-gummy-bear-shortage-in-germany/
- Third Stage Consulting — Lessons from the SAP failure at Lidl: https://www.thirdstage-consulting.com/blog/lessons-from-an-sap-failure-at-lidl/
- Whatfix — ERP implementation failures (Revlon): https://whatfix.com/blog/?p=18031

---

*Meridian · ECC → S/4HANA Migration Studio — Co-created by **PlanetAI LLP**.*
