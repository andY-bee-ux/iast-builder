// src/routes/admin.ts
// Routes d'administration. La connexion et la déconnexion sont traitées ici (auth.ts) ;
// toutes les autres routes /admin/* sont relayées telles quelles vers le brain, derrière
// requireAdmin. Deux routes reçoivent des fichiers (import d'ontologie, import de connecteur)
// et sont relayées en multipart ; les réponses non JSON (Turtle, JSONL, fichiers de version)
// sont transmises avec leur type d'origine.
import { Router, Request, Response } from "express";
import multer from "multer";
import { login, logout, requireAdmin } from "../auth";
import { brainJSON, brainPostForm } from "../brainClient";

const router = Router();
const upload = multer({ storage: multer.memoryStorage(), limits: { fileSize: 20 * 1024 * 1024 } });
const UNREACHABLE = { error: "Le service brain (Python) est injoignable." };

router.post("/admin/login", (req, res) => {
  try {
    const token = login(req.body?.password);
    if (!token) {
      res.status(401).json({ error: "Mot de passe incorrect." });
      return;
    }
    res.json({ token });
  } catch (err) {
    res.status(500).json({ error: (err as Error).message });
  }
});

router.post("/admin/logout", requireAdmin, (req, res) => {
  const header = req.headers.authorization || "";
  logout(header.startsWith("Bearer ") ? header.slice(7) : null);
  res.json({ ok: true });
});

// Transmet la réponse du brain au navigateur, JSON ou non.
async function forward(resp: globalThis.Response, res: Response): Promise<void> {
  const type = resp.headers.get("content-type") || "";
  res.status(resp.status);
  if (type.includes("application/json")) {
    res.json(await resp.json());
  } else {
    res.type(type || "application/octet-stream");
    const disposition = resp.headers.get("content-disposition");
    if (disposition) res.setHeader("Content-Disposition", disposition);
    res.send(Buffer.from(await resp.arrayBuffer()));
  }
}

function multipartRoute(brainPath: string, extraFields: string[]) {
  return async (req: Request, res: Response) => {
    if (!req.file) {
      res.status(400).json({ error: "Aucun fichier reçu (champ 'file' attendu)." });
      return;
    }
    try {
      const form = new FormData();
      form.append("file", new Blob([new Uint8Array(req.file.buffer)], { type: req.file.mimetype }), req.file.originalname);
      for (const f of extraFields) form.append(f, (req.body?.[f] as string) || "");
      await forward(await brainPostForm(brainPath, form), res);
    } catch (err) {
      console.error(`[gateway/admin] brain injoignable sur ${brainPath} :`, err);
      res.status(502).json(UNREACHABLE);
    }
  };
}

router.post("/admin/ontology/upload", requireAdmin, upload.single("file"), multipartRoute("/api/admin/ontology/upload", []));
router.post("/admin/connectors/import", requireAdmin, upload.single("file"), multipartRoute("/api/admin/connectors/import", ["preset", "mapping"]));

// Relais générique : GET, POST, PUT, DELETE sur /admin/*, chaîne de requête comprise.
router.all("/admin/*", requireAdmin, async (req, res) => {
  const path = "/api" + req.originalUrl.replace(/^\/api/, "");
  try {
    const body = ["GET", "HEAD"].includes(req.method) ? undefined : req.body;
    await forward(await brainJSON(req.method, path, body), res);
  } catch (err) {
    console.error(`[gateway/admin] brain injoignable sur ${req.method} ${path} :`, err);
    res.status(502).json(UNREACHABLE);
  }
});

export default router;
