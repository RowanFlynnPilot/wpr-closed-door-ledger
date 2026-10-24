// Shared by both pages: data loading, formatting, the exemption names.

export async function loadJSON(path) {
  const res = await fetch(path, { cache: "no-cache" });
  if (!res.ok) throw new Error(`${path}: HTTP ${res.status}`);
  return res.json();
}

// Every value from the data is set as text, never parsed as HTML.
export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") node.className = v;
    else node.setAttribute(k, v);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

export const fmtInt = (n) => n.toLocaleString("en-US");

export function fmtDate(iso, opts = { month: "short", day: "numeric", year: "numeric" }) {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString("en-US", opts);
}

export function fmtDateTime(iso) {
  return new Date(iso).toLocaleString("en-US", {
    month: "long", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit",
    timeZone: "America/Chicago", timeZoneName: "short",
  });
}

// The only paragraph letters in s. 19.85(1).
export const EXEMPTIONS = {
  a: "Deliberating a case heard before the body",
  b: "Dismissal, demotion, licensing or discipline of an employee or licensee",
  c: "Employment, promotion, compensation or performance evaluation",
  d: "Probation or parole applications; crime detection or prevention strategy",
  e: "Buying property, investing funds, or business needing secrecy for competitive or bargaining reasons",
  ee: "Unemployment insurance council deliberations",
  eg: "Worker's compensation council deliberations",
  em: "Burial site locations",
  f: "Personal histories or preliminary personnel problems that could harm a reputation",
  g: "Conferring with legal counsel on litigation strategy",
  h: "Requests for confidential advice from elections or ethics bodies",
};
export const LETTERS = Object.keys(EXEMPTIONS);

export const isBargaining = (item) => item.exemptions.length === 0 && item.other_citations.some((c) => c.startsWith("19.86"));

export function showError(container, err) {
  container.replaceChildren(el("p", { class: "load-error" }, `Could not load the ledger's data (${err.message}).`));
}
