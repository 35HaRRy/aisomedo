import type { DraftTransaction } from "../packages/drafts";

const rows = new Map<string, unknown>();
let quota = false;
export const draftMemory = {
  reset() { rows.clear(); quota = false; },
  failWrites() { quota = true; },
  transaction: (async (key, operation) => {
    const result = operation(structuredClone(rows.get(key) ?? null));
    if (result.write) {
      if (quota) throw new Error("quota");
      if (result.next === null) rows.delete(key); else rows.set(key, structuredClone(result.next));
    }
    return result.result;
  }) as DraftTransaction,
  entries: async (prefix: string): Promise<[string, unknown][]> => [...rows.entries()].filter(([key]) => key.startsWith(prefix)),
  clearIdentity: async (identity: { origin: string; clientId: number }) => {
    const prefix = JSON.stringify([identity.origin, identity.clientId]).slice(0, -1) + ",";
    for (const key of rows.keys()) if (key.startsWith(prefix)) rows.delete(key);
  },
};
