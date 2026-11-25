// The plain words of the first screen (PLAN §3.9, D-35). Fixed descriptions of DAIL's four invariants,
// written once, here. They describe what DAIL reports; they never decide anything.

export const NAMES = {
  "INV-SEC-001": { holds: "SSH is closed to the internet", broken: "SSH would be open to the internet" },
  "INV-SEC-002": { holds: "The database port is closed to the internet", broken: "the database port would be open to the internet" },
  "INV-SEC-003": { holds: "The database is not public", broken: "the database would be public" },
  "INV-FUNC-001": { holds: "The app can reach the database", broken: "the app would lose its connection to the database" },
};

const VERBS = { CREATED: "Adds", DELETED: "Deletes", MODIFIED: "Changes", REPLACED: "Replaces" };
const KINDS = {
  aws_security_group_rule: "rule", aws_security_group: "firewall group", aws_instance: "server",
  aws_db_instance: "database", aws_db_subnet_group: "database subnet group", aws_subnet: "subnet",
  aws_vpc: "network", aws_route_table: "route table", aws_route_table_association: "route table link",
  aws_internet_gateway: "internet gateway",
};

// One change of DAIL's identity stage, in plain words: [words, resource name].
export function changeWords(change) {
  const [type, ...rest] = String(change.address).split(".");
  return [`${VERBS[change.change_type] || "May change"} ${KINDS[type] || "resource"}`, rest.join(".")];
}

export function invariantOf(target) {
  const match = /^INVARIANT:(INV-[A-Z]+-\d+):\d+$/.exec(String(target));
  return match && NAMES[match[1]] ? match[1] : null;
}

function joined(parts) {
  return parts.length < 2 ? parts.join("") : `${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}`;
}

// The one-sentence reason, built only from DAIL's decision, its blocking conditions and the names above.
export function plainReason(decision) {
  if (decision.type === "PROMOTE") return "Accepted: DAIL proved that everything that must hold still holds.";
  const word = decision.type === "REJECT" ? "Rejected" : "Not accepted";
  const parts = [];
  for (const b of decision.blocking || []) {
    const id = invariantOf(b.target);
    const text = !id ? "one of DAIL's required checks did not pass"
      : b.code === "REQUIRED_CHECK_FAILED" ? NAMES[id].broken
        : `DAIL could not prove that ${NAMES[id].holds.charAt(0).toLowerCase()}${NAMES[id].holds.slice(1)}`;
    const fixed = text.replace("that sSH", "that SSH");
    if (!parts.includes(fixed)) parts.push(fixed);
  }
  if (!parts.length) parts.push("DAIL's rules do not allow it");
  return `${word}: ${joined(parts)}.`;
}

// The plain names of the invariants DAIL's blocking conditions name (for the feedback to the AI).
export function failedNames(decision) {
  return [...new Set((decision.blocking || []).map((b) => invariantOf(b.target)).filter(Boolean))].map((id) => NAMES[id].holds);
}

// What target-only checking (condition A) decided on the same patch.
export function normalChecker(decision) {
  if (decision === "PROMOTE") return ["A normal checker would have ", "accepted", " this fix."];
  if (decision === "REJECT") return ["A normal checker would have also ", "rejected", " this fix."];
  return ["A normal checker would have ", "reached no clear answer", " on this fix."];
}
