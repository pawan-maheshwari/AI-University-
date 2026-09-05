// AI Academia — issue-certificate
//
// Verifies a Razorpay payment server-side, then writes the certificate row and
// returns the credential code. This is the only path that may create a credential.
//
// The rule that matters: the browser never decides whether a payment succeeded.
// Razorpay's client callback can be replayed or forged, so we recompute the HMAC
// signature here with the key secret, which never leaves the server.
//
// Secrets to set:
//   supabase secrets set RAZORPAY_KEY_ID=... RAZORPAY_KEY_SECRET=...
// SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are injected automatically.
//
// Deploy:
//   supabase functions deploy issue-certificate

import { createClient } from "https://esm.sh/@supabase/supabase-js@2.45.0";

const ALLOWED_ORIGINS = [
  "https://ai-university.co.in",
  "https://www.ai-university.co.in",
];

// Fee in paise. Must match the amount used when the order was created, and the
// figure published in Terms clause 8.
const EXPECTED_AMOUNT_PAISE = 199900;

// Tracks that can be certified, and the label printed on the certificate.
const TRACKS: Record<string, string> = {
  kids: "Little Explorers",
  teens: "AI Teens Studio",
  teachers: "AI for Teachers",
  college: "Campus AI Track",
  early: "Early Career AI",
  mid: "Mid-Career Mastery",
  leaders: "Executive AI Lab",
  seniors: "AI for Seniors",
};

function corsHeaders(origin: string | null) {
  const allowed = origin && ALLOWED_ORIGINS.includes(origin) ? origin : ALLOWED_ORIGINS[0];
  return {
    "Access-Control-Allow-Origin": allowed,
    "Access-Control-Allow-Headers": "authorization, content-type",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Vary": "Origin",
  };
}

function json(body: unknown, status: number, origin: string | null) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...corsHeaders(origin), "Content-Type": "application/json" },
  });
}

/** Constant-time comparison, so a wrong signature cannot be found by timing. */
function safeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

async function hmacSha256Hex(secret: string, message: string): Promise<string> {
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const sig = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(message));
  return Array.from(new Uint8Array(sig))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

Deno.serve(async (req: Request) => {
  const origin = req.headers.get("origin");

  if (req.method === "OPTIONS") return new Response(null, { headers: corsHeaders(origin) });
  if (req.method !== "POST") return json({ error: "method_not_allowed" }, 405, origin);

  const RAZORPAY_KEY_SECRET = Deno.env.get("RAZORPAY_KEY_SECRET");
  const SUPABASE_URL = Deno.env.get("SUPABASE_URL");
  const SERVICE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  if (!RAZORPAY_KEY_SECRET || !SUPABASE_URL || !SERVICE_KEY) {
    return json({ error: "server_misconfigured" }, 500, origin);
  }

  // ---- 1. the caller must be a signed-in learner -------------------------
  const authHeader = req.headers.get("Authorization") ?? "";
  const jwt = authHeader.replace(/^Bearer\s+/i, "");
  if (!jwt) return json({ error: "not_signed_in" }, 401, origin);

  const admin = createClient(SUPABASE_URL, SERVICE_KEY, {
    auth: { persistSession: false, autoRefreshToken: false },
  });

  const { data: userData, error: userErr } = await admin.auth.getUser(jwt);
  if (userErr || !userData?.user) return json({ error: "not_signed_in" }, 401, origin);
  const user = userData.user;

  // ---- 2. read and sanity-check the request ------------------------------
  let body: Record<string, string>;
  try {
    body = await req.json();
  } catch {
    return json({ error: "bad_request" }, 400, origin);
  }

  const trackId = String(body.track_id ?? "");
  const orderId = String(body.razorpay_order_id ?? "");
  const paymentId = String(body.razorpay_payment_id ?? "");
  const signature = String(body.razorpay_signature ?? "");

  if (!TRACKS[trackId]) return json({ error: "unknown_track" }, 400, origin);
  if (!orderId || !paymentId || !signature) return json({ error: "missing_payment_fields" }, 400, origin);

  // ---- 3. verify the Razorpay signature ----------------------------------
  const expected = await hmacSha256Hex(RAZORPAY_KEY_SECRET, `${orderId}|${paymentId}`);
  if (!safeEqual(expected, signature.toLowerCase())) {
    return json({ error: "signature_mismatch" }, 400, origin);
  }

  // ---- 4. confirm with Razorpay that the payment is real, captured and
  //         for the right amount. The signature alone proves the fields were
  //         not tampered with; it does not prove the money arrived.
  const keyId = Deno.env.get("RAZORPAY_KEY_ID") ?? "";
  const basic = btoa(`${keyId}:${RAZORPAY_KEY_SECRET}`);
  const rzp = await fetch(`https://api.razorpay.com/v1/payments/${paymentId}`, {
    headers: { Authorization: `Basic ${basic}` },
  });
  if (!rzp.ok) return json({ error: "payment_lookup_failed" }, 502, origin);
  const payment = await rzp.json();

  if (payment.status !== "captured") return json({ error: "payment_not_captured" }, 400, origin);
  if (payment.order_id !== orderId) return json({ error: "order_mismatch" }, 400, origin);
  if (Number(payment.amount) !== EXPECTED_AMOUNT_PAISE) {
    return json({ error: "amount_mismatch" }, 400, origin);
  }

  // ---- 5. idempotency: never issue twice for one payment or one track ----
  const { data: existing } = await admin
    .from("certificates")
    .select("code, track_label, issued_at")
    .eq("user_id", user.id)
    .eq("track_id", trackId)
    .maybeSingle();

  if (existing) {
    return json({ ok: true, code: existing.code, track_label: existing.track_label,
                  issued_at: existing.issued_at, reissued: true }, 200, origin);
  }

  // ---- 6. allocate a code and write the row ------------------------------
  const { data: codeRow, error: codeErr } = await admin
    .rpc("generate_credential_code", { p_track_id: trackId });
  if (codeErr || !codeRow) return json({ error: "code_allocation_failed" }, 500, origin);

  const holderName =
    (typeof body.holder_name === "string" && body.holder_name.trim().slice(0, 80)) ||
    (user.user_metadata?.name as string | undefined) ||
    user.email?.split("@")[0] ||
    "AI Academia Learner";

  const { data: inserted, error: insErr } = await admin
    .from("certificates")
    .insert({
      code: codeRow,
      user_id: user.id,
      holder_name: holderName,
      track_id: trackId,
      track_label: TRACKS[trackId],
      payment_ref: paymentId,
      order_ref: orderId,
      amount_paise: Number(payment.amount),
    })
    .select("code, track_label, issued_at")
    .single();

  if (insErr) {
    // Unique violation: a parallel request won the race. Return that certificate.
    const { data: raced } = await admin
      .from("certificates")
      .select("code, track_label, issued_at")
      .eq("user_id", user.id)
      .eq("track_id", trackId)
      .maybeSingle();
    if (raced) return json({ ok: true, ...raced, reissued: true }, 200, origin);
    return json({ error: "issue_failed" }, 500, origin);
  }

  return json({ ok: true, ...inserted }, 200, origin);
});
