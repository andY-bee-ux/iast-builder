// src/auth.ts
import crypto from "crypto";
import { Request, Response, NextFunction } from "express";

const activeSessions = new Set<string>();

export function login(password: string): string | null {
  const expected = process.env.ADMIN_PASSWORD;
  if (!expected) {
    throw new Error(
      "ADMIN_PASSWORD n'est pas défini. Copiez .env.example vers .env et définissez un mot de passe avant de démarrer."
    );
  }
  if (password !== expected) return null;
  const token = crypto.randomBytes(24).toString("hex");
  activeSessions.add(token);
  return token;
}

export function logout(token: string | null): void {
  if (token) activeSessions.delete(token);
}

export function requireAdmin(req: Request, res: Response, next: NextFunction): void {
  const header = req.headers.authorization || "";
  const token = header.startsWith("Bearer ") ? header.slice(7) : null;
  if (!token || !activeSessions.has(token)) {
    res.status(401).json({ error: "Non autorisé. Connectez-vous depuis /admin.html." });
    return;
  }
  next();
}
