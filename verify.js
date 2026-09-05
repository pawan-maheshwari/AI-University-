/* AI Academia — certificate verification.
   Reads a credential ID from ?id= or the input box and asks Supabase whether it exists.
   Queries the public view `certificate_verification`, which exposes only holder name,
   track, issue date and status — never email, payment reference or user id. */
(function () {
  "use strict";

  var SUPABASE_URL = "https://octgqicycwaxfsxaswjf.supabase.co";
  // Anon key. Safe to publish: the view is read-only to anon and exposes no private columns.
  var SUPABASE_ANON_KEY = "REPLACE_WITH_YOUR_SUPABASE_ANON_KEY";

  var out = document.getElementById("out");
  var input = document.getElementById("code");
  var form = document.getElementById("form");

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  }
  function clear() { while (out.firstChild) out.removeChild(out.firstChild); }

  function message(text, hint) {
    clear();
    out.appendChild(el("p", "msg", text));
    if (hint) out.appendChild(el("div", "hint", hint));
  }

  function statusBlock(kind, glyph, title) {
    var wrap = el("div", "status " + kind);
    wrap.appendChild(el("div", "dot", glyph));
    var t = el("div");
    t.appendChild(el("strong", null, title));
    wrap.appendChild(t);
    return wrap;
  }

  function row(label, value, mono) {
    var r = el("div", "row");
    r.appendChild(el("dt", null, label));
    r.appendChild(el("dd", mono ? "code" : null, value));
    return r;
  }

  // Accepts AIU-TEEN-7K3M9X and tolerates spaces or lowercase.
  function normalise(raw) {
    return String(raw || "").trim().toUpperCase().replace(/\s+/g, "");
  }
  function looksValid(code) {
    return /^AIU-[A-Z]{3,6}-[A-Z0-9]{6,10}$/.test(code);
  }

  function formatDate(iso) {
    try {
      var d = new Date(iso);
      if (isNaN(d.getTime())) return iso;
      return d.toLocaleDateString("en-GB", { year: "numeric", month: "long", day: "numeric" });
    } catch (e) { return iso; }
  }

  function renderValid(rec) {
    clear();
    out.appendChild(statusBlock("ok", "\u2713", "Valid certificate"));
    var dl = el("dl");
    dl.appendChild(row("Awarded to", rec.holder_name));
    dl.appendChild(row("Track", rec.track_label));
    dl.appendChild(row("Issued", formatDate(rec.issued_at)));
    dl.appendChild(row("Credential", rec.code, true));
    out.appendChild(dl);
    out.appendChild(el("div", "hint",
      "This certificate recognises completion and assessed understanding of an AI Academia track. " +
      "It is not an accredited academic qualification and carries no credit."));
  }

  function renderRevoked(rec) {
    clear();
    out.appendChild(statusBlock("warn", "!", "Certificate revoked"));
    var dl = el("dl");
    dl.appendChild(row("Track", rec.track_label));
    dl.appendChild(row("Issued", formatDate(rec.issued_at)));
    dl.appendChild(row("Credential", rec.code, true));
    out.appendChild(dl);
    out.appendChild(el("div", "hint",
      "This credential was issued by AI Academia but has since been withdrawn. " +
      "It should not be relied on. Please contact us if you believe this is an error."));
  }

  function renderNotFound(code) {
    clear();
    out.appendChild(statusBlock("bad", "\u2717", "Not found"));
    out.appendChild(el("p", "msg",
      "No certificate with the ID " + code + " has been issued by AI Academia."));
    out.appendChild(el("div", "hint",
      "Check the ID for typing errors \u2014 the character after the second dash is the easiest to " +
      "mistake. If it is correct as printed, this certificate did not come from us."));
  }

  function renderError() {
    clear();
    out.appendChild(statusBlock("warn", "!", "Could not check right now"));
    out.appendChild(el("p", "msg",
      "The verification service did not respond. This does not mean the certificate is invalid \u2014 " +
      "please try again in a moment."));
  }

  function lookup(code) {
    if (!code) {
      message("Enter the credential ID printed on the certificate, or scan its QR code.");
      return;
    }
    if (!looksValid(code)) {
      clear();
      out.appendChild(statusBlock("bad", "\u2717", "Not a valid ID format"));
      out.appendChild(el("p", "msg",
        "AI Academia credential IDs look like AIU-TEEN-7K3M9X \u2014 three parts separated by dashes."));
      return;
    }

    message("Checking \u2026");

    var url = SUPABASE_URL + "/rest/v1/certificate_verification" +
      "?select=code,holder_name,track_label,issued_at,status" +
      "&code=eq." + encodeURIComponent(code) + "&limit=1";

    fetch(url, {
      headers: {
        apikey: SUPABASE_ANON_KEY,
        Authorization: "Bearer " + SUPABASE_ANON_KEY,
        Accept: "application/json"
      }
    })
      .then(function (r) {
        if (!r.ok) throw new Error("http " + r.status);
        return r.json();
      })
      .then(function (rows) {
        if (!rows || !rows.length) { renderNotFound(code); return; }
        var rec = rows[0];
        if (rec.status === "revoked") renderRevoked(rec);
        else renderValid(rec);
      })
      .catch(function () { renderError(); });
  }

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var code = normalise(input.value);
    input.value = code;
    // Keep the URL shareable, so a verified result can be linked to.
    try {
      history.replaceState(null, "", code ? "?id=" + encodeURIComponent(code) : location.pathname);
    } catch (err) {}
    lookup(code);
  });

  // Deep link: /verify.html?id=AIU-TEEN-7K3M9X (what the certificate QR encodes)
  var params = new URLSearchParams(location.search);
  var initial = normalise(params.get("id"));
  if (initial) {
    input.value = initial;
    lookup(initial);
  }
})();
