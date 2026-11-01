// src/routes/contribute.ts
import { Router } from "express";
import { brainPostJSON } from "../brainClient";

const router = Router();

router.post("/contribute", async (req, res) => {
  try {
    const resp = await brainPostJSON("/api/contribute", req.body);
    const data = await resp.json();
    res.status(resp.status).json(data);
  } catch (err) {
    console.error("[gateway/contribute] brain unreachable:", err);
    res.status(502).json({ error: "Le service brain (Python) est injoignable." });
  }
});

export default router;
