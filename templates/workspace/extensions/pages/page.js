// "Your pages": what a page extension is, and examples that open a session with the request already typed.
// This page is itself an extension (extensions/pages/): delete it in Settings -> Extensions when you no longer need it.

const TEXT = {
  en: {
    title: "Pages made for you, just by asking",
    lead: "A page extension is a whole page of the app, built for your business. Ask in any session; Harness writes it, it shows up in the menu, and updates never touch it.",
    try: "Try one",
    tryHint: "Click an example: a new session opens with the request already typed. Change it if you like, then send.",
    how: "How it works",
    steps: [
      ["Ask", "In any session: \"create a page that...\". Say what you want to see and do on it."],
      ["Harness builds it", "It writes the page in extensions/<name>/ on your server, with its own data if needed, and tests it."],
      ["Use it", "It appears under Extensions in the menu. Pin it to the sidebar, and ask for changes the same way: \"add a filter by city\"."],
    ],
    safe: "Your pages live in your workspace: updates never overwrite them, and the memory backup keeps them.",
    widgets: "Just a number or a list on the dashboard? Ask for a widget instead.",
    toDashboard: "Open the dashboard",
    self: "This page is itself an extension (extensions/pages/): remove it when you no longer need it.",
    settings: "Manage extensions",
    examples: [
      ["users", "Client file", "Contacts, notes, follow-ups due", "Create a page extension: a client file with contacts, notes and the follow-ups due. Ask me which fields I need."],
      ["package", "Order tracker", "Orders to pack, status, carrier", "Create a page extension to track my orders: what to pack today, status and carrier. Ask me where my orders come from."],
      ["calendar-days", "Content calendar", "Posts and videos, week by week", "Create a page extension: a content calendar with my planned articles, videos and posts, week by week."],
      ["receipt", "Invoices", "Sent, paid, overdue", "Create a page extension to follow my invoices: sent, paid, overdue, with the totals of the month."],
      ["book-open", "Reading list", "Books, notes, quotes", "Create a page extension for my reading: books to read and read, my notes and favourite quotes."],
      ["sparkles", "Something else", "Describe it, Harness asks the right questions", "I would like a new page in the app. Ask me the questions you need to build it."],
    ],
  },
  fr: {
    title: "Des pages sur mesure, simplement en les demandant",
    lead: "Une page d'extension est une page entière de l'app, construite pour votre activité. Demandez-la dans n'importe quelle session : Harness l'écrit, elle apparaît dans le menu, et les mises à jour n'y touchent jamais.",
    try: "Essayez",
    tryHint: "Cliquez sur un exemple : une nouvelle session s'ouvre avec la demande déjà écrite. Modifiez-la si vous voulez, puis envoyez.",
    how: "Comment ça marche",
    steps: [
      ["Demandez", "Dans n'importe quelle session : « crée une page qui… ». Dites ce que vous voulez y voir et y faire."],
      ["Harness la construit", "Il écrit la page dans extensions/<nom>/ sur votre serveur, avec ses propres données si besoin, et la teste."],
      ["Utilisez-la", "Elle apparaît sous Extensions dans le menu. Épinglez-la dans la barre latérale, et demandez des changements de la même façon : « ajoute un filtre par ville »."],
    ],
    safe: "Vos pages vivent dans votre espace de travail : les mises à jour ne les écrasent jamais, et la sauvegarde de la mémoire les garde.",
    widgets: "Juste un chiffre ou une liste sur le tableau de bord ? Demandez plutôt un widget.",
    toDashboard: "Ouvrir le tableau de bord",
    self: "Cette page est elle-même une extension (extensions/pages/) : supprimez-la quand vous n'en avez plus besoin.",
    settings: "Gérer les extensions",
    examples: [
      ["users", "Fichier clients", "Contacts, notes, relances à faire", "Crée une page d'extension : un fichier clients avec les contacts, des notes et les relances à faire. Demande-moi les champs dont j'ai besoin."],
      ["package", "Suivi des commandes", "À préparer, statut, transporteur", "Crée une page d'extension pour suivre mes commandes : ce qu'il faut préparer aujourd'hui, le statut et le transporteur. Demande-moi d'où viennent mes commandes."],
      ["calendar-days", "Calendrier éditorial", "Articles et vidéos, semaine par semaine", "Crée une page d'extension : un calendrier éditorial avec mes articles, vidéos et posts prévus, semaine par semaine."],
      ["receipt", "Factures", "Envoyées, payées, en retard", "Crée une page d'extension pour suivre mes factures : envoyées, payées, en retard, avec les totaux du mois."],
      ["book-open", "Bibliothèque", "Livres, notes, citations", "Crée une page d'extension pour mes lectures : livres à lire et lus, mes notes et mes citations préférées."],
      ["sparkles", "Autre chose", "Décrivez-la, Harness pose les bonnes questions", "Je voudrais une nouvelle page dans l'app. Pose-moi les questions utiles pour la construire."],
    ],
  },
};

// Styled with the app's UI kit (`ui-*` classes, see extensions/README.md): it follows the theme, the accent colour and
// the density by itself. Only the layout specific to this page is written here.
const CSS = `
.mxp .lead{max-width:68ch;margin-top:4px}
.mxp .head{display:flex;gap:14px;align-items:flex-start}
.mxp .notes{display:flex;flex-direction:column;gap:6px}
`;

function el(tag, attrs = {}, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "on") for (const [ev, fn] of Object.entries(v)) n.addEventListener(ev, fn);
    else if (k === "class") n.className = v;
    else n.setAttribute(k, v);
  }
  for (const c of kids.flat()) if (c != null) n.append(c);
  return n;
}

// "extensions/pages/" in a sentence -> a <code> chip
function withCode(text) {
  return text.split(/(extensions\/[^\s),.]+\/?)/).map((part, i) => (i % 2 ? el("code", { class: "ui-code" }, part) : part));
}

export function mount(root, ctx) {
  const T = TEXT[ctx.lang === "fr" ? "fr" : "en"];
  const icon = (name) => (ctx.icon ? ctx.icon(name) : null);
  let topic = "projects/system/topics/harness";
  ctx.api("topic").then((r) => { if (r && r.topic) topic = r.topic; }).catch(() => {});
  const ask = (prompt) =>
    ctx.navigate(`/sessions?path=${encodeURIComponent(topic)}&new=1&prompt=${encodeURIComponent(prompt)}`);

  const page = el("div", { class: "ui-page mxp" },
    el("style", {}, CSS),
    el("section", { class: "head" },
      el("div", { class: "ui-icon-box ui-lg" }, icon("layout-grid")),
      el("div", {}, el("h1", { class: "ui-h1" }, T.title), el("p", { class: "ui-muted lead" }, T.lead))),
    el("section", { class: "ui-section" },
      el("div", {}, el("h2", { class: "ui-h2" }, T.try), el("p", { class: "ui-muted" }, T.tryHint)),
      el("div", { class: "ui-grid" },
        T.examples.map(([name, title, sub, prompt]) =>
          el("button", { class: "ui-tile", type: "button", on: { click: () => ask(prompt) } },
            el("div", { class: "ui-icon-box" }, icon(name)),
            el("div", {}, el("b", {}, title), el("span", {}, sub)))))),
    el("section", { class: "ui-card" },
      el("h2", { class: "ui-h2" }, T.how),
      el("ol", { class: "ui-steps" },
        T.steps.map(([title, text], i) =>
          el("li", {}, el("span", { class: "ui-step-num" }, String(i + 1)),
            el("div", {}, el("b", { class: "ui-h3" }, title), el("p", { class: "ui-muted" }, ...withCode(text))))))),
    el("section", { class: "ui-callout" },
      icon("info"),
      el("div", { class: "notes" },
        el("p", {}, T.safe),
        el("p", {}, T.widgets, " ",
          el("button", { class: "ui-link", type: "button", on: { click: () => ctx.navigate("/") } }, T.toDashboard)),
        el("p", {}, ...withCode(T.self), " ",
          el("button", { class: "ui-link", type: "button", on: { click: () => ctx.navigate("/settings/extensions") } }, T.settings)))));

  root.replaceChildren(page);
  return () => root.replaceChildren();
}
