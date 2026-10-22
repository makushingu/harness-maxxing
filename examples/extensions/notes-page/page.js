// Notes page - a full-page extension written as a plain ES module (no build step).
//
// The app imports /ext/notes-page/page.js and calls mount(el, ctx):
//   el   an empty <div> inside the app layout - render anything you like into it
//   ctx  { api(path, opts), navigate(route), theme: "dark" | "light", lang, t(key), icon(name) }
//        ctx.api("notes") -> fetch of /api/ext/notes-page/notes (auth + CSRF header handled),
//        resolves to the parsed JSON, rejects with an Error on HTTP errors.
// Return a cleanup function; it runs when the user leaves the page.
//
// The page sits inside the app's UI kit: `ui-*` classes (ui-card, ui-btn, ui-textarea, ui-muted...) give it the
// app's look, and follow the theme, the accent colour and the density. ctx.icon("name") returns an app icon (<svg>).

export function mount(el, ctx) {
  el.innerHTML = `
    <div class="ui-page" style="max-width:720px">
      <h1 class="ui-h1">Notes</h1>
      <div class="ui-card">
        <textarea class="ui-textarea" rows="16" placeholder="Write anything..."></textarea>
        <div class="ui-row">
          <button class="ui-btn" type="button">Save</button>
          <span class="ui-muted"></span>
        </div>
      </div>
    </div>`;
  const area = el.querySelector("textarea");
  const button = el.querySelector("button");
  button.prepend(ctx.icon("check"));
  const status = el.querySelector("span");
  const show = (saved) => {
    status.textContent = saved ? `Saved ${new Date(saved * 1000).toLocaleString()}` : "Not saved yet";
  };

  ctx.api("notes").then((d) => { area.value = d.text; show(d.saved); })
    .catch((e) => { status.textContent = e.message; });

  const save = async () => {
    button.disabled = true;
    try {
      const d = await ctx.api("notes", { method: "PUT", body: { text: area.value } });
      show(d.saved);
    } catch (e) {
      status.textContent = e.message;
    } finally {
      button.disabled = false;
    }
  };
  button.addEventListener("click", save);
  const onKey = (e) => { if ((e.metaKey || e.ctrlKey) && e.key === "s") { e.preventDefault(); save(); } };
  window.addEventListener("keydown", onKey);

  return () => window.removeEventListener("keydown", onKey);   // cleanup
}
