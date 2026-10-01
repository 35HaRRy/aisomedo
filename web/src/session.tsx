import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { api, ApiError } from "./api/client";
import type { ClientOut } from "./api/openapi";

interface Session {
  status: "loading" | "paired" | "unpaired" | "error";
  client: ClientOut | null;
  generation: number;
  restore(): Promise<void>;
  pair(code: string, name: string): Promise<void>;
  invalidate(): void;
}

const Context = createContext<Session | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<Pick<Session, "status" | "client" | "generation">>({
    status: "loading", client: null, generation: 0,
  });
  const generation = useRef(0);
  const flight = useRef<AbortController | null>(null);
  const invalidate = useCallback(() => {
    flight.current?.abort();
    setState({ status: "unpaired", client: null, generation: ++generation.current });
  }, []);
  const restore = useCallback(async () => {
    flight.current?.abort();
    const controller = new AbortController();
    flight.current = controller;
    const token = ++generation.current;
    setState({ status: "loading", client: null, generation: token });
    try {
      const client = await api.me(controller.signal);
      if (token === generation.current && !controller.signal.aborted)
        setState({ status: "paired", client, generation: token });
    } catch (error) {
      if (token !== generation.current || controller.signal.aborted) return;
      setState({ status: error instanceof ApiError && error.status === 401 ? "unpaired" : "error", client: null, generation: token });
    }
  }, []);
  const pair = useCallback(async (code: string, name: string) => {
    flight.current?.abort();
    const controller = new AbortController();
    flight.current = controller;
    const token = generation.current;
    await api.pair({ code: code.trim(), name: name.trim(), kind: "browser" }, controller.signal);
    if (token === generation.current && !controller.signal.aborted) await restore();
  }, [restore]);
  useEffect(() => {
    void restore();
    return () => { generation.current++; flight.current?.abort(); };
  }, [restore]);
  return <Context.Provider value={{ ...state, restore, pair, invalidate }}>{children}</Context.Provider>;
}

export function useSession(): Session {
  const session = useContext(Context);
  if (!session) throw new Error("SessionProvider required");
  return session;
}
