/** Thin hand-written wrapper around the generated OpenAPI types (src/lib/api is generated). */
import createClient from "openapi-fetch";
import type { paths } from "./api/schema";

const TOKEN_KEY = "gigbid.token";

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string | null): void {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable: the session just won't persist */
  }
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly traceId: string | null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export const UNAUTHORIZED_EVENT = "gigbid:unauthorized";

export const api = createClient<paths>({ baseUrl: "" });

api.use({
  onRequest({ request }) {
    const token = getToken();
    if (token) request.headers.set("Authorization", `Bearer ${token}`);
    return request;
  },
});

function describe(error: unknown, status: number): string {
  if (error && typeof error === "object") {
    const e = error as { detail?: unknown; message?: unknown };
    if (typeof e.detail === "string" && e.detail) return e.detail;
    if (typeof e.message === "string") return e.message;
  }
  return `Request failed (${status})`;
}

/** Unwrap an openapi-fetch result or throw an ApiError (never swallow errors). */
export async function unwrap<T>(
  promise: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  let result;
  try {
    result = await promise;
  } catch (cause) {
    throw new ApiError("Cannot reach the server. Check your connection and retry.", 0, null);
  }
  const { data, error, response } = result;
  if (error !== undefined || data === undefined) {
    if (response.status === 401 && getToken()) window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
    throw new ApiError(describe(error, response.status), response.status, response.headers.get("x-trace-id"));
  }
  return data;
}

export function authHeaders(): Record<string, string> {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}
