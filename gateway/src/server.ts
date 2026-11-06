// src/server.ts
import "dotenv/config";
import express from "express";
import path from "path";

import chatRoutes from "./routes/chat";
import contributeRoutes from "./routes/contribute";
import documentsRoutes from "./routes/documents";
import adminRoutes from "./routes/admin";
import profileRoutes from "./routes/profile";
import sttRoutes from "./routes/stt";
import { BRAIN_URL } from "./brainClient";

const app = express();
const PORT = process.env.PORT || 3000;

app.use(express.json({ limit: "2mb" }));
app.use(express.static(path.join(__dirname, "..", "public")));

app.use("/api", chatRoutes);
app.use("/api", contributeRoutes);
app.use("/api", documentsRoutes);
app.use("/api", profileRoutes);
app.use("/api", sttRoutes);
app.use("/api", adminRoutes);

app.get("/api/health", async (req, res) => {
  try {
    const resp = await fetch(`${BRAIN_URL}/health`);
    const brainHealth = await resp.json();
    res.json({ ok: true, gateway: true, brain: brainHealth });
  } catch (err) {
    res.status(200).json({ ok: true, gateway: true, brain: null, brainError: "injoignable" });
  }
});

app.listen(PORT, () => {
  console.log(`IAST-Builder gateway running at http://localhost:${PORT}`);
  console.log(`Admin panel:              http://localhost:${PORT}/admin.html`);
  console.log(`Brain service expected at: ${BRAIN_URL}`);
  if (!process.env.ADMIN_PASSWORD) {
    console.warn("[gateway] ADMIN_PASSWORD n'est pas définie — le panneau d'administration sera inaccessible.");
  }
  if (!process.env.INTERNAL_SECRET) {
    console.warn("[gateway] INTERNAL_SECRET n'est pas définie — doit être identique à celle du service brain.");
  }
});
