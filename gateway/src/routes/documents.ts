// src/routes/documents.ts
import { Router } from "express";
import multer from "multer";
import { brainPostForm } from "../brainClient";

const router = Router();
const upload = multer({ storage: multer.memoryStorage(), limits: { fileSize: 20 * 1024 * 1024 } });

router.post("/documents", upload.single("file"), async (req, res) => {
  if (!req.file) {
    res.status(400).json({ error: "Aucun fichier reçu (champ 'file' attendu)." });
    return;
  }
  try {
    const form = new FormData();
    const blob = new Blob([new Uint8Array(req.file.buffer)], { type: req.file.mimetype });
    form.append("file", blob, req.file.originalname);
    form.append("submittedBy", (req.body.submittedBy as string) || "");
    form.append("note", (req.body.note as string) || "");

    const resp = await brainPostForm("/api/documents", form);
    const data = await resp.json();
    res.status(resp.status).json(data);
  } catch (err) {
    console.error("[gateway/documents] brain unreachable:", err);
    res.status(502).json({ error: "Le service brain (Python) est injoignable." });
  }
});

export default router;
