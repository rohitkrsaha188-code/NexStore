/* Authentication gate — NexStore
 * Handles: Sign In | Create Account | Forgot Password
 * Auth backends: Supabase (email+password, Google OAuth) + local dev fallback
 */
(() => {
  "use strict";

  const { $, fmtDateTime } = window.UI;
  let currentUser = null;
  let supabaseEnabled = false;

  // ── Panel switching ───────────────────────────────────────────────────────
  function showPanel(id) {
    ["login", "signup", "forgot"].forEach((name) => {
      const el = $(`#auth-panel-${name}`);
      if (el) {
        el.hidden = id !== name;
      }
    });
    // Clear all errors/success when switching panels
    ["auth-error", "signup-error", "signup-success", "forgot-error", "forgot-success"].forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.textContent = "";
    });
  }

  function setError(elId, msg) {
    const el = document.getElementById(elId);
    if (el) el.textContent = msg || "";
  }

  function setSuccess(elId, msg) {
    const el = document.getElementById(elId);
    if (el) el.textContent = msg || "";
  }

  function setLoading(submitId, textId, spinnerId, loading, label = "Sign in") {
    const btn = document.getElementById(submitId);
    const txt = document.getElementById(textId);
    const spin = document.getElementById(spinnerId);
    if (btn) btn.disabled = loading;
    if (txt) txt.textContent = loading ? "Please wait…" : label;
    if (spin) spin.hidden = !loading;
  }

  // ── Auth gate visibility ──────────────────────────────────────────────────
  function showGate(error) {
    $(`#auth-gate`).hidden = false;
    $(`#app-shell`).hidden = true;
    showPanel("login");
    if (error) setError("auth-error", error);
  }

  // ── User session ──────────────────────────────────────────────────────────
  function setUser(user) {
    currentUser = user;
    $(`#auth-gate`).hidden = true;
    $(`#app-shell`).hidden = false;

    const initial = (user.name || user.email || "?").trim().charAt(0).toUpperCase();
    const avatarHtml = user.picture
      ? `<img src="${user.picture}" alt="" referrerpolicy="no-referrer" />`
      : initial;

    for (const id of ["user-avatar", "profile-avatar"]) {
      const el = document.getElementById(id);
      if (el) el.innerHTML = avatarHtml;
    }
    $(`#user-name`).textContent = user.name || user.email || "User";
    $(`#dd-name`).textContent = user.name || user.email || "User";
    $(`#dd-email`).textContent = user.email || "";
    renderProfile(user);
  }

  function renderProfile(user) {
    const escape = (s) => {
      const d = document.createElement("div");
      d.textContent = s == null ? "" : String(s);
      return d.innerHTML;
    };
    const el = $(`#profile-name`);
    if (el) el.textContent = user.name || user.email;
    const em = $(`#profile-email`);
    if (em) em.textContent = user.email;
    const kv = $(`#profile-kv`);
    if (kv) {
      kv.innerHTML = `
        <span class="k">Full Name</span><span class="v">${escape(user.name)}</span>
        <span class="k">Email</span><span class="v">${escape(user.email)}</span>
        <span class="k">Authentication Provider</span><span class="v">${escape(user.provider || "—")}</span>
        <span class="k">User ID</span><span class="v">${escape(user.user_id)}</span>
        <span class="k">Account Created</span><span class="v">${fmtDateTime(user.created_at)}</span>
        <span class="k">Last Login</span><span class="v">${fmtDateTime(user.last_login)}</span>`;
    }
  }

  // ── Google button handler ─────────────────────────────────────────────────
  function handleGoogleClick() {
    if (supabaseEnabled) {
      window.location.href = window.VaultAPI.supabaseGoogleLoginUrl;
    } else {
      window.location.href = window.VaultAPI.googleLoginUrl;
    }
  }

  // ── Supabase OAuth callback (hash fragment) ───────────────────────────────
  async function handleSupabaseCallback() {
    const hash = window.location.hash;
    if (!hash) return false;
    const params = new URLSearchParams(hash.slice(1));
    const access_token = params.get("access_token");
    const refresh_token = params.get("refresh_token");
    if (!access_token) return false;
    // Clean the URL
    history.replaceState(null, "", window.location.pathname + window.location.search);
    try {
      const result = await window.VaultAPI.supabaseSession(access_token, refresh_token);
      if (result?.authenticated && result.user) {
        setUser(result.user);
        window.app?.refreshAll();
        return true;
      }
    } catch (err) {
      console.error("Supabase session exchange failed:", err);
    }
    return false;
  }

  // ── Sign in form ──────────────────────────────────────────────────────────
  function initSignInForm() {
    $(`#auth-form`)?.addEventListener("submit", async (e) => {
      e.preventDefault();
      setError("auth-error", "");
      const email = $(`#auth-email`).value.trim();
      const password = $(`#auth-password`).value;
      setLoading("auth-submit", "auth-submit-text", "auth-submit-spinner", true, "Sign in");
      try {
        let result;
        if (supabaseEnabled) {
          result = await window.VaultAPI.supabaseLogin(email, password);
        } else {
          result = await window.VaultAPI.devLogin(email, password);
        }
        if (result?.authenticated && result.user) {
          setUser(result.user);
          window.app?.refreshAll();
        }
      } catch (err) {
        const msg =
          err?.payload?.detail ||
          err?.payload?.message ||
          err?.message ||
          "Login failed. Please check your credentials.";
        setError("auth-error", msg);
      } finally {
        setLoading("auth-submit", "auth-submit-text", "auth-submit-spinner", false, "Sign in");
      }
    });
  }

  // ── Sign up form ──────────────────────────────────────────────────────────
  function initSignupForm() {
    $(`#signup-form`)?.addEventListener("submit", async (e) => {
      e.preventDefault();
      setError("signup-error", "");
      setSuccess("signup-success", "");
      const name = $(`#signup-name`)?.value.trim() || "";
      const email = $(`#signup-email`).value.trim();
      const password = $(`#signup-password`).value;
      const confirm = $(`#signup-confirm`).value;
      if (password !== confirm) {
        setError("signup-error", "Passwords do not match.");
        return;
      }
      if (password.length < 8) {
        setError("signup-error", "Password must be at least 8 characters.");
        return;
      }
      setLoading("signup-submit", "signup-submit-text", "signup-submit-spinner", true, "Create Account");
      try {
        if (!supabaseEnabled) {
          setError("signup-error", "Account creation requires Supabase to be configured. Use the demo login instead.");
          return;
        }
        const result = await window.VaultAPI.supabaseSignup(email, password, name);
        if (result?.authenticated && result.user) {
          setUser(result.user);
          window.app?.refreshAll();
        } else if (result?.requires_confirmation) {
          setSuccess("signup-success", result.message || "Account created! Check your email to confirm.");
        }
      } catch (err) {
        const msg =
          err?.payload?.detail ||
          err?.payload?.message ||
          err?.message ||
          "Sign up failed. Please try again.";
        setError("signup-error", msg);
      } finally {
        setLoading("signup-submit", "signup-submit-text", "signup-submit-spinner", false, "Create Account");
      }
    });
  }

  // ── Forgot password form ──────────────────────────────────────────────────
  function initForgotForm() {
    $(`#forgot-form`)?.addEventListener("submit", async (e) => {
      e.preventDefault();
      setError("forgot-error", "");
      setSuccess("forgot-success", "");
      const email = $(`#forgot-email`).value.trim();
      setLoading("forgot-submit", "forgot-submit-text", "forgot-submit-spinner", true, "Send Reset Link");
      try {
        const result = await window.VaultAPI.supabaseResetPassword(email);
        setSuccess("forgot-success", result?.message || "If that email exists, a reset link has been sent.");
        $(`#forgot-email`).value = "";
      } catch (err) {
        const msg = err?.payload?.detail || err?.message || "Request failed.";
        setError("forgot-error", msg);
      } finally {
        setLoading("forgot-submit", "forgot-submit-text", "forgot-submit-spinner", false, "Send Reset Link");
      }
    });
  }

  // ── Password eye toggle ───────────────────────────────────────────────────
  function initPasswordToggle() {
    $(`#auth-eye-toggle`)?.addEventListener("click", () => {
      const input = $(`#auth-password`);
      const showIcon = $(`#eye-show`);
      const hideIcon = $(`#eye-hide`);
      if (!input) return;
      const isText = input.type === "text";
      input.type = isText ? "password" : "text";
      if (showIcon) showIcon.hidden = !isText;
      if (hideIcon) hideIcon.hidden = isText;
    });
  }

  // ── Navigation ────────────────────────────────────────────────────────────
  function initPanelNavigation() {
    $(`#btn-go-signup`)?.addEventListener("click", () => showPanel("signup"));
    $(`#btn-go-login`)?.addEventListener("click", () => showPanel("login"));
    $(`#btn-go-login-2`)?.addEventListener("click", () => showPanel("login"));
    $(`#btn-forgot`)?.addEventListener("click", () => showPanel("forgot"));
    // Google buttons
    $(`#btn-google`)?.addEventListener("click", handleGoogleClick);
    $(`#btn-google-signup`)?.addEventListener("click", handleGoogleClick);
  }

  // ── User dropdown / logout ────────────────────────────────────────────────
  function initUserMenu() {
    const dropdown = $(`#user-dropdown`);
    $(`#btn-user`)?.addEventListener("click", (e) => {
      e.stopPropagation();
      dropdown?.classList.toggle("open");
      $(`#notif-dropdown`)?.classList.remove("open");
    });
    document.addEventListener("click", () => dropdown?.classList.remove("open"));
    dropdown?.querySelectorAll("[data-goto]").forEach((btn) =>
      btn.addEventListener("click", () => {
        dropdown.classList.remove("open");
        window.app?.switchView(btn.dataset.goto);
      }),
    );
    $(`#btn-logout`)?.addEventListener("click", async () => {
      try {
        await window.VaultAPI.logout();
      } catch {
        /* already gone */
      }
      window.location.reload();
    });
  }

  // ── Boot: check session + handle URL params ───────────────────────────────
  async function boot() {
    // Check for Supabase OAuth callback (hash fragment)
    const urlParams = new URLSearchParams(window.location.search);
    const supabaseCallback = urlParams.get("supabase_callback");
    if (supabaseCallback || window.location.hash.includes("access_token")) {
      const handled = await handleSupabaseCallback();
      if (handled) return;
    }
    // Check for auth errors from OAuth redirect
    const authError = urlParams.get("auth_error");
    if (authError) {
      history.replaceState(null, "", window.location.pathname);
    }

    let me;
    try {
      me = await window.VaultAPI.getMe();
    } catch {
      showGate("Backend unreachable — start the server with `python run.py`.");
      return;
    }

    supabaseEnabled = me.supabase_enabled === true;

    if (me.authenticated && me.user) {
      setUser(me.user);
      return;
    }

    showGate(authError ? decodeURIComponent(authError).replace(/_/g, " ") : "");
  }

  function init() {
    initSignInForm();
    initSignupForm();
    initForgotForm();
    initPasswordToggle();
    initPanelNavigation();
    initUserMenu();
  }

  window.Auth = {
    boot,
    init,
    get user() {
      return currentUser;
    },
  };
})();
