// src/routes/chat.ts
// Relaie la conversation vers le brain. Le corps comprend messages, lang, persona et clientId
// (identifiant aléatoire du navigateur, qui sert seulement à compter les usagers distincts
// d'une question d'investigation ; le brain le transforme en empreinte irréversible).
import { Router } from "express";
import { brainPostJSON } from "../brainClient";

const router = Router();

router.post("/chat", async (req, res) => {
  try {
    const resp = await brainPostJSON("/api/chat", req.body);
    const data = await resp.json();
    res.status(resp.status).json(data);
  } catch (err) {
    console.error("[gateway/chat] brain injoignable :", err);
    res.status(502).json({ error: "Le service brain (Python) est injoignable. Vérifiez qu'il est démarré (voir README)." });
  }
});

export default router;
