"use client";

import type { ReactNode } from "react";

export type Row = Record<string, any>;
export type Role = "ADMIN" | "DOCTOR" | "LAB" | "PHARMACY" | "RECEPTION";
export type Staff = { username: string; display_name: string; role: Role; doctor_id?: string };

/** Everything a desk needs from the shell. */
export type Ctx = {
  user: Staff;
  busy: boolean;
  selected: string;
  record: Row;          // GET /patients/{id}
  detail: Row;          // GET /encounters/{id} for the visit in view ({} when none)
  catalog: Row;         // GET /catalog
  act: (label: string, path: string, body?: Row) => Promise<Row | null>;
  load: (path: string) => Promise<Row | null>;
  choose: (patientId: string) => Promise<void>;
};

export const roles: { id: string; role: Role; name: string; task: string; icon: string }[] = [
  { id: "reception", role: "RECEPTION", name: "Reception", task: "Register, insurance, deposit", icon: "R" },
  { id: "doctor", role: "DOCTOR", name: "Doctor", task: "Consult, orders, discharge", icon: "+" },
  { id: "lab", role: "LAB", name: "Diagnostics", task: "Lab and radiology", icon: "L" },
  { id: "pharmacy", role: "PHARMACY", name: "Pharmacy", task: "Dispense medicine", icon: "Rx" },
  { id: "admin", role: "ADMIN", name: "Billing", task: "Audit, bill, payer, payment", icon: "₹" },
];
export const deskTitle: Record<Role, string> = {
  RECEPTION: "Reception desk", DOCTOR: "Doctor desk", LAB: "Diagnostics desk", PHARMACY: "Pharmacy desk", ADMIN: "Billing desk",
};

export const money = (n?: number) =>
  `${(n || 0) < 0 ? "−" : ""}₹${(Math.abs(n || 0) / 100).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
export const dateText = (s?: string) =>
  s ? new Date(s).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" }) : "";
export const dateTime = (s?: string) =>
  s ? new Date(s).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "";
// Local calendar date (not UTC), so early-morning IST still shows today's date.
export const today = (days = 0) => { const d = new Date(Date.now() + days * 86400000); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; };
export const initials = (name?: string) => (name || "").split(" ").map(part => part[0]).join("").slice(0, 2);

export async function api(path: string, init: RequestInit = {}) {
  const token = typeof window === "undefined" ? "" : sessionStorage.getItem("tiveri_token") || "";
  const response = await fetch(`/api${path}`, {
    cache: "no-store", ...init,
    headers: { ...(init.body ? { "Content-Type": "application/json" } : {}), ...(token ? { Authorization: `Bearer ${token}` } : {}), ...init.headers },
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(typeof body.detail === "string" ? body.detail : body.detail ? JSON.stringify(body.detail) : `Request failed (${response.status})`);
  return body;
}
export const post = (path: string, body: Row = {}) => api(path, { method: "POST", body: JSON.stringify(body) });

export function Tag({ children, tone = "blue" }: { children: ReactNode; tone?: string }) {
  return <span className={`p-tag ${tone}`}>{children}</span>;
}

export function Card({ title, sub, icon, children, wide = false, tone = "" }: { title: string; sub?: string; icon: string; children: ReactNode; wide?: boolean; tone?: string }) {
  return <section className={`p-card ${wide ? "p-wide" : ""} ${tone}`}>
    <div className="p-card-head"><span className="p-card-icon">{icon}</span><div><h3>{title}</h3>{sub && <small>{sub}</small>}</div></div>
    {children}
  </section>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="p-history">{children}</p>;
}

export const statusTone = (s?: string) =>
  ({ COMPLETED: "green", PERFORMED: "green", DISPENSED: "green", VERIFIED: "green", APPROVED: "green", SUCCEEDED: "green", PAID: "green", BILLED: "green",
     ORDERED: "amber", PARTIAL: "amber", PENDING: "amber", SUBMITTED: "amber", UNVERIFIED: "amber", OPEN: "amber", DISCHARGED: "blue", UNPAID: "amber",
     CANCELLED: "grey", REJECTED: "red", FAILED: "red", TIMEOUT: "red", NOT_ELIGIBLE: "red" } as Record<string, string>)[s || ""] || "blue";

export const payerText = (enc: Row) =>
  enc.payment_mode === "CASHLESS" ? `Cashless · ${enc.payer_label}` : enc.payment_mode === "REIMBURSEMENT" ? "Reimbursement (patient pays, claims later)" : "Self-pay";
