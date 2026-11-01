// src/routes/profile.ts
// Description publique du profil de domaine actif, relayée depuis le brain.
// L'interface de conversation s'en sert pour adapter ses textes au domaine.
import { Router } from "express";
import { brainGet } from "../brainClient";

const router = Router();

router.get("/profile", async (_req, res) => {
  try {
    const resp = await brainGet("/api/profile");
    res.status(resp.status).json(await resp.json());
  } catch (err) {
    res.status(502).json({ error: "Le service brain (Python) est injoignable." });
  }
});

export default router;
