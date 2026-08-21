"use client";

import { useCallback, useEffect, useRef } from "react";

import { safeRandomUuid } from "@/lib/ids";

const ONTOLOGY_HISTORY_KEY = "__limesAxisOntologyHistory";
const ONTOLOGY_HISTORY_VERSION = 1;

type OntologyHistoryMarker = {
  depth: number;
  entityId: string | null;
  pathname: string;
  sessionId: string;
  version: typeof ONTOLOGY_HISTORY_VERSION;
};

type EntityNavigationMode = "push" | "replace";

type UseOntologyEntityHistoryOptions = {
  entityId: string | null;
  updateEntityId: (entityId: string, history: EntityNavigationMode) => void;
};

function locationEntityId(): string | null {
  if (typeof window === "undefined") {
    return null;
  }

  const value = new URLSearchParams(window.location.search).get("entity_id");
  return value !== null && value.length > 0 ? value : null;
}

function markerFromState(state: unknown): OntologyHistoryMarker | null {
  if (!state || typeof state !== "object" || Array.isArray(state)) {
    return null;
  }

  const marker = (state as Record<string, unknown>)[ONTOLOGY_HISTORY_KEY];
  if (!marker || typeof marker !== "object" || Array.isArray(marker)) {
    return null;
  }

  const candidate = marker as Record<string, unknown>;
  if (
    candidate.version !== ONTOLOGY_HISTORY_VERSION ||
    typeof candidate.sessionId !== "string" ||
    candidate.sessionId.length === 0 ||
    typeof candidate.pathname !== "string" ||
    !Number.isSafeInteger(candidate.depth) ||
    (candidate.entityId !== null && typeof candidate.entityId !== "string")
  ) {
    return null;
  }

  const depth = candidate.depth as number;
  const entityId = candidate.entityId as string | null;
  if (
    depth < 0 ||
    (depth === 0 && entityId !== null) ||
    (depth > 0 && entityId === null)
  ) {
    return null;
  }

  return {
    depth,
    entityId,
    pathname: candidate.pathname,
    sessionId: candidate.sessionId,
    version: ONTOLOGY_HISTORY_VERSION,
  };
}

function currentMarker(): OntologyHistoryMarker | null {
  if (typeof window === "undefined") {
    return null;
  }

  const marker = markerFromState(window.history.state);
  if (
    !marker ||
    marker.pathname !== window.location.pathname ||
    marker.entityId !== locationEntityId() ||
    marker.depth >= window.history.length
  ) {
    return null;
  }

  return marker;
}

function replaceCurrentMarker(marker: OntologyHistoryMarker) {
  if (typeof window === "undefined") {
    return;
  }

  const currentState = window.history.state;
  const preservedState =
    currentState && typeof currentState === "object" && !Array.isArray(currentState)
      ? currentState as Record<string, unknown>
      : {};

  window.history.replaceState(
    { ...preservedState, [ONTOLOGY_HISTORY_KEY]: marker },
    "",
    window.location.href,
  );
}

/**
 * Keeps ontology sheet traversal undoable without leaving duplicate entity
 * entries behind when the operator explicitly closes the sheet.
 *
 * A selection made from the explorer starts a marked history session. Peer
 * selections push within that session, and Close jumps back to its underlying
 * explorer entry. An entity URL opened directly has no marker, so peer changes
 * and Close use replace semantics and Back cannot reopen a stale entity.
 */
export function useOntologyEntityHistory({
  entityId,
  updateEntityId,
}: UseOntologyEntityHistoryOptions) {
  const pendingMarkerRef = useRef<OntologyHistoryMarker | null>(null);

  useEffect(() => {
    const pendingMarker = pendingMarkerRef.current;
    if (!pendingMarker) {
      return;
    }
    if (pendingMarker.entityId !== entityId) {
      pendingMarkerRef.current = null;
      return;
    }

    if (
      typeof window !== "undefined" &&
      pendingMarker.pathname === window.location.pathname &&
      pendingMarker.entityId === locationEntityId()
    ) {
      replaceCurrentMarker(pendingMarker);
    }
    pendingMarkerRef.current = null;
  }, [entityId]);

  const navigateToEntity = useCallback(
    (nextEntityId: string) => {
      if (nextEntityId.length === 0 || nextEntityId === entityId) {
        return;
      }

      const marker = currentMarker();
      if (entityId !== null && (!marker || marker.depth === 0)) {
        // The current entity came from a direct URL, not the explorer. Keep a
        // single replaceable entity entry so closing it cannot reopen peers.
        pendingMarkerRef.current = null;
        updateEntityId(nextEntityId, "replace");
        return;
      }

      if (typeof window === "undefined") {
        updateEntityId(nextEntityId, "push");
        return;
      }

      const sessionId = marker?.sessionId ?? safeRandomUuid();
      const depth = marker?.depth ?? 0;
      if (depth === 0) {
        replaceCurrentMarker({
          depth: 0,
          entityId: null,
          pathname: window.location.pathname,
          sessionId,
          version: ONTOLOGY_HISTORY_VERSION,
        });
      }

      pendingMarkerRef.current = {
        depth: depth + 1,
        entityId: nextEntityId,
        pathname: window.location.pathname,
        sessionId,
        version: ONTOLOGY_HISTORY_VERSION,
      };
      updateEntityId(nextEntityId, "push");
    },
    [entityId, updateEntityId],
  );

  const closeEntity = useCallback(() => {
    const marker = currentMarker();
    pendingMarkerRef.current = null;

    if (marker && marker.depth > 0 && typeof window !== "undefined") {
      window.history.go(-marker.depth);
      return;
    }

    // Direct links have no traversal root to return to, so remove the entity
    // query from the current entry instead of manufacturing a duplicate page.
    updateEntityId("", "replace");
  }, [updateEntityId]);

  return { closeEntity, navigateToEntity };
}
