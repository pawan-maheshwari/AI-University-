// AI Academia — badge-assertion
//
// Serves an Open Badges 2.0 Assertion for a credential code, at the URL that is also
// the assertion's own `id`. That self-reference is what hosted verification means: a
// validator fetches the id and compares it with the copy baked into the PNG.
//
// Public by design — an Open Badge assertion is meant to be fetchable by any validator.
// It therefore exposes only what a badge must contain: the hashed recipient email, the
// badge class, the issue date and the status. Never the name, the payment, or the score.
//
// Deploy:  supabase functions deploy badge-assertion --no-verify-jwt
// (--no-verify-jwt matters: validators are anonymous and carry no user token.)

import { createClient } from "https://esm.sh/@supabase/supabase-js@2.45.0";

const SITE = "https://ai-university.co.in";
const OB_CONTEXT = "https://w3id.org/openbadges/v2";

const TRACKS: Record<string, string> = {
  kids: "little-explorers",
  teens: "ai-teens-studio",
  teachers: "ai-for-teachers",
  college: "campus-ai-track",
  early: "early-career-ai",
  mid: "mid-career-mastery",
  leaders: "executive-ai-lab",
  seniors: "ai-for-seniors",
};

function json(body: unknown, status: number) {
  return new Response(JSON.stringify(body, null, 2), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Access-Control-Allow-Origin": "*",          // validators are anonymous third parties
      "Access-Control-Allow-Headers": "apikey, authorization, content-type",
      "Cache-Control": "public, max-age=300",
    },
  });
}

async function sha256Hex(input: string): Promise<string> {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(input));
  return Array.from(new Uint8Array(buf)).map(b => b.toString(16).padStart(2, "0")).join("");
}

Deno.serve(async (req: Request) => {
  if (req.method === "OPTIONS") {
    return new Response(null, {
      headers: {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Headers": "apikey, authorization, content-type",
        "Access-Control-Allow-Methods": "GET, OPTIONS",
      },
    });
  }

  const url = new URL(req.url);
  const code = (url.searchParams.get("id") ?? "").trim().toUpperCase();
  if (!/^AIU-[A-Z]{3,6}-[A-Z0-9]{6,10}$/.test(code)) {
    return json({ error: "invalid_credential_id" }, 400);
  }

  const SUPABASE_URL = Deno.env.get("SUPABASE_URL");
  const SERVICE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  if (!SUPABASE_URL || !SERVICE_KEY) return json({ error: "server_misconfigured" }, 500);

  const admin = createClient(SUPABASE_URL, SERVICE_KEY, {
    auth: { persistSession: false, autoRefreshToken: false },
  });

  const { data: cert, error } = await admin
    .from("certificates")
    .select("code, user_id, track_id, track_label, issued_at, status")
    .eq("code", code)
    .maybeSingle();

  if (error) return json({ error: "lookup_failed" }, 502);
  if (!cert) return json({ error: "not_found" }, 404);

  const slug = TRACKS[cert.track_id];
  if (!slug) return json({ error: "unknown_track" }, 500);

  const assertionId = `${SUPABASE_URL}/functions/v1/badge-assertion?id=${encodeURIComponent(code)}`;

  // Recipient identity: salted hash of the email, per the spec. The plain email is
  // never published. The salt is the credential code, which is stable and already public.
  const { data: userRes } = await admin.auth.admin.getUserById(cert.user_id);
  const email = (userRes?.user?.email ?? "").trim().toLowerCase();
  const salt = code;
  const identity = email ? `sha256$${await sha256Hex(email + salt)}` : null;

  const assertion: Record<string, unknown> = {
    "@context": OB_CONTEXT,
    type: "Assertion",
    id: assertionId,
    badge: `${SITE}/openbadges/badge-${slug}.json`,
    issuedOn: new Date(cert.issued_at).toISOString(),
    verification: { type: "HostedBadge" },
    evidence: `${SITE}/verify.html?id=${encodeURIComponent(code)}`,
  };

  if (identity) {
    assertion.recipient = { type: "email", hashed: true, salt, identity };
  }

  // A revoked badge must still resolve. Returning 404 would look like a broken link;
  // the spec expects the assertion to say so itself.
  if (cert.status === "revoked") {
    return json({
      "@context": OB_CONTEXT,
      type: "Assertion",
      id: assertionId,
      revoked: true,
      revocationReason: "This credential has been withdrawn by AI Academia.",
    }, 410);
  }

  return json(assertion, 200);
});
