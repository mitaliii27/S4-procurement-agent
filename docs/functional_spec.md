# Functional specification - Procurement Assistant (sample go-live deliverable)

*Written the way a customer-engagement spec would be: business need -> behaviour -> acceptance criteria. All volumes and thresholds are illustrative.*

## 1. Business context
Buyers spend time answering routine questions (what is in stock, who supplies it) and keying low-value requisitions. The assistant handles those through ERP APIs, and routes anything risky to a human.

## 2. In scope / out of scope
| In scope | Out of scope |
|---|---|
| Stock lookup by material (and plant) | Goods receipt, invoice verification, payments |
| Supplier/price lookup, cheapest or fastest selection | Contract negotiation, supplier onboarding |
| Create purchase requisition (below threshold) | Releasing/approving requisitions |
| Requisition status lookup | Multi-line requisitions, services procurement |

## 3. User stories & acceptance criteria
| ID | Story | Acceptance criteria |
|---|---|---|
| PA-1 | As a buyer I can ask for stock of a material | Returns quantity, unit and reorder point per plant; flags BELOW when stock < reorder point; unknown material -> clear "not found" |
| PA-2 | As a buyer I can ask who supplies a material | Lists suppliers cheapest first with price and delivery days |
| PA-3 | As a buyer I can say "if below reorder point, order N from the cheapest supplier" | Checks stock first; creates **no** requisition when stock is at/above reorder point |
| PA-4 | As a budget owner I need large orders held for approval | Requisitions above EUR 5,000 are **not** created without an approver; the user is told why |
| PA-5 | As a risk owner I need hard limits | Quantity > 10,000, unknown plant, or > 3 writes per session are refused regardless of how the request is phrased |
| PA-6 | As an auditor I can see what the agent did | Every tool call is written to an audit log with arguments and outcome |
| PA-7 | As a buyer I get asked when a request is ambiguous | Missing quantity or ambiguous material -> clarifying question, no tool writes |

## 4. Tool contracts
| Tool | Inputs | Writes? | Guardrail |
|---|---|---|---|
| `search_materials` | `query` | no | - |
| `check_stock` | `material`, `plant?` | no | - |
| `find_suppliers` | `material` | no | - |
| `create_purchase_requisition` | `material`, `quantity`, `supplier`, `plant`, `justification?` | **yes** | value, quantity, plant, write-count, supplier-must-supply-material |
| `get_requisition_status` | `pr_number` | no | - |

## 5. Policy table
| Parameter | Value | Verdict when breached |
|---|---|---|
| Approval threshold | EUR 5,000 | approval_required |
| Max quantity per requisition | 10,000 | denied |
| Permitted plants | 1010, 1020 | denied |
| Max writes per run | 3 | denied |

## 6. Non-functional requirements
- Upstream 502/503/504 and transport errors retried 3x with exponential backoff; persistent failure surfaces as an observation, not a crash.
- Agent loop capped at 8 steps.
- Every behaviour above is covered by a unit test or an eval case (`tests/`, `evals/cases.jsonl`).

## 7. Open items for a real engagement
Entity/field mapping to the customer's actual S/4HANA APIs; authentication via BTP Destination; which model/endpoint the customer approves; data-privacy review of what leaves the system prompt; approval workflow integration (here a callback).
