// login.js · page controller for login.html
import {
  signIn, signUp, signInWithGoogle, sendPasswordReset,
  recordConsent, getSession, getAssuranceLevel, completeMfaChallenge,
  signOut, TURNSTILE_SITE_KEY
} from './aiu-auth.js';

const $ = (id) => document.getElementById(id);
const msg = $('msg');
const params = new URLSearchParams(location.search);
const nextUrl = params.get('next') || '/';

const views = {
  signin: { form: $('form-signin'), cap: 'cap-signin',
    h: 'Welcome back', s: 'Sign in to keep your progress across every zone.',
    toggle: 'Create an account', next: 'signup' },
  signup: { form: $('form-signup'), cap: 'cap-signup',
    h: 'Join AI Academia', s: 'One account for every zone, from Sprouts to the Executive Lab.',
    toggle: 'I already have an account', next: 'signin' },
  reset:  { form: $('form-reset'), cap: 'cap-reset',
    h: 'Reset your password', s: 'We will send a link to the email on your account.',
    toggle: 'Back to sign in', next: 'signin' },
  mfa:    { form: $('form-mfa'), cap: null,
    h: 'One more step', s: 'Open your authenticator app and enter the current code.' }
};

// ---------------------------------------------------------------------
// Turnstile: render one widget per form, lazily, and keep its token.
// If the script is blocked or missing we pass undefined, and Supabase
// simply rejects the call — which is the correct failure direction.
// ---------------------------------------------------------------------
let currentCap = 'cap-signin';
const widgets = {};   // capId -> turnstile widget id
const tokens  = {};   // capId -> token string

function renderCaptcha(capId) {
  if (!capId || widgets[capId] !== undefined) return;
  if (typeof window.turnstile === 'undefined') return;   // still loading
  widgets[capId] = window.turnstile.render(`#${capId}`, {
    sitekey: TURNSTILE_SITE_KEY,
    theme: 'dark',
    callback: (token) => { tokens[capId] = token; },
    'expired-callback': () => { tokens[capId] = undefined; },
    'error-callback':   () => { tokens[capId] = undefined; }
  });
}

function resetCaptcha(capId) {
  tokens[capId] = undefined;
  if (widgets[capId] !== undefined && window.turnstile) {
    window.turnstile.reset(widgets[capId]);
  }
}

// Turnstile loads async; retry until it is there.
(function waitForTurnstile(tries = 0) {
  if (window.turnstile) { renderCaptcha(currentCap); return; }
  if (tries < 50) setTimeout(() => waitForTurnstile(tries + 1), 200);
})();

// ---------------------------------------------------------------------
// View handling
// ---------------------------------------------------------------------
function show(name) {
  Object.values(views).forEach(v => { v.form.hidden = true; });
  const v = views[name];
  v.form.hidden = false;
  $('heading').textContent = v.h;
  $('subheading').textContent = v.s;

  const isMfa = name === 'mfa';
  $('switcher').hidden = isMfa;
  if (!isMfa) {
    $('btn-toggle').textContent = v.toggle;
    $('btn-toggle').dataset.view = v.next;
  }

  currentCap = v.cap;
  renderCaptcha(v.cap);
  clear();
}

const say = (t, k = 'err') => { msg.textContent = t; msg.className = `msg show ${k}`; };
const clear = () => { msg.className = 'msg'; msg.textContent = ''; };

function busy(form, on, label) {
  const b = form.querySelector('.primary');
  b.disabled = on;
  if (on) { b.dataset.label = b.textContent; b.textContent = label; }
  else if (b.dataset.label) b.textContent = b.dataset.label;
}

document.addEventListener('click', (e) => {
  const t = e.target.closest('[data-view]');
  if (t) show(t.dataset.view);
});

// ---------------------------------------------------------------------
// After a password succeeds, decide whether a second step is owed.
// ---------------------------------------------------------------------
async function finishOrChallenge() {
  const level = await getAssuranceLevel();
  if (level.currentLevel === 'aal1' && level.nextLevel === 'aal2') {
    show('mfa');
    $('mfa-code').focus();
    return false;
  }
  location.replace(nextUrl);
  return true;
}

// ---------------------------------------------------------------------
// Handlers
// ---------------------------------------------------------------------
$('form-signin').addEventListener('submit', async (e) => {
  e.preventDefault(); clear(); busy(e.target, true, 'Signing in…');
  try {
    await signIn({
      email: $('si-email').value.trim(),
      password: $('si-pass').value,
      captchaToken: tokens['cap-signin']
    });
    await finishOrChallenge();
  } catch (err) {
    say(err.message === 'Invalid login credentials'
      ? 'That email and password do not match. Try again, or reset your password.'
      : err.message);
    resetCaptcha('cap-signin');
    busy(e.target, false);
  }
});

$('form-signup').addEventListener('submit', async (e) => {
  e.preventDefault(); clear(); busy(e.target, true, 'Creating…');
  try {
    const { session } = await signUp({
      email: $('su-email').value.trim(),
      password: $('su-pass').value,
      displayName: $('su-name').value.trim(),
      captchaToken: tokens['cap-signup']
    });
    if (session) {
      await recordConsent('account', true);
      location.replace(nextUrl);
    } else {
      say('Check your inbox — we sent a link to confirm your email address.', 'ok');
      resetCaptcha('cap-signup');
      busy(e.target, false);
    }
  } catch (err) {
    say(err.message.includes('already registered')
      ? 'An account already uses that email. Sign in instead.'
      : err.message);
    resetCaptcha('cap-signup');
    busy(e.target, false);
  }
});

$('form-reset').addEventListener('submit', async (e) => {
  e.preventDefault(); clear(); busy(e.target, true, 'Sending…');
  try {
    await sendPasswordReset($('rs-email').value.trim(), tokens['cap-reset']);
    say('If that email has an account, a reset link is on its way.', 'ok');
  } catch (err) { say(err.message); }
  resetCaptcha('cap-reset');
  busy(e.target, false);
});

$('form-mfa').addEventListener('submit', async (e) => {
  e.preventDefault(); clear(); busy(e.target, true, 'Verifying…');
  try {
    await completeMfaChallenge($('mfa-code').value.trim());
    location.replace(nextUrl);
  } catch (err) {
    say('That code did not work. Codes expire every 30 seconds — try the next one.');
    $('mfa-code').value = '';
    $('mfa-code').focus();
    busy(e.target, false);
  }
});

$('mfa-cancel').addEventListener('click', signOut);

$('btn-google').addEventListener('click', async () => {
  try { await signInWithGoogle(); } catch (err) { say(err.message); }
});

// ---------------------------------------------------------------------
// Entry: handle arriving back from a magic link or OAuth redirect, and
// the ?step=mfa hand-off from requireAuth({ requireMfa: true }).
// ---------------------------------------------------------------------
(async () => {
  const session = await getSession();
  if (!session) { show('signin'); return; }
  if (params.get('step') === 'mfa') { show('mfa'); $('mfa-code').focus(); return; }
  await finishOrChallenge();
})();
