export default async function handler(req: any, res: any) {
  const token = process.env.CAREER_OS_API_TOKEN;
  const renderUrl = process.env.CAREER_OS_RENDER_URL;

  if (!token || !renderUrl) {
    return res.status(500).json({
      error: "Vercel API proxy is not configured",
    });
  }

  const pathParts = req.query?.path;

  const path = Array.isArray(pathParts)
    ? pathParts.join("/")
    : String(pathParts || "");

  const incomingUrl = new URL(
    req.url || "/",
    `https://${req.headers.host}`
  );

  const targetUrl =
    `${renderUrl.replace(/\/$/, "")}/api/${path}` +
    incomingUrl.search;

  const headers: Record<string, string> = {
    Authorization: `Bearer ${token}`,
    Accept: req.headers.accept || "*/*",
  };

  if (req.headers["content-type"]) {
    headers["Content-Type"] = req.headers["content-type"];
  }

  const method = req.method || "GET";

  const response = await fetch(targetUrl, {
    method,
    headers,
    body:
      method === "GET" || method === "HEAD"
        ? undefined
        : typeof req.body === "string"
          ? req.body
          : JSON.stringify(req.body),
  });

  const contentType = response.headers.get("content-type");

  if (contentType) {
    res.setHeader("Content-Type", contentType);
  }

  const disposition = response.headers.get("content-disposition");

  if (disposition) {
    res.setHeader("Content-Disposition", disposition);
  }

  const body = Buffer.from(await response.arrayBuffer());

  return res.status(response.status).send(body);
}