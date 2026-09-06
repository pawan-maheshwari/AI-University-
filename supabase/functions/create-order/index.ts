// AI Academia — create-order
//
// Creates a Razorpay order for a certification fee. The amount is fixed here on the
// server: if the browser could name the price, anyone could pay ₹1 for a certificate.
//
// Deploy:
//   supabase functions deploy create-order
// Secrets (shared with issue-certificate):
//   supabase secrets set RAZORPAY_KEY_ID=... RAZORPAY_KEY_SECRET=...

import { createClient } from "https://esm.sh/@supabase/supabase-js@2.45.0";

const ALLOWED_ORIGINS = [
  "https://ai-university.co.in",
  "https://www.ai-university.co.in",
  "http://localhost:8000",
];

// Must match EXPECTED_AMOUNT_PAISE in issue-certificate and Terms clause 8.
const FEE_PAISE = 199900;
const CURRENCY = "INR";

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

Deno.serve(async (req: Request) => {
  const origin = req.headers.get("origin");
  if (req.method === "OPTIONS") return new Response(null, { headers: corsHeaders(origin) });
  if (req.method !== "POST") return json({ error: "method_not_allowed" }, 405, origin);

  const KEY_ID = Deno.env.get("RAZORPAY_KEY_ID");
  const KEY_SECRET = Deno.env.get("RAZORPAY_KEY_SECRET");
  const SUPABASE_URL = Deno.env.get("SUPABASE_URL");
  const SERVICE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  if (!KEY_ID || !KEY_SECRET || !SUPABASE_URL || !SERVICE_KEY) {
    return json({ error: "server_misconfigured" }, 500, origin);
  }

  // Must be a signed-in learner — we tie the order to their user id.
  const jwt = (req.headers.get("Authorization") ?? "").replace(/^Bearer\s+/i, "");
  if (!jwt) return json({ error: "not_signed_in" }, 401, origin);

  const admin = createClient(SUPABASE_URL, SERVICE_KEY, {
    auth: { persistSession: false, autoRefreshToken: false },
  });
  const { data: userData, error: userErr } = await admin.auth.getUser(jwt);
  if (userErr || !userData?.user) return json({ error: "not_signed_in" }, 401, origin);
  const user = userData.user;

  let body: Record<string, string>;
  try { body = await req.json(); } catch { return json({ error: "bad_request" }, 400, origin); }

  const trackId = String(body.track_id ?? "");
  if (!TRACKS[trackId]) return json({ error: "unknown_track" }, 400, origin);

  // Already certified for this track? Don't take the money twice.
  const { data: existing } = await admin
    .from("certificates")
    .select("code")
    .eq("user_id", user.id)
    .eq("track_id", trackId)
    .maybeSingle();
  if (existing) {
    return json({ error: "already_certified", code: existing.code }, 409, origin);
  }

  const basic = btoa(`${KEY_ID}:${KEY_SECRET}`);
  // receipt is capped at 40 chars by Razorpay
  const receipt = `aiu_${trackId}_${user.id.slice(0, 8)}_${Date.now().toString(36)}`.slice(0, 40);

  const res = await fetch("https://api.razorpay.com/v1/orders", {
    method: "POST",
    headers: { Authorization: `Basic ${basic}`, "Content-Type": "application/json" },
    body: JSON.stringify({
      amount: FEE_PAISE,
      currency: CURRENCY,
      receipt,
      notes: { track_id: trackId, track_label: TRACKS[trackId], user_id: user.id },
    }),
  });

  if (!res.ok) {
    const detail = await res.text();
    console.error("razorpay order failed", res.status, detail);
    return json({ error: "order_create_failed" }, 502, origin);
  }

  const order = await res.json();
  return json({
    ok: true,
    order_id: order.id,
    amount: order.amount,
    currency: order.currency,
    key_id: KEY_ID,              // publishable; the secret never leaves this function
    track_label: TRACKS[trackId],
    name: (user.user_metadata?.name as string | undefined) ?? "",
    email: user.email ?? "",
  }, 200, origin);
});
