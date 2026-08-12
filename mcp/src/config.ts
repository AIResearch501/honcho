import { Honcho } from "@honcho-ai/sdk";

export interface HonchoConfig {
  apiKey?: string;
  baseUrl: string;
  workspaceId: string;
}

export interface Env {
  HONCHO_API_URL?: string;
}

/**
 * Parse configuration from request headers and Worker env bindings.
 *
 * The Authorization bearer token is optional: self-hosted Honcho
 * instances may not require API keys. When absent, the SDK falls back to
 * its own auth handling (e.g. the HONCHO_API_KEY env var).
 *
 * The Honcho API URL is read from the `HONCHO_API_URL` env var when set,
 * allowing operators to run this Worker alongside a self-hosted Honcho
 * instance (see the "Self-Hosted Honcho" section in README.md). It is
 * intentionally not exposed as a request header: routing public requests
 * to an internal URL would be a latency and security regression.
 */
export function parseConfig(request: Request, env: Env = {}): HonchoConfig {
  const authHeader = request.headers.get("Authorization");
  const bearerMatch = authHeader?.trim().match(/^Bearer\s+(.*)$/i);
  const apiKey = bearerMatch ? bearerMatch[1].trim() : undefined;

  return {
    apiKey,
    baseUrl: env.HONCHO_API_URL?.trim() || "https://api.honcho.dev",
    workspaceId: request.headers.get("X-Honcho-Workspace-ID")?.trim() || "default",
  };
}

export function createClient(config: HonchoConfig): Honcho {
  return new Honcho({
    apiKey: config.apiKey,
    baseURL: config.baseUrl,
    workspaceId: config.workspaceId,
  });
}
