"""Texts of the Telegram bot (English and French; English is the fallback of gateway._w)."""
from __future__ import annotations


STATUS_WORDS = {
    "en": {"working": "Working…", "done": "Done", "failed": "Stopped with an error", "steps": "steps",
           "step": "step", "earlier": "earlier steps"},
    "fr": {"working": "Harness travaille…", "done": "Terminé", "failed": "Arrêté sur une erreur", "steps": "étapes",
           "step": "étape", "earlier": "étapes précédentes"},
}


WORDS = {
    "en": {"where": "Where should this session live?", "more": "More topics…",
           "started": "🆕 <b>{title}</b> · {where}", "moved": "🆕 <b>{title}</b> · {where}\n→ continue in the thread <b>{name}</b>",
           "auto": " (no answer: default topic)", "ready": "Write your message here.",
           "intro": "💬 <b>{title}</b> · {where}\nWrite here to continue this session - the same conversation as in the web UI.",
           "pick_first": "Choose where the session lives first (buttons above).",
           "open": "Open sessions (one thread each):", "none_open": "No open session - write in the main chat to start one.",
           "notify_only": "This thread only receives notifications - write in a session thread or in the main chat.",
           "in_thread": "/{cmd} is about one session: send it in that session's thread.",
           "start_failed": "Could not start the session: {err}. Your messages are kept - choose a topic again (buttons above).",
           "restarted_new": "Harness restarted before your new session was started: {n} message(s) not handled - send them again, please."},
    "fr": {"where": "Où mettre cette session ?", "more": "Autres topics…",
           "started": "🆕 <b>{title}</b> · {where}", "moved": "🆕 <b>{title}</b> · {where}\n→ la suite dans le fil <b>{name}</b>",
           "auto": " (sans réponse : topic par défaut)", "ready": "Écrivez votre message ici.",
           "intro": "💬 <b>{title}</b> · {where}\nÉcrivez ici pour continuer cette session - la même conversation que dans l'interface web.",
           "pick_first": "Choisissez d'abord où mettre la session (boutons au-dessus).",
           "open": "Sessions ouvertes (un fil chacune) :", "none_open": "Aucune session ouverte - écrivez dans le chat principal pour en démarrer une.",
           "notify_only": "Ce fil ne reçoit que des notifications - écrivez dans le fil d'une session ou dans le chat principal.",
           "in_thread": "/{cmd} concerne une session : envoyez-la dans le fil de cette session.",
           "start_failed": "Impossible de démarrer la session : {err}. Vos messages sont gardés - choisissez à nouveau un topic (boutons au-dessus).",
           "restarted_new": "Harness a redémarré avant de créer votre nouvelle session : {n} message(s) non traité(s) - renvoyez-les, s'il vous plaît."},
}

# Bot texts beyond the "new session" flow (same languages as WORDS; English is the fallback of _w).
WORDS["en"].update({
    "help": ("<b>Harness Maxxing</b>\n\n"
             "Write a message (text, voice note, photo or file): I ask in which topic, then Harness answers here. "
             "<b>Reply</b> to any message of a session to continue it. Every session is also in the web UI, and "
             "the alerts (server, sign-ins, scheduled jobs, agents) arrive here too.\n\n"
             "/new [title] - new session (you choose its topic)\n"
             "/sessions - continue a recent session\n"
             "/stop - stop the running turn\n"
             "/close - archive the session\n"
             "/model [id] - choose the model\n"
             "/status - state, model, cost, queue\n\n"
             "<i>/stop, /close, /model and /status act on the session of the message you reply to, else on the "
             "last one you wrote to.</i>"),
    "help_threads": ("<b>Harness Maxxing</b> - here: {here}\n\n"
                     "Every open session of the web UI has its own thread here (same conversation, both ways). "
                     "Write in a session's thread to talk to Harness there; write in the main chat (or create a "
                     "thread) to start a new session - you choose its topic. /close (or archiving the session in "
                     "the web UI) closes it: the thread goes away, the conversation stays in the web UI.\n\n"
                     "/new [title] - new session (its own thread)\n"
                     "/sessions - list the open sessions\n"
                     "/stop - stop the running turn\n"
                     "/close - close this session (archived, thread deleted)\n"
                     "/model [id] - choose the model\n"
                     "/status - state, model, cost, queue"),
    "main_chat": "main chat", "general": "General",
    "untitled": "Untitled", "default": "default",
    "cmd_new": "Start a new session", "cmd_sessions": "Recent sessions",
    "cmd_stop": "Stop the running turn", "cmd_close": "Archive the session",
    "cmd_model": "Choose the model of the session", "cmd_status": "Session status: state, model, cost, queue",
    "cmd_help": "What this bot can do",
    "queued": "⏳ Queued - Harness is still working on the previous message.",
    "nothing_running": "Nothing is running.", "stopped": "⏹ Stopped.",
    "unsupported": "This kind of message is not supported yet - send text, a photo or a file.",
    "edited": "Edits are not sent to Harness - send a new message.",
    "no_sessions": "⚠️ Sessions are not available on this server yet.",
    "save_failed": "⚠️ Could not save the file: {error}",
    "save_failed_some": "⚠️ Could not save {names}: {error}",
    "voice_off": "🎤 Voice messages are off. Turn them on in the web UI: Settings → Voice.",
    "voice_not_ready": "🎤 Voice messages are not ready ({reason}). Open Settings → Voice in the web UI.",
    "voice_download": "⚠️ Could not download the audio: {error}",
    "voice_failed": "⚠️ Transcription failed: {error}",
    "voice_empty": "🎤 I could not hear any speech in this message.",
    "restarted": "Harness restarted while your last message was being handled: send it again, please.",
    "restarted_voice": "Harness restarted while your last voice note was being handled: send it again, please.",
    "model_set": "Model set to <b>{model}</b>.", "model_of": "Model of this session: {model}{note}",
    "model_last": " (last answer: {model})",
    "model_unknown": "Unknown model \"{model}\". Choose one of: {choices} (or \"default\").",
    "st_topic": "Topic: {v}", "st_state": "State: {v}", "st_queued": " · {n} queued", "st_model": "Model: {v}",
    "st_turns": "Turns: {n} · cost {cost}", "st_context": "Context: {n} tokens", "st_error": "Last error: {v}",
    "cb_not_allowed": "Not allowed.", "cb_not_here": "Not available here.",
    "cb_session_gone": "This session no longer exists.", "cb_model": "Model changed.",
    "cb_topic_gone": "This topic no longer exists.", "cb_unknown": "Unknown action.",
    "cb_done": "Already done.", "cb_error": "Error: {error}", "running": " · running",
    "no_session_here": "No session here.",
    "stop_first": "Harness is still working - /stop first, then /close.", "archived": "🗄 <b>{title}</b> archived.",
    "archived_kept": "🗄 Archived (Telegram did not delete this thread - delete it by hand).",
    "done_no_text": "✅ Done (no text reply).",
    "private_only": "Sorry, this is a private assistant - it only answers its owner.",
    "link_private": "Open the link from a private chat with the bot.",
    "link_who": "Could not identify you - send the link again from your account.",
    "linked": ("<b>Linked to Harness Maxxing.</b>\nWrite here to start a session (I ask in which topic); "
               "reply to a message to continue its session. Alerts arrive here too. /help lists the commands."),
    "linked_threads": ("<b>Linked to Harness Maxxing.</b>\nEach open session gets its own thread. "
                       "Write here (the main chat) to start a new session. /help lists the commands."),
    "ev_gone": "This notification no longer exists.", "ev_no_sessions": "Sessions are not available.",
    "ev_opened": "Opened: {name}", "ev_started": "Session started.",
    # Simple mode: one chat, a reply continues the session of the message it answers
    "where_last": "↩ Continue: {title}",
    "continued": "↩ <b>{title}</b> · {where}",
    "reply_hint": "\n<i>Reply to this message to write in this session.</i>",
    "card": "↩ <b>{title}</b> · {where}\n<i>Reply to this message to continue this session.</i>",
    "recent": "Recent sessions - tap one, then reply to the message that comes:",
    "no_recent": "No session yet - just write a message.",
    "no_target": "Which session? Reply to one of its messages (or /sessions).",
    "about": "<i>{title}</i>",
    # alerts: health problems of the server (dashboard) and alerts of other modules (post_alert)
    "seen_btn": "✓ Seen", "seen": "✓ Seen", "resolved": "✅ Resolved", "cb_seen": "Marked as seen.",
    "open_btn": "Open",
})
WORDS["fr"].update({
    "help": ("<b>Harness Maxxing</b>\n\n"
             "Écrivez un message (texte, message vocal, photo ou fichier) : je demande dans quel topic, puis Harness "
             "répond ici. <b>Répondez</b> à n'importe quel message d'une session pour la continuer. Chaque session est "
             "aussi dans l'interface web, et les alertes (serveur, connexions, tâches planifiées, agents) arrivent "
             "ici aussi.\n\n"
             "/new [titre] - nouvelle session (vous choisissez son topic)\n"
             "/sessions - continuer une session récente\n"
             "/stop - arrêter le tour en cours\n"
             "/close - archiver la session\n"
             "/model [id] - choisir le modèle\n"
             "/status - état, modèle, coût, file d'attente\n\n"
             "<i>/stop, /close, /model et /status agissent sur la session du message auquel vous répondez, sinon sur "
             "la dernière à laquelle vous avez écrit.</i>"),
    "help_threads": ("<b>Harness Maxxing</b> - ici : {here}\n\n"
                     "Chaque session ouverte de l'interface web a son propre fil ici (même conversation, dans les deux "
                     "sens). Écrivez dans le fil d'une session pour parler à Harness ; écrivez dans le chat principal (ou "
                     "créez un fil) pour démarrer une nouvelle session - vous choisissez son topic. /close (ou archiver "
                     "la session dans l'interface web) la ferme : le fil disparaît, la conversation reste dans "
                     "l'interface web.\n\n"
                     "/new [titre] - nouvelle session (son propre fil)\n"
                     "/sessions - lister les sessions ouvertes\n"
                     "/stop - arrêter le tour en cours\n"
                     "/close - fermer cette session (archivée, fil supprimé)\n"
                     "/model [id] - choisir le modèle\n"
                     "/status - état, modèle, coût, file d'attente"),
    "main_chat": "chat principal", "general": "Général",
    "untitled": "Sans titre", "default": "par défaut",
    "cmd_new": "Démarrer une nouvelle session", "cmd_sessions": "Sessions récentes",
    "cmd_stop": "Arrêter le tour en cours", "cmd_close": "Archiver la session",
    "cmd_model": "Choisir le modèle de la session", "cmd_status": "État de la session : modèle, coût, file",
    "cmd_help": "Ce que ce bot sait faire",
    "queued": "⏳ En file d'attente - Harness travaille encore sur le message précédent.",
    "nothing_running": "Rien n'est en cours.", "stopped": "⏹ Arrêté.",
    "unsupported": "Ce type de message n'est pas encore pris en charge - envoyez du texte, une photo ou un fichier.",
    "edited": "Les modifications ne sont pas transmises à Harness - envoyez un nouveau message.",
    "no_sessions": "⚠️ Les sessions ne sont pas encore disponibles sur ce serveur.",
    "save_failed": "⚠️ Impossible d'enregistrer le fichier : {error}",
    "save_failed_some": "⚠️ Impossible d'enregistrer {names} : {error}",
    "voice_off": "🎤 Les messages vocaux sont désactivés. Activez-les dans l'interface web : Réglages → Voix.",
    "voice_not_ready": "🎤 Les messages vocaux ne sont pas prêts ({reason}). Ouvrez Réglages → Voix dans l'interface web.",
    "voice_download": "⚠️ Impossible de télécharger l'audio : {error}",
    "voice_failed": "⚠️ La transcription a échoué : {error}",
    "voice_empty": "🎤 Aucune parole entendue dans ce message.",
    "restarted": "Harness a redémarré pendant le traitement de votre dernier message : renvoyez-le, s'il vous plaît.",
    "restarted_voice": "Harness a redémarré pendant le traitement de votre dernier message vocal : renvoyez-le, s'il vous plaît.",
    "model_set": "Modèle choisi : <b>{model}</b>.", "model_of": "Modèle de cette session : {model}{note}",
    "model_last": " (dernière réponse : {model})",
    "model_unknown": "Modèle inconnu « {model} ». Choisissez parmi : {choices} (ou « default »).",
    "st_topic": "Topic : {v}", "st_state": "État : {v}", "st_queued": " · {n} en attente", "st_model": "Modèle : {v}",
    "st_turns": "Tours : {n} · coût {cost}", "st_context": "Contexte : {n} tokens", "st_error": "Dernière erreur : {v}",
    "cb_not_allowed": "Non autorisé.", "cb_not_here": "Indisponible ici.",
    "cb_session_gone": "Cette session n'existe plus.", "cb_model": "Modèle changé.",
    "cb_topic_gone": "Ce topic n'existe plus.", "cb_unknown": "Action inconnue.",
    "cb_done": "Déjà fait.", "cb_error": "Erreur : {error}", "running": " · en cours",
    "no_session_here": "Aucune session ici.", "stop_first": "Harness travaille encore - /stop d'abord, puis /close.",
    "archived": "🗄 <b>{title}</b> archivée.",
    "archived_kept": "🗄 Archivée (Telegram n'a pas supprimé ce fil - supprimez-le à la main).",
    "done_no_text": "✅ Terminé (pas de réponse écrite).",
    "private_only": "Désolé, cet assistant est privé : il ne répond qu'à son propriétaire.",
    "link_private": "Ouvrez le lien depuis une conversation privée avec le bot.",
    "link_who": "Impossible de vous identifier - renvoyez le lien depuis votre compte.",
    "linked": ("<b>Relié à Harness Maxxing.</b>\nÉcrivez ici pour démarrer une session (je demande dans quel "
               "topic) ; répondez à un message pour continuer sa session. Les alertes arrivent ici aussi. /help liste "
               "les commandes."),
    "linked_threads": ("<b>Relié à Harness Maxxing.</b>\nChaque session ouverte a son propre fil. "
                       "Écrivez ici (le chat principal) pour démarrer une nouvelle session. /help liste les commandes."),
    "ev_gone": "Cette notification n'existe plus.", "ev_no_sessions": "Les sessions ne sont pas disponibles.",
    "ev_opened": "Ouvert : {name}", "ev_started": "Session démarrée.",
    "where_last": "↩ Continuer : {title}",
    "continued": "↩ <b>{title}</b> · {where}",
    "reply_hint": "\n<i>Répondez à ce message pour écrire dans cette session.</i>",
    "card": "↩ <b>{title}</b> · {where}\n<i>Répondez à ce message pour continuer cette session.</i>",
    "recent": "Sessions récentes - touchez-en une, puis répondez au message qui arrive :",
    "no_recent": "Aucune session pour l'instant - écrivez simplement un message.",
    "no_target": "Quelle session ? Répondez à un de ses messages (ou /sessions).",
    "about": "<i>{title}</i>",
    "seen_btn": "✓ Vu", "seen": "✓ Vu", "resolved": "✅ Résolu", "cb_seen": "Marqué comme vu.",
    "open_btn": "Ouvrir",
})

# The thread of an agent (agent.json `telegram`): its results, and a message there starts the agent.
WORDS["en"].update({
    "agent_intro": "🤖 <b>{name}</b> posts its results here. Write here to give it a task.",
    "agent_started": "⏳ {name} is on it.",
    "agent_skipped": "{name} did not start: {reason}.",
    "agent_command": "Commands work in session threads. Here every message is a task for {name}.",
    "agent_new_chat": "🆕 New conversation with {name}: reply to this message to start it.",
    "approval_ask": "🔐 <b>{name}</b> asks before doing this:\n<code>{what}</code>",
    "approval_btn_allow": "✅ Allow", "approval_btn_deny": "❌ Deny",
    "approval_allow": "✅ Allowed", "approval_deny": "❌ Denied",
    "approval_timeout": "⏱ No answer in time, denied", "approval_expired": "⏹ Expired (the turn stopped)",
    "approval_cut": "Only part of it is shown: open the request in Harness to allow it.",
    "alert_cut": "…(cut, open it to see all)",
})
WORDS["fr"].update({
    "agent_intro": "🤖 <b>{name}</b> publie ses résultats ici. Écrivez ici pour lui confier une tâche.",
    "agent_started": "⏳ {name} s'en occupe.",
    "agent_skipped": "{name} n'a pas démarré : {reason}.",
    "agent_command": "Les commandes marchent dans les fils de session. Ici chaque message est une tâche pour {name}.",
    "agent_new_chat": "🆕 Nouvelle conversation avec {name} : répondez à ce message pour la commencer.",
    "approval_ask": "🔐 <b>{name}</b> demande votre accord avant :\n<code>{what}</code>",
    "approval_btn_allow": "✅ Autoriser", "approval_btn_deny": "❌ Refuser",
    "approval_allow": "✅ Autorisé", "approval_deny": "❌ Refusé",
    "approval_timeout": "⏱ Pas de réponse à temps, refusé", "approval_expired": "⏹ Expiré (le tour s'est arrêté)",
    "approval_cut": "Seule une partie est affichée : ouvrez la demande dans Harness pour l'autoriser.",
    "alert_cut": "…(coupé, ouvrez-le pour tout voir)",
})
AGENT_REASONS = {
    "en": {"disabled": "it is switched off", "budget": "its daily budget is reached",
           "busy": "its run in progress holds the rest of today's budget: try again once it is done",
           "rate": "too many runs in the last hour", "missing": "it no longer exists",
           "depth": "too many hops between agents"},
    "fr": {"disabled": "il est désactivé", "budget": "son budget du jour est atteint",
           "busy": "le tour en cours réserve le reste de son budget du jour : réessayez quand il aura fini",
           "rate": "trop de tours dans la dernière heure", "missing": "il n'existe plus",
           "depth": "trop d'allers-retours entre agents"},
}


TOPICS_HELP = ("Telegram refused to create topic threads in this chat, so everything goes to the main "
               "chat (as in the Simple mode). To get threads (one per session, or an agent's own thread), enable "
               "topics (\"threaded mode\") for your bot in @BotFather (open your bot's settings, \"Threaded Mode\"), "
               "then press \"Retry\" in Settings -> Telegram.")
CONFLICT_HELP = ("Another program (n8n, Hermes, OpenClaw, a second Harness Maxxing…) is already reading this "
                 "bot's messages: stop it, or create a bot dedicated to Harness Maxxing with @BotFather.")

COMMANDS = [
    ("new", "Start a new session"),
    ("sessions", "Recent sessions"),
    ("stop", "Stop the running turn"),
    ("close", "Archive the session"),
    ("model", "Choose the model of the session"),
    ("status", "Session status: state, model, cost, queue"),
    ("help", "What this bot can do"),
]


LINK_WORDS = {
    "en": "This link expired or is not valid - create a new one in Harness Maxxing → Settings → Telegram, "
          "then open it (or scan its QR code).",
    "fr": "Ce lien a expiré ou n'est pas valide - créez-en un nouveau dans Harness Maxxing → Réglages → Telegram, "
          "puis ouvrez-le (ou scannez son QR code).",
}
