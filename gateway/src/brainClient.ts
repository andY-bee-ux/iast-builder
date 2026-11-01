// src/brainClient.ts
// Tous les appels vers le service brain portent l'en-tête X-Internal-Secret, pour que
// le brain refuse les appels qui ne passent pas par cette gateway (brain/app/internal_auth.py).

const BRAIN_URL = process.env.BRAIN_URL || "http://localhost:8000";

function headers(extra: Record<string, string> = {}): Record<string, string> {
  return {
    "X-Internal-Secret": process.env.INTERNAL_SECRET || "",
    ...extra,
  };
}

export async function brainGet(path: string): Promise<Response> {
  return fetch(`${BRAIN_URL}${path}`, { headers: headers() });
}

export async function brainPostJSON(path: string, body: unknown): Promise<Response> {
  return fetch(`${BRAIN_URL}${path}`, {
    method: "POST",
    headers: headers({ "Content-Type": "application/json" }),
    body: JSON.stringify(body),
  });
}

export async function brainPutJSON(path: string, body: unknown): Promise<Response> {
  return fetch(`${BRAIN_URL}${path}`, {
    method: "PUT",
    headers: headers({ "Content-Type": "application/json" }),
    body: JSON.stringify(body),
  });
}

// Requête JSON générique (méthode quelconque), utilisée par le relais d'administration.
export async function brainJSON(method: string, path: string, body?: unknown): Promise<Response> {
  const init: RequestInit = { method, headers: headers(body === undefined ? {} : { "Content-Type": "application/json" }) };
  if (body !== undefined && method !== "GET" && method !== "HEAD") init.body = JSON.stringify(body);
  return fetch(`${BRAIN_URL}${path}`, init);
}

// Relais d'un envoi de fichier : Express (multer, stockage en mémoire) fournit le tampon,
// reconstruit ici en FormData. Ne pas fixer Content-Type : fetch pose lui-même la limite multipart.
export async function brainPostForm(path: string, form: FormData): Promise<Response> {
  return fetch(`${BRAIN_URL}${path}`, {
    method: "POST",
    headers: headers(),
    body: form as unknown as BodyInit,
  });
}

export { BRAIN_URL };
