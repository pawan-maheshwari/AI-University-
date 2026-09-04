// =====================================================================
//  aiu-auth.js  ·  v2  ·  AI Academia shared authentication module
//
//  Changes from v1:
//   · imports the vendored client from ./vendor/supabase.js, not a CDN
//   · every email-sending call carries a Turnstile captcha token
//   · MFA (TOTP) enrol / challenge / verify helpers
// =====================================================================

import { createClient } from './vendor/supabase.js';

// ---------------------------------------------------------------------
// CONFIG
// The anon key is PUBLIC by design and safe in this repo.
// The service_role key is NOT and must never appear in any file here.
// ---------------------------------------------------------------------
export const SUPABASE_URL       = 'https://octgqicycwaxfsxaswjf.supabase.co';
export const SUPABASE_ANON_KEY  = 'sb_publishable_MzsglSmQRtprAHzhIcOYrw_vYzCaBOZ';
export const TURNSTILE_SITE_KEY = 'YOUR-TURNSTILE-SITE-KEY';   // public, safe here

export const POLICY_VERSION = '2026-09-01';
export const LOGIN_PAGE = '/login.html';

export const supabase = createClient(SUPABASE_URL, SUPABASE_ANON_KEY, {
  auth: {
    flowType: 'pkce',
    persistSession: true,
    autoRefreshToken: true,
    detectSessionInUrl: true,
    storageKey: 'aiu.auth'
  }
});

// ---------------------------------------------------------------------
// Session
// ---------------------------------------------------------------------
export async function getSession() {
  const { data, error } = await supabase.auth.getSession();
  return error ? null : data.session;
}

export async function getUser() {
  const { data } = await supabase.auth.getUser();
  return data?.user ?? null;
}

/**
 * Gate a page. Returns the user, or redirects and never resolves.
 *
 * Hides UI only. A static site cannot enforce anything client-side.
 * Real protection is the RLS policies in schema.sql + mfa-policies.sql.
 */
export async function requireAuth({ redirect = true, requireMfa = false } = {}) {
  const session = await getSession();

  if (session?.user) {
    if (!requireMfa) return session.user;
    const level = await getAssuranceLevel();
    if (level.currentLevel === 'aal2' || level.nextLevel !== 'aal2') return session.user;
    // enrolled in MFA but has not completed the second step this session
    location.replace(`${LOGIN_PAGE}?step=mfa&next=${encodeURIComponent(location.pathname)}`);
    await new Promise(() => {});
  }

  if (redirect) {
    const back = encodeURIComponent(location.pathname + location.search + location.hash);
    location.replace(`${LOGIN_PAGE}?next=${back}`);
    await new Promise(() => {});
  }
  return null;
}

export function onAuthChange(handler) {
  const { data } = supabase.auth.onAuthStateChange((event, session) => {
    handler(session?.user ?? null, event);
  });
  return () => data.subscription.unsubscribe();
}

// ---------------------------------------------------------------------
// Sign in / up / out
// captchaToken becomes mandatory once captcha protection is switched on
// in the Supabase dashboard.
// ---------------------------------------------------------------------
export async function signUp({ email, password, displayName, captchaToken }) {
  const { data, error } = await supabase.auth.signUp({
    email,
    password,
    options: {
      captchaToken,
      data: { display_name: displayName },
      emailRedirectTo: `${location.origin}${LOGIN_PAGE}`
    }
  });
  if (error) throw error;
  return data;
}

export async function signIn({ email, password, captchaToken }) {
  const { data, error } = await supabase.auth.signInWithPassword({
    email, password, options: { captchaToken }
  });
  if (error) throw error;
  return data;
}

export async function signInWithMagicLink(email, captchaToken) {
  const { error } = await supabase.auth.signInWithOtp({
    email,
    options: { captchaToken, emailRedirectTo: `${location.origin}${LOGIN_PAGE}` }
  });
  if (error) throw error;
}

export async function signInWithGoogle() {
  // OAuth redirects away from the page, so no captcha token applies.
  const { error } = await supabase.auth.signInWithOAuth({
    provider: 'google',
    options: { redirectTo: `${location.origin}${LOGIN_PAGE}` }
  });
  if (error) throw error;
}

export async function sendPasswordReset(email, captchaToken) {
  const { error } = await supabase.auth.resetPasswordForEmail(email, {
    captchaToken,
    redirectTo: `${location.origin}/account.html?reset=1`
  });
  if (error) throw error;
}

export async function signOut() {
  await supabase.auth.signOut();
  location.href = '/';
}

// ---------------------------------------------------------------------
// MFA — time-based one-time passwords (Google Authenticator, Authy, 1Password)
// ---------------------------------------------------------------------

/** { currentLevel, nextLevel }. currentLevel 'aal1' with nextLevel 'aal2'
 *  means: this account has MFA and still owes the second step. */
export async function getAssuranceLevel() {
  const { data, error } = await supabase.auth.mfa.getAuthenticatorAssuranceLevel();
  if (error) throw error;
  return data;
}

export async function listFactors() {
  const { data, error } = await supabase.auth.mfa.listFactors();
  if (error) throw error;
  return data.totp ?? [];
}

/** Step 1 of enrolment. Returns { factorId, qrSvg, secret } — show the QR. */
export async function startMfaEnrolment(friendlyName = 'Authenticator') {
  const { data, error } = await supabase.auth.mfa.enroll({
    factorType: 'totp',
    friendlyName
  });
  if (error) throw error;
  return { factorId: data.id, qrSvg: data.totp.qr_code, secret: data.totp.secret };
}

/** Step 2. Six digits from the app. Throws if the code is wrong. */
export async function confirmMfaEnrolment(factorId, code) {
  const { data: ch, error: chErr } = await supabase.auth.mfa.challenge({ factorId });
  if (chErr) throw chErr;
  const { error } = await supabase.auth.mfa.verify({ factorId, challengeId: ch.id, code });
  if (error) throw error;
}

/** Used at sign-in time when the account already has a verified factor. */
export async function completeMfaChallenge(code) {
  const factors = await listFactors();
  const factor = factors.find(f => f.status === 'verified');
  if (!factor) throw new Error('No authenticator is set up on this account.');
  const { data: ch, error: chErr } = await supabase.auth.mfa.challenge({ factorId: factor.id });
  if (chErr) throw chErr;
  const { error } = await supabase.auth.mfa.verify({
    factorId: factor.id, challengeId: ch.id, code
  });
  if (error) throw error;
}

export async function removeMfaFactor(factorId) {
  const { error } = await supabase.auth.mfa.unenroll({ factorId });
  if (error) throw error;
}

// ---------------------------------------------------------------------
// Profile — low sensitivity
// ---------------------------------------------------------------------
export async function getProfile() {
  const user = await getUser();
  if (!user) return null;
  const { data, error } = await supabase
    .from('profiles')
    .select('id, display_name, avatar_seed, zone, locale')
    .eq('id', user.id).single();
  if (error) throw error;
  return data;
}

export async function updateProfile(fields) {
  const user = await getUser();
  if (!user) throw new Error('Sign in to save your profile.');
  const { error } = await supabase.from('profiles').update(fields).eq('id', user.id);
  if (error) throw error;
}

// ---------------------------------------------------------------------
// Confidential details — owner-only RLS, and aal2 once MFA is enrolled.
// Fetch only on the account page. Never into a global or localStorage.
// ---------------------------------------------------------------------
export async function getPrivateDetails() {
  const user = await getUser();
  if (!user) return null;
  const { data, error } = await supabase
    .from('profile_private')
    .select('full_name, date_of_birth, phone, school_or_org, city, country, guardian_email, guardian_verified')
    .eq('user_id', user.id).single();
  if (error) throw error;
  return data;
}

export async function savePrivateDetails(fields) {
  const user = await getUser();
  if (!user) throw new Error('Sign in to save your details.');
  const { error } = await supabase
    .from('profile_private').update(fields).eq('user_id', user.id);
  if (error) throw error;
}

// ---------------------------------------------------------------------
// Consent (DPDP Act 2023) — append-only
// ---------------------------------------------------------------------
export async function recordConsent(purpose, granted = true) {
  const user = await getUser();
  if (!user) return;
  await supabase.from('consent_events').insert({
    user_id: user.id, purpose, granted, policy_version: POLICY_VERSION
  });
}

// ---------------------------------------------------------------------
// Learner progress
// ---------------------------------------------------------------------
export async function saveProgress(toolId, state, score = null) {
  const user = await getUser();
  if (!user) return;
  const { error } = await supabase
    .from('progress').upsert({ user_id: user.id, tool_id: toolId, state, score });
  if (error) throw error;
}

export async function loadProgress(toolId) {
  const user = await getUser();
  if (!user) return null;
  const { data, error } = await supabase
    .from('progress').select('state, score, updated_at')
    .eq('user_id', user.id).eq('tool_id', toolId).maybeSingle();
  if (error) throw error;
  return data;
}

// ---------------------------------------------------------------------
// Data rights
// ---------------------------------------------------------------------
export async function exportMyData() {
  const { data, error } = await supabase.rpc('export_my_data');
  if (error) throw error;
  return data;
}

export async function eraseMyPrivateData() {
  const { error } = await supabase.rpc('erase_my_private_data');
  if (error) throw error;
}

export async function deleteMyAccount() {
  const { error } = await supabase.functions.invoke('delete-account');
  if (error) throw error;
  await supabase.auth.signOut();
  location.href = '/';
}

// ---------------------------------------------------------------------
// Header state for the 20-odd content pages.
// Built with DOM nodes, not innerHTML, so a strict CSP is happy and a
// display name can never inject markup.
// ---------------------------------------------------------------------
export function mountHeaderAuth(el) {
  const paint = (user) => {
    if (!el) return;
    el.textContent = '';
    const a = document.createElement('a');
    if (user) {
      a.href = '/account.html';
      a.textContent = user.user_metadata?.display_name || 'My account';
      const b = document.createElement('button');
      b.type = 'button';
      b.textContent = 'Sign out';
      b.addEventListener('click', signOut);
      el.append(a, b);
    } else {
      a.href = LOGIN_PAGE;
      a.textContent = 'Sign in';
      el.append(a);
    }
  };
  getUser().then(paint);
  onAuthChange(paint);
}
