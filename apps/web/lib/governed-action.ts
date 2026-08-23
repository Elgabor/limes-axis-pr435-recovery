import type { IdentitySessionReadModel } from "./platform-overview";

/*
 * One derivation of who a governed console write acts as, shared by every
 * mutation surface (wizard, import panel, runs, lifecycle control). The API
 * rebinds actor identity to the verified OIDC principal and rejects
 * impersonation, so the fallback id only labels unauthenticated demo writes;
 * when the deployment enforces SSO and no session exists, the console blocks
 * the submission before it can fail server-side.
 */
export function deriveGovernedActor(
  identitySession: IdentitySessionReadModel | null,
  demoActorId: string,
): { actorId: string; ssoBlocked: boolean } {
  return {
    actorId: identitySession?.actor_id ?? demoActorId,
    ssoBlocked: Boolean(
      identitySession
      && identitySession.api_auth_required
      && !identitySession.authenticated,
    ),
  };
}
