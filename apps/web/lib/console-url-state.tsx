"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

type ConsoleUrlField<T> = {
  defaultValue: T;
  param: string;
  parse: (value: string) => T | null;
  serialize: (value: unknown) => string;
};

type ConsoleUrlSchema = Record<string, ConsoleUrlField<unknown>>;

type ConsoleUrlState<TSchema extends ConsoleUrlSchema> = {
  [TKey in keyof TSchema]: TSchema[TKey] extends ConsoleUrlField<infer TValue>
    ? TValue
    : never;
};

type ConsoleUrlStateUpdate<TSchema extends ConsoleUrlSchema> =
  | Partial<ConsoleUrlState<TSchema>>
  | ((current: ConsoleUrlState<TSchema>) => Partial<ConsoleUrlState<TSchema>>);

type ConsoleUrlStateUpdateOptions = {
  /**
   * Filters default to `replace` so typing and refinement do not flood browser
   * history. Use `push` for record traversal that operators should be able to
   * undo with Back/Forward.
   */
  history?: "push" | "replace";
};

type ConsoleUrlContextValue = {
  pathname: string;
  push: (search: string) => void;
  replace: (search: string) => void;
  search: string;
};

const ConsoleUrlContext = createContext<ConsoleUrlContextValue | null>(null);

export function stringUrlField(param: string, defaultValue = ""): ConsoleUrlField<string> {
  return {
    defaultValue,
    param,
    parse: (value) => value.trim() || null,
    serialize: String,
  };
}

/**
 * URL field for identifiers whose bytes are owned by another system. Unlike a
 * human-entered filter, an opaque identifier must not be normalized: leading
 * and trailing whitespace can be part of its identity.
 */
export function opaqueStringUrlField(
  param: string,
  defaultValue = "",
): ConsoleUrlField<string> {
  return {
    defaultValue,
    param,
    parse: (value) => value.length > 0 ? value : null,
    serialize: String,
  };
}

export function enumUrlField<const TValue extends string>(
  param: string,
  values: readonly TValue[],
  defaultValue: TValue,
): ConsoleUrlField<TValue> {
  const allowedValues = new Set<string>(values);

  return {
    defaultValue,
    param,
    parse: (value) => allowedValues.has(value) ? value as TValue : null,
    serialize: String,
  };
}

export function ConsoleUrlStateProvider({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const search = searchParams.toString();
  const replace = useCallback(
    (nextSearch: string) => {
      router.replace(nextSearch ? `${pathname}?${nextSearch}` : pathname, { scroll: false });
    },
    [pathname, router],
  );
  const push = useCallback(
    (nextSearch: string) => {
      router.push(nextSearch ? `${pathname}?${nextSearch}` : pathname, { scroll: false });
    },
    [pathname, router],
  );
  const value = useMemo(
    () => ({ pathname, push, replace, search }),
    [pathname, push, replace, search],
  );

  return <ConsoleUrlContext.Provider value={value}>{children}</ConsoleUrlContext.Provider>;
}

function readState<TSchema extends ConsoleUrlSchema>(
  schema: TSchema,
  search: string,
): ConsoleUrlState<TSchema> {
  const params = new URLSearchParams(search);
  const state = {} as ConsoleUrlState<TSchema>;

  for (const key of Object.keys(schema) as Array<keyof TSchema>) {
    const field = schema[key];
    const rawValue = params.get(field.param);
    state[key] = (
      rawValue === null ? field.defaultValue : field.parse(rawValue) ?? field.defaultValue
    ) as ConsoleUrlState<TSchema>[typeof key];
  }

  return state;
}

export function useConsoleUrlState<const TSchema extends ConsoleUrlSchema>(
  schema: TSchema,
): [
  ConsoleUrlState<TSchema>,
  (
    update: ConsoleUrlStateUpdate<TSchema>,
    options?: ConsoleUrlStateUpdateOptions,
  ) => void,
] {
  const context = useContext(ConsoleUrlContext);
  const [browserLocation, setBrowserLocation] = useState(() =>
    typeof window === "undefined" ? { pathname: "", search: "" } : {
      pathname: window.location.pathname,
      search: window.location.search.slice(1),
    },
  );

  useEffect(() => {
    if (context || typeof window === "undefined") {
      return;
    }

    const syncLocation = () => {
      setBrowserLocation({
        pathname: window.location.pathname,
        search: window.location.search.slice(1),
      });
    };
    window.addEventListener("popstate", syncLocation);
    return () => window.removeEventListener("popstate", syncLocation);
  }, [context]);

  const search = context?.search ?? browserLocation.search;
  const state = useMemo(() => readState(schema, search), [schema, search]);

  const setState = useCallback(
    (
      update: ConsoleUrlStateUpdate<TSchema>,
      options: ConsoleUrlStateUpdateOptions = {},
    ) => {
      const changes = typeof update === "function" ? update(state) : update;
      const params = new URLSearchParams(search);

      for (const key of Object.keys(changes) as Array<keyof TSchema>) {
        const field = schema[key];
        const value = changes[key];
        if (value === undefined) {
          continue;
        }
        if (Object.is(value, field.defaultValue)) {
          params.delete(field.param);
        } else {
          params.set(field.param, field.serialize(value));
        }
      }

      const nextSearch = params.toString();
      if (nextSearch === search) {
        return;
      }
      const historyMode = options.history ?? "replace";
      if (context) {
        context[historyMode](nextSearch);
        return;
      }
      if (typeof window !== "undefined") {
        const nextUrl = nextSearch
          ? `${browserLocation.pathname}?${nextSearch}`
          : browserLocation.pathname;
        window.history[`${historyMode}State`](window.history.state, "", nextUrl);
        setBrowserLocation((current) => ({ ...current, search: nextSearch }));
      }
    },
    [browserLocation.pathname, context, schema, search, state],
  );

  return [state, setState];
}
