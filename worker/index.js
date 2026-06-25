/**
 * Cloudflare Worker - TempMail Pro IP Rotation Proxy
 *
 * Mọi request từ Render server sẽ đi qua Worker này.
 * Cloudflare có ~100,000+ IPs → mỗi request đến SmailPro từ IP khác nhau.
 * → Không bao giờ bị rate limit 429.
 *
 * Secrets cần set trong Cloudflare Dashboard hoặc wrangler:
 *   - XSRF_TOKEN       (cookie SmailPro)
 *   - SONJJ_SESSION     (cookie SmailPro)
 *   - API_KEY            (key bảo vệ worker, phải giống WORKER_API_KEY trên Render)
 */

const SMAILPRO_BASE = "https://smailpro.com";
const SONJJ_BASE = "https://api.sonjj.com";

export default {
    async fetch(request, env, ctx) {
        const url = new URL(request.url);
        const path = url.pathname;

        // ── CORS Headers ──
        const corsHeaders = {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, X-API-Key",
        };

        // Preflight
        if (request.method === "OPTIONS") {
            return new Response(null, { headers: corsHeaders });
        }

        // ── API Key Authentication ──
        const apiKey = request.headers.get("X-API-Key");
        if (!env.API_KEY || apiKey !== env.API_KEY) {
            return new Response(
                JSON.stringify({ error: "Unauthorized" }),
                { status: 401, headers: { "Content-Type": "application/json", ...corsHeaders } }
            );
        }

        // ── Route Requests ──
        try {
            // Health check
            if (path === "/" || path === "/health") {
                return jsonResponse({ status: "ok", timestamp: new Date().toISOString() }, 200, corsHeaders);
            }

            // GET /create?username=xxx
            if (path === "/create") {
                return await handleCreate(url, request, env, corsHeaders);
            }

            // POST /inbox/:email
            if (path.startsWith("/inbox/")) {
                const email = decodeURIComponent(path.replace("/inbox/", ""));
                return await handleInbox(email, request, env, corsHeaders);
            }

            // GET /sonjj/inbox?payload=xxx
            if (path === "/sonjj/inbox") {
                return await handleSonjjInbox(url, env, corsHeaders);
            }

            // GET /sonjj/message?payload=xxx&mid=xxx
            if (path === "/sonjj/message") {
                return await handleSonjjMessage(url, env, corsHeaders);
            }

            return jsonResponse({ error: "Not found" }, 404, corsHeaders);

        } catch (error) {
            return jsonResponse({ error: error.message }, 500, corsHeaders);
        }
    }
};

// ════════════════════════════════════════════════════════════════
//                           HANDLERS
// ════════════════════════════════════════════════════════════════

/**
 * Tạo email mới qua SmailPro
 * GET /create?username=random
 */
async function handleCreate(url, request, env, corsHeaders) {
    const username = url.searchParams.get("username") || "random";

    const smailUrl = new URL(`${SMAILPRO_BASE}/app/create`);
    smailUrl.searchParams.set("username", username);
    smailUrl.searchParams.set("type", "real");
    smailUrl.searchParams.set("domain", "gmail.com");
    smailUrl.searchParams.set("server", "2");

    const resp = await fetch(smailUrl.toString(), {
        method: "GET",
        headers: getSmailHeaders(env, request),
    });

    const data = await resp.json();

    return new Response(JSON.stringify(data), {
        status: resp.status,
        headers: { "Content-Type": "application/json", ...corsHeaders },
    });
}

/**
 * Lấy inbox qua SmailPro
 * POST /inbox/:email
 */
async function handleInbox(email, request, env, corsHeaders) {
    const body = await request.json().catch(() => ({}));

    const resp = await fetch(`${SMAILPRO_BASE}/app/inbox`, {
        method: "POST",
        headers: getSmailHeaders(env, request),
        body: JSON.stringify([{
            address: email,
            timestamp: parseInt(body.timestamp) || 0,
            key: body.key || "",
        }]),
    });

    const data = await resp.json();

    return new Response(JSON.stringify(data), {
        status: resp.status,
        headers: { "Content-Type": "application/json", ...corsHeaders },
    });
}

/**
 * Lấy inbox từ Sonjj API
 * GET /sonjj/inbox?payload=xxx
 */
async function handleSonjjInbox(url, env, corsHeaders) {
    const payload = url.searchParams.get("payload");
    if (!payload) {
        return jsonResponse({ error: "payload is required" }, 400, corsHeaders);
    }

    const sonjjUrl = new URL(`${SONJJ_BASE}/v1/temp_gmail/inbox`);
    sonjjUrl.searchParams.set("payload", payload);

    const resp = await fetch(sonjjUrl.toString(), {
        headers: { "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36" },
    });

    const data = await resp.json();

    return new Response(JSON.stringify(data), {
        status: resp.status,
        headers: { "Content-Type": "application/json", ...corsHeaders },
    });
}

/**
 * Lấy chi tiết message từ Sonjj API
 * GET /sonjj/message?payload=xxx&mid=yyy
 */
async function handleSonjjMessage(url, env, corsHeaders) {
    const payload = url.searchParams.get("payload");
    const mid = url.searchParams.get("mid");

    if (!payload || !mid) {
        return jsonResponse({ error: "payload and mid are required" }, 400, corsHeaders);
    }

    const sonjjUrl = new URL(`${SONJJ_BASE}/v1/temp_gmail/message`);
    sonjjUrl.searchParams.set("payload", payload);
    sonjjUrl.searchParams.set("mid", mid);

    const resp = await fetch(sonjjUrl.toString(), {
        headers: { "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36" },
    });

    const data = await resp.json();

    return new Response(JSON.stringify(data), {
        status: resp.status,
        headers: { "Content-Type": "application/json", ...corsHeaders },
    });
}

// ════════════════════════════════════════════════════════════════
//                           HELPERS
// ════════════════════════════════════════════════════════════════

/**
 * Headers chuẩn cho SmailPro (bao gồm cookies từ secrets hoặc override)
 */
function getSmailHeaders(env, request) {
    const headers = {
        "accept": "*/*",
        "accept-language": "en-US,en;q=0.9",
        "content-type": "application/json",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "referer": `${SMAILPRO_BASE}/temporary-email`,
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
    };

    // Cookies: ưu tiên override từ header, fallback về env secrets
    const xsrfToken = request?.headers?.get("X-Xsrf-Token-Override") || env.XSRF_TOKEN;
    const sonjjSession = request?.headers?.get("X-Sonjj-Session-Override") || env.SONJJ_SESSION;

    const cookies = [];
    if (xsrfToken) {
        cookies.push(`XSRF-TOKEN=${xsrfToken}`);
        headers["x-xsrf-token"] = xsrfToken;
    }
    if (sonjjSession) {
        cookies.push(`sonjj_session=${sonjjSession}`);
    }
    if (cookies.length > 0) {
        headers["cookie"] = cookies.join("; ");
    }

    return headers;
}

/**
 * Helper tạo JSON response
 */
function jsonResponse(data, status, corsHeaders) {
    return new Response(JSON.stringify(data), {
        status,
        headers: { "Content-Type": "application/json", ...corsHeaders },
    });
}
