let role = "student";

const studentBtn = document.getElementById("studentBtn");
const teacherBtn = document.getElementById("teacherBtn");
const loginBtn = document.getElementById("loginBtn");
const loginError = document.getElementById("loginError");
const passwordInput = document.getElementById("password");
const togglePasswordBtn = document.getElementById("togglePasswordBtn");
const loginForm = document.getElementById("loginForm");
const openLoginBtn = document.getElementById("openLoginBtn");
const closeLoginBtn = document.getElementById("closeLoginBtn");
const loginPanel = document.getElementById("loginPanel");

function openLogin() {
  document.body.classList.add("login-open");
  loginPanel.hidden = false;
  loginPanel.setAttribute("aria-hidden", "false");
  openLoginBtn.setAttribute("aria-expanded", "true");
  window.setTimeout(() => {
    if (loginPanel.getAttribute("aria-hidden") === "false") {
      document.getElementById("email").focus();
    }
  }, 350);
}

function closeLogin() {
  document.body.classList.remove("login-open");
  loginPanel.setAttribute("aria-hidden", "true");
  openLoginBtn.setAttribute("aria-expanded", "false");
  loginError.hidden = true;
  openLoginBtn.focus();
  window.setTimeout(() => {
    if (loginPanel.getAttribute("aria-hidden") === "true") loginPanel.hidden = true;
  }, 350);
}

openLoginBtn.addEventListener("click", openLogin);
closeLoginBtn.addEventListener("click", closeLogin);

function syncRoleButtons() {
  const isStudent = role === "student";
  studentBtn.classList.toggle("active", isStudent);
  teacherBtn.classList.toggle("active", !isStudent);
  studentBtn.setAttribute("aria-selected", isStudent ? "true" : "false");
  teacherBtn.setAttribute("aria-selected", isStudent ? "false" : "true");
}

studentBtn.addEventListener("click", () => {
  role = "student";
  syncRoleButtons();
});

teacherBtn.addEventListener("click", () => {
  role = "teacher";
  syncRoleButtons();
});

togglePasswordBtn.addEventListener("click", () => {
  const reveal = passwordInput.type === "password";
  passwordInput.type = reveal ? "text" : "password";
  togglePasswordBtn.textContent = reveal ? "Hide" : "Show";
  togglePasswordBtn.setAttribute("aria-label", reveal ? "Hide password" : "Show password");
});

loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const email = document.getElementById("email").value.trim();
  const password = document.getElementById("password").value;

  if (!email || !password) {
    showError("Please enter both email and password.");
    return;
  }

  loginBtn.disabled = true;
  loginBtn.classList.add("is-loading");
  loginBtn.textContent = "Signing in...";
  loginError.hidden = true;
  console.log("login attempt", { email: email, role: role });

  try {
    const result = await ReadWiseAPI.login(email, password, role);
    console.log("login result:", result);
    console.log("login token stored", localStorage.getItem("readwise_auth_token_v1"));
    const user = result && result.user ? result.user : null;
    if (!user) throw new Error("Invalid login response.");

    await ReadWiseAPI.me({ forceRefresh: true });
    console.log("login auth verified for user", user.email, user.role);

    sessionStorage.setItem("role", user.role);
    if (user.student && user.student.id) {
      sessionStorage.setItem("studentId", user.student.id);
    } else {
      sessionStorage.removeItem("studentId");
    }

    if (user.role === "student") {
      const needsPreAssessment = !(user.student && user.student.preAssessmentCompleted);
      window.location.href = needsPreAssessment
        ? "/student-pre-assessment"
        : "/student-dashboard";
    } else {
      window.location.href = "/teacher-dashboard";
    }
  } catch (error) {
    showError(error.message || "Invalid credentials. Try again.");
  } finally {
    loginBtn.disabled = false;
    loginBtn.classList.remove("is-loading");
    loginBtn.textContent = "Login";
  }
});

function showError(message) {
  loginError.textContent = message || "Invalid credentials. Try again.";
  loginError.hidden = false;
}

document.getElementById("email").addEventListener("input", () => {
  loginError.hidden = true;
});

passwordInput.addEventListener("input", () => {
  loginError.hidden = true;
});

syncRoleButtons();
