"use client";

import { useState, type PointerEvent } from "react";
import type { ModelRouteTelemetry } from "@/lib/model-routing-demo";
import type { SourceState } from "@/lib/source-state";
import { SourcePill } from "@/components/ui/source-pill";

type RouteDependency = Pick<ModelRouteTelemetry, "provider_id" | "provider_name" | "model">;
export type RoutingFlowSelection = { providerId: string; model?: string };

type ModelGroup = { name: string; count: number };
type ProviderGroup = { id: string; name: string; count: number; models: ModelGroup[] };

/** Count route entries, retaining provider identity even when display names match. */
export function groupRoutingDependencies(routes: RouteDependency[]): ProviderGroup[] {
  const providers = new Map<string, { name: string; count: number; models: Map<string, number> }>();
  for (const route of routes) {
    const group = providers.get(route.provider_id) ?? {
      name: route.provider_name.trim() || route.provider_id.trim() || "Unknown provider",
      count: 0,
      models: new Map<string, number>(),
    };
    group.count += 1;
    const model = route.model.trim() ? route.model : "Unknown model";
    group.models.set(model, (group.models.get(model) ?? 0) + 1);
    providers.set(route.provider_id, group);
  }
  return [...providers].map(([id, group]) => ({
    id, name: group.name, count: group.count,
    models: [...group.models].map(([name, count]) => ({ name, count }))
      .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name)),
  })).sort((a, b) => b.count - a.count || a.id.localeCompare(b.id));
}

const routeCount = (count: number) => `${count.toLocaleString("en")} ${count === 1 ? "route" : "routes"}`;

function buildDependencyLayout(providers: ProviderGroup[]) {
  const palette = ["rgb(var(--signal))", "rgb(var(--positive))", "rgb(var(--warning))", "rgb(var(--muted))"];
  // Assign by identity, not route volume, so colors survive count/order changes.
  const colors = new Map([...providers].sort((a, b) => a.id.localeCompare(b.id))
    .map((provider, index) => [provider.id, palette[index % palette.length]]));
  const unit = Math.min(28, 160 / Math.max(1, ...providers.map((provider) => provider.count)));
  let offset = 0;
  const layout = providers.map((provider) => {
    const rows = provider.models.map((model) => ({
      ...model,
      height: Math.max(52, Math.ceil(model.name.length / 22) * 18 + 28, model.count * unit + 20),
    }));
    const height = Math.max(rows.reduce((total, row) => total + row.height, 0), Math.ceil(provider.name.length / 17) * 18 + 28);
    const top = offset;
    offset += height + 16;
    let modelTop = top;
    let sourceTop = top + (height - provider.count * unit) / 2;
    return {
      ...provider, top, height, color: colors.get(provider.id),
      rows: rows.map((row) => {
        const targetY = modelTop + row.height / 2;
        const sourceY = sourceTop + row.count * unit / 2;
        modelTop += row.height;
        sourceTop += row.count * unit;
        return { ...row, targetY, sourceY };
      }),
    };
  });
  return { layout, height: Math.max(1, offset - 16), unit };
}

export function ModelRoutingFlow({ routes, sourceState, onInspect }: {
  routes: RouteDependency[];
  sourceState: SourceState;
  onInspect?: (selection: RoutingFlowSelection) => void;
}) {
  const [selected, setSelected] = useState<RoutingFlowSelection | null>(null);
  const [preview, setPreview] = useState<RoutingFlowSelection | null>(null);
  const providers = groupRoutingDependencies(routes);
  const pairCount = providers.reduce((total, provider) => total + provider.models.length, 0);
  // Dense inventories retain every count in the list instead of an unreadable diagram.
  const showDiagram = pairCount > 0 && pairCount <= 12;
  const { layout, height, unit } = buildDependencyLayout(providers);
  function resolve(selection: RoutingFlowSelection | null) {
    const provider = providers.find((entry) => entry.id === selection?.providerId);
    if (!provider || !selection) return null;
    const model = selection.model === undefined ? null : provider.models.find((entry) => entry.name === selection.model);
    if (selection.model !== undefined && !model) return null;
    return { selection, provider, model, count: model?.count ?? provider.count };
  }
  const active = resolve(preview) ?? resolve(selected);
  const pinned = resolve(selected);
  const matches = (selection: RoutingFlowSelection | null, providerId: string, model?: string) =>
    selection?.providerId === providerId && selection.model === model;
  const emphasized = (providerId: string, model?: string) => !active ||
    (active.provider.id === providerId && (active.selection.model === undefined || model === undefined || active.selection.model === model));
  function controls(selection: RoutingFlowSelection) {
    return {
      onClick: () => setSelected(selection),
      onFocus: () => setPreview(selection),
      onBlur: () => setPreview(null),
      onPointerEnter: (event: PointerEvent) => { if (event.pointerType !== "touch") setPreview(selection); },
      onPointerLeave: () => setPreview(null),
      "aria-pressed": matches(selected, selection.providerId, selection.model),
    };
  }

  return (
    <section onKeyDown={(event) => { if (event.key === "Escape") { setSelected(null); setPreview(null); } }} aria-label="Routing dependencies" className="grid min-w-0 gap-3 rounded-2xl border border-line bg-surface p-4 dark:border-white/10">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="grid gap-1">
          <h2 className="m-0 font-display text-xl text-ink">Routing dependencies</h2>
          <p className="m-0 text-sm text-muted">{routes.length.toLocaleString("en")} configured {routes.length === 1 ? "route" : "routes"} · {providers.length} {providers.length === 1 ? "provider" : "providers"}</p>
        </div>
        <SourcePill state={sourceState} subject="model routing" />
      </div>
      <p className="m-0 text-xs leading-relaxed text-muted">Includes blocked routes. Width = configured routes.</p>
      {routes.length > 0 ? (
        <div className="flex min-h-12 flex-wrap items-center justify-between gap-3 rounded-xl bg-ink/4 px-3 py-2 dark:bg-white/5">
          <p className="m-0 min-w-0 break-words text-sm text-ink" role="status">
            {active ? `${active.provider.name}${active.model ? ` → ${active.model.name}` : ""} · ${routeCount(active.count)} configured` : "Select a provider or model to inspect its configured routes."}
          </p>
          <div className="flex shrink-0 flex-wrap gap-3">
            {pinned && onInspect ? <button type="button" className="min-h-9 text-sm font-medium text-signal underline-offset-4 hover:underline" onClick={() => onInspect(pinned.selection)}>{pinned.model ? "Inspect first matching route" : "View provider routes"}</button> : null}
            {active ? <button type="button" className="min-h-9 text-sm text-muted underline-offset-4 hover:underline" onClick={() => { setSelected(null); setPreview(null); }}>Reset selection</button> : null}
          </div>
        </div>
      ) : null}
      {routes.length === 0 ? <p className="m-0 text-sm text-muted">No configured routes to compare.</p> : <>
        {showDiagram ? (
          <div className="hidden max-h-[560px] overflow-auto sm:block" tabIndex={0} role="region" aria-label="Provider to model diagram">
            <div className="grid min-w-[760px] grid-cols-[180px_minmax(300px,1fr)_240px] gap-3 text-xs text-muted" aria-hidden="true">
              <span>Provider</span><span /><span>Model</span>
            </div>
            <div className="relative mt-3 grid min-w-[760px] grid-cols-[180px_minmax(300px,1fr)_240px] gap-3" style={{ height }}>
              <div className="relative">
                {layout.map((provider) => (
                  <button type="button" {...controls({ providerId: provider.id })} aria-label={`Select provider ${provider.name}`} key={provider.id} className="absolute flex w-full flex-col justify-center gap-1 rounded-lg px-2 text-left text-sm hover:bg-ink/4 aria-pressed:bg-signal/10 dark:hover:bg-white/5" style={{ top: provider.top, height: provider.height, opacity: emphasized(provider.id) ? 1 : 0.35 }}>
                    <span className="break-all font-medium leading-[18px] text-ink">{provider.name}</span>
                    <span className="tabular-nums text-muted">{routeCount(provider.count)}</span>
                  </button>
                ))}
              </div>
              <svg aria-hidden="true" className="h-full w-full" viewBox={`0 0 300 ${height}`} preserveAspectRatio="none">
                {layout.map((provider) => (
                  <g key={provider.id} style={{ color: provider.color }}>
                    {provider.rows.map((row) => (
                      <g key={row.name} opacity={emphasized(provider.id, row.name) ? 1 : 0.12}>
                        <path onClick={() => setSelected({ providerId: provider.id, model: row.name })} onPointerEnter={(event) => { if (event.pointerType !== "touch") setPreview({ providerId: provider.id, model: row.name }); }} onPointerLeave={() => setPreview(null)} d={`M 8 ${row.sourceY} C 130 ${row.sourceY}, 170 ${row.targetY}, 292 ${row.targetY}`} fill="none" stroke="currentColor" className={active && emphasized(provider.id, row.name) ? "cursor-pointer opacity-80" : "cursor-pointer opacity-40 dark:opacity-50"} strokeWidth={row.count * unit} />
                        <rect x="292" y={row.targetY - row.count * unit / 2} width="6" height={row.count * unit} rx="2" fill="currentColor" />
                      </g>
                    ))}
                    <rect opacity={emphasized(provider.id) ? 1 : 0.12} x="2" y={provider.top + (provider.height - provider.count * unit) / 2} width="6" height={provider.count * unit} rx="2" fill="currentColor" />
                  </g>
                ))}
              </svg>
              <div className="relative">
                {layout.flatMap((provider) => provider.rows.map((row) => (
                  <button type="button" {...controls({ providerId: provider.id, model: row.name })} aria-label={`Select ${row.name} from ${provider.name}`} key={JSON.stringify([provider.id, row.name])} className="absolute flex w-full flex-col justify-center gap-1 rounded-lg px-3 text-left text-sm hover:bg-ink/4 aria-pressed:bg-signal/10 dark:hover:bg-white/5" style={{ top: row.targetY - row.height / 2, height: row.height, opacity: emphasized(provider.id, row.name) ? 1 : 0.35 }}>
                    <span className="break-all font-medium leading-[18px] text-ink">{row.name}</span>
                    <span className="tabular-nums text-muted">{routeCount(row.count)}</span>
                  </button>
                )))}
              </div>
            </div>
          </div>
        ) : null}
        <dl className={`m-0 grid gap-4 ${showDiagram ? "sm:hidden" : ""}`} aria-label="Routes by provider and model">
          {providers.map((provider) => (
            <div key={provider.id} className="min-w-0 rounded-xl border border-line p-3 dark:border-white/10">
              <dt><button type="button" {...controls({ providerId: provider.id })} aria-label={`Select provider ${provider.name}`} className="flex min-h-11 w-full flex-wrap items-center justify-between gap-2 rounded-lg text-left text-sm font-medium text-ink aria-pressed:bg-signal/10"><span className="min-w-0 break-all">{provider.name}</span><span className="tabular-nums">{routeCount(provider.count)}</span></button></dt>
              <dd className="m-0 mt-3 grid gap-2">
                {provider.models.map((model) => (
                  <button type="button" {...controls({ providerId: provider.id, model: model.name })} aria-label={`Select ${model.name} from ${provider.name}`} key={model.name} className="flex min-h-11 items-center justify-between gap-3 rounded-lg text-left text-sm text-muted aria-pressed:bg-signal/10"><span className="min-w-0 break-all">{model.name}</span><span className="shrink-0 tabular-nums">{routeCount(model.count)}</span></button>
                ))}
              </dd>
            </div>
          ))}
        </dl>
      </>}
    </section>
  );
}
