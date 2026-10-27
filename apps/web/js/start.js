// Create a test and open it in the exam console. Throws the API error so each screen can show it where it fits.
import { api } from "./api.js";

export async function startTest(body) {
  const t = await api("/tests", { method: "POST", body });
  const a = await api("/attempts", { method: "POST", body: { test_id: t.id } });
  location.hash = `#/exam/${a.id}`;
}

export const KIND = { full: "Full mock", topic: "Topic test", pyq: "Past paper", custom: "Retry mistakes", subject: "Subject test" };
export const kindLabel = (kind) => KIND[kind] || "Test";
