// src/routes/stt.ts
// Volet oral : relais de l'enregistrement du micro vers la reconnaissance vocale locale du brain.
import { Router } from "express";
import multer from "multer";
import { brainPostForm } from "../brainClient";

const router = Router();
const upload = multer({ storage: multer.memoryStorage(), limits: { fileSize: 10 * 1024 * 1024 } });

router.post("/stt", upload.single("file"), async (req, res) => {
  if (!req.file) {
    res.status(400).json({ error: "Aucun enregistrement reçu (champ 'file' attendu)." });
    return;
  }
  try {
    const form = new FormData();
    const blob = new Blob([new Uint8Array(req.file.buffer)], { type: req.file.mimetype });
    form.append("file", blob, req.file.originalname || "question.webm");
    form.append("lang", (req.body.lang as string) || "fr");

    const resp = await brainPostForm("/api/stt", form);
    const data = await resp.json();
    res.status(resp.status).json(data);
  } catch (err) {
    console.error("[gateway/stt] brain injoignable :", err);
    res.status(502).json({ error: "Le service brain (Python) est injoignable." });
  }
});

export default router;
