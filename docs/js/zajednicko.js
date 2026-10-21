// Zajedničko za sve stranice: adresa API-ja, sesija advokata i bezbedan prikaz teksta.

const API_URL = (location.hostname === "localhost" || location.hostname === "127.0.0.1")
  ? "http://localhost:8000"
  : "https://lexintake-backend.onrender.com";

// Escape-uje tekst pre ubacivanja u innerHTML (podaci dolaze od klijenata i AI-ja)
function esc(vrednost) {
  return String(vrednost ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

// Escape + prelomi redova
function escRedovi(vrednost) {
  return esc(vrednost).replace(/\n/g, "<br>");
}

// FastAPI vraća detail kao tekst; za svaki slučaj podržava i listu grešaka
function porukaGreske(podaci, podrazumevano) {
  const detail = podaci && podaci.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length) return detail[0].msg || podrazumevano;
  return podrazumevano;
}

function sacuvajSesiju(rezultat) {
  localStorage.setItem("lex_token", rezultat.token);
  localStorage.setItem("lex_ime", rezultat.ime);
  localStorage.setItem("lex_email", rezultat.email);
  localStorage.setItem("lex_advokat_id", rezultat.advokat_id);
}

function odjava() {
  ["lex_token", "lex_ime", "lex_email", "lex_advokat_id"].forEach(k => localStorage.removeItem(k));
  window.location.href = "prijava.html";
}

function zahtevajPrijavu() {
  if (!localStorage.getItem("lex_token")) {
    // Posle prijave vraća korisnika na istu stranicu (npr. link iz mejla)
    const nazad = location.pathname.split("/").pop() + location.search;
    window.location.href = "prijava.html?nazad=" + encodeURIComponent(nazad);
    return false;
  }
  return true;
}

// Dozvoljava povratak samo na stranice aplikacije, ne na spoljne adrese
function stranicaPosle(podrazumevano = "tabla.html") {
  const nazad = new URLSearchParams(location.search).get("nazad") || "";
  return /^(tabla|podesavanja)\.html(\?[\w=&%-]*)?$/.test(nazad) ? nazad : podrazumevano;
}

// fetch sa tokenom advokata; na 401 odjavljuje korisnika
async function apiAdvokat(putanja, opcije = {}) {
  const zaglavlja = Object.assign({}, opcije.headers, {
    "Authorization": `Bearer ${localStorage.getItem("lex_token")}`
  });
  if (opcije.body && !zaglavlja["Content-Type"]) zaglavlja["Content-Type"] = "application/json";

  const odg = await fetch(`${API_URL}${putanja}`, Object.assign({}, opcije, { headers: zaglavlja }));
  if (odg.status === 401) {
    odjava();
    throw new Error("Sesija je istekla");
  }
  return odg;
}
