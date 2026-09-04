// account.js · page controller for account.html
import {
  requireAuth, getProfile, updateProfile,
  getPrivateDetails, savePrivateDetails,
  exportMyData, eraseMyPrivateData, deleteMyAccount, signOut,
  listFactors, startMfaEnrolment, confirmMfaEnrolment, removeMfaFactor,
  getAssuranceLevel
} from './aiu-auth.js';

const $ = (id) => document.getElementById(id);
const msg = $('msg');
const say = (t, k = 'ok') => { msg.textContent = t; msg.className = `msg show ${k}`; };
const nz = (v) => (v === '' ? null : v);

const PRIVATE_FIELDS = ['full_name','date_of_birth','phone','school_or_org','city','country','guardian_email'];

const user = await requireAuth();
$('who').textContent = user.email;

// ---------------------------------------------------------------------
// Profile
// ---------------------------------------------------------------------
const profile = await getProfile();
if (profile) {
  $('display_name').value = profile.display_name ?? '';
  $('zone').value = profile.zone ?? '';
}

$('save-profile').addEventListener('click', async (e) => {
  e.target.disabled = true;
  try {
    await updateProfile({ display_name: $('display_name').value.trim(), zone: nz($('zone').value) });
    say('Profile saved.');
  } catch (err) { say(err.message, 'err'); }
  e.target.disabled = false;
});

// ---------------------------------------------------------------------
// Two-step sign-in
// ---------------------------------------------------------------------
let pendingFactorId = null;

function showMfa(state) {
  $('mfa-none').hidden  = state !== 'none';
  $('mfa-enrol').hidden = state !== 'enrol';
  $('mfa-on').hidden    = state !== 'on';
}

async function refreshMfa() {
  const factors = await listFactors();
  const active = factors.find(f => f.status === 'verified');
  if (active) {
    $('mfa-name').textContent = active.friendly_name || 'Authenticator';
    $('mfa-on').dataset.factorId = active.id;
    showMfa('on');
  } else {
    showMfa('none');
  }
  return !!active;
}

$('mfa-start').addEventListener('click', async (e) => {
  e.target.disabled = true;
  try {
    // clear any half-finished attempt from a previous visit
    for (const f of await listFactors()) {
      if (f.status !== 'verified') await removeMfaFactor(f.id);
    }
    const { factorId, qrSvg, secret } = await startMfaEnrolment('AI Academia');
    pendingFactorId = factorId;

    // qrSvg is a data: URI — set it as an <img> src, never innerHTML
    const img = document.createElement('img');
    img.src = qrSvg;
    img.alt = 'QR code for your authenticator app';
    $('mfa-qr').textContent = '';
    $('mfa-qr').append(img);
    $('mfa-secret').textContent = secret;

    showMfa('enrol');
    $('mfa-code').focus();
  } catch (err) { say(err.message, 'err'); }
  e.target.disabled = false;
});

$('mfa-confirm').addEventListener('click', async (e) => {
  e.target.disabled = true;
  try {
    await confirmMfaEnrolment(pendingFactorId, $('mfa-code').value.trim());
    $('mfa-code').value = '';
    pendingFactorId = null;
    await refreshMfa();
    say('Two-step sign-in is on. Keep a backup of the key somewhere safe.');
  } catch (err) {
    say('That code did not work. Codes change every 30 seconds — try the next one.', 'err');
  }
  e.target.disabled = false;
});

$('mfa-abandon').addEventListener('click', async () => {
  if (pendingFactorId) { try { await removeMfaFactor(pendingFactorId); } catch {} }
  pendingFactorId = null;
  $('mfa-code').value = '';
  await refreshMfa();
});

$('mfa-remove').addEventListener('click', async (e) => {
  if (!confirm('Turn off two-step sign-in? Your account will be protected by password alone.')) return;
  e.target.disabled = true;
  try {
    await removeMfaFactor($('mfa-on').dataset.factorId);
    await refreshMfa();
    say('Two-step sign-in is off.');
  } catch (err) { say(err.message, 'err'); }
  e.target.disabled = false;
});

const mfaActive = await refreshMfa();

// ---------------------------------------------------------------------
// Private details — the database refuses these at aal1 once MFA is on,
// so reflect that in the UI rather than showing a raw error.
// ---------------------------------------------------------------------
const level = await getAssuranceLevel();
const unlocked = !mfaActive || level.currentLevel === 'aal2';

$('private-locked').hidden = unlocked;
$('private-fields').hidden = !unlocked;

if (unlocked) {
  try {
    const priv = await getPrivateDetails();
    if (priv) PRIVATE_FIELDS.forEach(k => { $(k).value = priv[k] ?? ''; });
  } catch (err) {
    $('private-fields').hidden = true;
    $('private-locked').hidden = false;
  }
}

$('save-private').addEventListener('click', async (e) => {
  e.target.disabled = true;
  try {
    const payload = {};
    PRIVATE_FIELDS.forEach(k => { payload[k] = nz($(k).value.trim()); });
    await savePrivateDetails(payload);
    say('Details saved.');
  } catch (err) { say(err.message, 'err'); }
  e.target.disabled = false;
});

// ---------------------------------------------------------------------
// Data rights
// ---------------------------------------------------------------------
$('export').addEventListener('click', async () => {
  try {
    const data = await exportMyData();
    const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }));
    const a = Object.assign(document.createElement('a'), { href: url, download: 'ai-academia-my-data.json' });
    a.click();
    URL.revokeObjectURL(url);
    say('Your data file has been downloaded.');
  } catch (err) { say(err.message, 'err'); }
});

$('erase').addEventListener('click', async () => {
  if (!confirm('Erase your private details? Your account and progress stay.')) return;
  try {
    await eraseMyPrivateData();
    PRIVATE_FIELDS.forEach(k => { $(k).value = ''; });
    say('Private details erased.');
  } catch (err) { say(err.message, 'err'); }
});

$('delete').addEventListener('click', async () => {
  if (!confirm('Delete your account and everything in it? This cannot be undone.')) return;
  try { await deleteMyAccount(); } catch (err) { say(err.message, 'err'); }
});

$('signout').addEventListener('click', signOut);
