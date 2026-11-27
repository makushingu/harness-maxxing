"""Texts of the Telegram bot in the interface languages (config.LANGUAGES; English is the fallback of gateway._w)."""
from __future__ import annotations


STATUS_WORDS = {
    "en": {"working": "Working…", "done": "Done", "failed": "Stopped with an error", "steps": "steps",
           "step": "step", "earlier": "earlier steps"},
    "fr": {"working": "Harness travaille…", "done": "Terminé", "failed": "Arrêté sur une erreur", "steps": "étapes",
           "step": "étape", "earlier": "étapes précédentes"},
    "es": {"working": "Harness está trabajando…", "done": "Terminado", "failed": "Detenido por un error",
           "steps": "pasos", "step": "paso", "earlier": "pasos anteriores"},
    "de": {"working": "Harness arbeitet…", "done": "Fertig", "failed": "Mit einem Fehler gestoppt",
           "steps": "Schritte", "step": "Schritt", "earlier": "frühere Schritte"},
    "zh": {"working": "Harness 正在工作…", "done": "已完成", "failed": "因错误而停止", "steps": "个步骤",
           "step": "个步骤", "earlier": "之前的步骤"},
    "ja": {"working": "Harness が作業中…", "done": "完了", "failed": "エラーで停止しました", "steps": "ステップ",
           "step": "ステップ", "earlier": "以前のステップ"},
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
    "es": {"where": "¿Dónde pongo esta sesión?", "more": "Más temas…",
           "started": "🆕 <b>{title}</b> · {where}", "moved": "🆕 <b>{title}</b> · {where}\n→ continúa en el hilo <b>{name}</b>",
           "auto": " (sin respuesta: tema por defecto)", "ready": "Escribe tu mensaje aquí.",
           "intro": "💬 <b>{title}</b> · {where}\nEscribe aquí para continuar esta sesión: la misma conversación que en la interfaz web.",
           "pick_first": "Elige primero dónde poner la sesión (botones de arriba).",
           "open": "Sesiones abiertas (un hilo cada una):", "none_open": "Ninguna sesión abierta: escribe en el chat principal para iniciar una.",
           "notify_only": "Este hilo solo recibe notificaciones: escribe en el hilo de una sesión o en el chat principal.",
           "in_thread": "/{cmd} se refiere a una sesión: envíalo en el hilo de esa sesión.",
           "start_failed": "No se ha podido iniciar la sesión: {err}. Tus mensajes se conservan: elige un tema de nuevo (botones de arriba).",
           "restarted_new": "Harness se ha reiniciado antes de crear tu nueva sesión: {n} mensaje(s) sin procesar. Envíalos de nuevo, por favor."},
    "de": {"where": "Wohin soll diese Sitzung?", "more": "Weitere Themen…",
           "started": "🆕 <b>{title}</b> · {where}", "moved": "🆕 <b>{title}</b> · {where}\n→ weiter im Thread <b>{name}</b>",
           "auto": " (keine Antwort: Standardthema)", "ready": "Schreib deine Nachricht hier.",
           "intro": "💬 <b>{title}</b> · {where}\nSchreib hier, um diese Sitzung fortzusetzen - dieselbe Unterhaltung wie in der Weboberfläche.",
           "pick_first": "Wähle zuerst, wohin die Sitzung soll (Schaltflächen oben).",
           "open": "Offene Sitzungen (je ein Thread):", "none_open": "Keine offene Sitzung - schreib im Hauptchat, um eine zu starten.",
           "notify_only": "Dieser Thread empfängt nur Benachrichtigungen - schreib im Thread einer Sitzung oder im Hauptchat.",
           "in_thread": "/{cmd} betrifft eine Sitzung: Sende es im Thread dieser Sitzung.",
           "start_failed": "Die Sitzung konnte nicht gestartet werden: {err}. Deine Nachrichten bleiben erhalten - wähle erneut ein Thema (Schaltflächen oben).",
           "restarted_new": "Harness wurde neu gestartet, bevor deine neue Sitzung begann: {n} Nachricht(en) nicht verarbeitet - sende sie bitte noch einmal."},
    "zh": {"where": "这个会话放在哪里？", "more": "更多主题…",
           "started": "🆕 <b>{title}</b> · {where}", "moved": "🆕 <b>{title}</b> · {where}\n→ 请在话题 <b>{name}</b> 中继续",
           "auto": "（未回答：默认主题）", "ready": "在这里写下你的消息。",
           "intro": "💬 <b>{title}</b> · {where}\n在这里输入即可继续此会话，与网页界面中是同一个对话。",
           "pick_first": "请先选择会话放在哪里（上方按钮）。",
           "open": "打开的会话（每个一个话题）：", "none_open": "没有打开的会话，在主聊天中发消息即可开始一个。",
           "notify_only": "此话题只接收通知，请在某个会话的话题或主聊天中发消息。",
           "in_thread": "/{cmd} 针对单个会话：请在该会话的话题中发送。",
           "start_failed": "无法启动会话：{err}。你的消息已保留，请重新选择主题（上方按钮）。",
           "restarted_new": "Harness 在新会话启动前重启了：有 {n} 条消息未处理，请重新发送。"},
    "ja": {"where": "このセッションをどこに置きますか？", "more": "他のトピック…",
           "started": "🆕 <b>{title}</b> · {where}", "moved": "🆕 <b>{title}</b> · {where}\n→ 続きはスレッド <b>{name}</b> で",
           "auto": "（応答なし：既定のトピック）", "ready": "ここにメッセージを書いてください。",
           "intro": "💬 <b>{title}</b> · {where}\nここに書くとこのセッションを続けられます。Web UI と同じ会話です。",
           "pick_first": "先にセッションの置き場所を選んでください（上のボタン）。",
           "open": "開いているセッション（それぞれ 1 スレッド）：", "none_open": "開いているセッションはありません。メインチャットに書くと開始できます。",
           "notify_only": "このスレッドは通知専用です。セッションのスレッドかメインチャットに書いてください。",
           "in_thread": "/{cmd} は 1 つのセッションが対象です。そのセッションのスレッドで送信してください。",
           "start_failed": "セッションを開始できませんでした：{err}。メッセージは保存されています。もう一度トピックを選んでください（上のボタン）。",
           "restarted_new": "新しいセッションが始まる前に Harness が再起動しました。{n} 件のメッセージが未処理です。もう一度送信してください。"},
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

# The same texts in the other interface languages (every key of WORDS["en"]: server/tests/test_i18n_server.py).
WORDS["es"].update({
    "help": ("<b>Harness Maxxing</b>\n\n"
             "Escribe un mensaje (texto, nota de voz, foto o archivo): pregunto en qué tema y Harness responde aquí. "
             "<b>Responde</b> a cualquier mensaje de una sesión para continuarla. Todas las sesiones están también "
             "en la interfaz web, y las alertas (servidor, inicios de sesión, tareas programadas, agentes) llegan "
             "aquí también.\n\n"
             "/new [título] - nueva sesión (tú eliges su tema)\n"
             "/sessions - continuar una sesión reciente\n"
             "/stop - detener el turno en curso\n"
             "/close - archivar la sesión\n"
             "/model [id] - elegir el modelo\n"
             "/status - estado, modelo, coste, cola\n\n"
             "<i>/stop, /close, /model y /status actúan sobre la sesión del mensaje al que respondes; si no, sobre "
             "la última a la que has escrito.</i>"),
    "help_threads": ("<b>Harness Maxxing</b> - aquí: {here}\n\n"
                     "Cada sesión abierta de la interfaz web tiene su propio hilo aquí (la misma conversación, en "
                     "ambos sentidos). Escribe en el hilo de una sesión para hablar con Harness; escribe en el chat "
                     "principal (o crea un hilo) para iniciar una sesión nueva: tú eliges su tema. /close (o archivar "
                     "la sesión en la interfaz web) la cierra: el hilo desaparece, la conversación se queda en la "
                     "interfaz web.\n\n"
                     "/new [título] - nueva sesión (su propio hilo)\n"
                     "/sessions - listar las sesiones abiertas\n"
                     "/stop - detener el turno en curso\n"
                     "/close - cerrar esta sesión (archivada, hilo eliminado)\n"
                     "/model [id] - elegir el modelo\n"
                     "/status - estado, modelo, coste, cola"),
    "main_chat": "chat principal", "general": "General",
    "untitled": "Sin título", "default": "por defecto",
    "cmd_new": "Iniciar una sesión nueva", "cmd_sessions": "Sesiones recientes",
    "cmd_stop": "Detener el turno en curso", "cmd_close": "Archivar la sesión",
    "cmd_model": "Elegir el modelo de la sesión", "cmd_status": "Estado de la sesión: modelo, coste, cola",
    "cmd_help": "Qué sabe hacer este bot",
    "queued": "⏳ En cola: Harness sigue trabajando en el mensaje anterior.",
    "nothing_running": "No hay nada en curso.", "stopped": "⏹ Detenido.",
    "unsupported": "Este tipo de mensaje todavía no es compatible: envía texto, una foto o un archivo.",
    "edited": "Las ediciones no se envían a Harness: envía un mensaje nuevo.",
    "no_sessions": "⚠️ Las sesiones todavía no están disponibles en este servidor.",
    "save_failed": "⚠️ No se ha podido guardar el archivo: {error}",
    "save_failed_some": "⚠️ No se ha podido guardar {names}: {error}",
    "voice_off": "🎤 Los mensajes de voz están desactivados. Actívalos en la interfaz web: Ajustes → Voz.",
    "voice_not_ready": "🎤 Los mensajes de voz no están listos ({reason}). Abre Ajustes → Voz en la interfaz web.",
    "voice_download": "⚠️ No se ha podido descargar el audio: {error}",
    "voice_failed": "⚠️ La transcripción ha fallado: {error}",
    "voice_empty": "🎤 No he oído ninguna voz en este mensaje.",
    "restarted": "Harness se ha reiniciado mientras procesaba tu último mensaje: envíalo de nuevo, por favor.",
    "restarted_voice": "Harness se ha reiniciado mientras procesaba tu última nota de voz: envíala de nuevo, por favor.",
    "model_set": "Modelo elegido: <b>{model}</b>.", "model_of": "Modelo de esta sesión: {model}{note}",
    "model_last": " (última respuesta: {model})",
    "model_unknown": "Modelo desconocido «{model}». Elige uno de: {choices} (o «default»).",
    "st_topic": "Tema: {v}", "st_state": "Estado: {v}", "st_queued": " · {n} en cola", "st_model": "Modelo: {v}",
    "st_turns": "Turnos: {n} · coste {cost}", "st_context": "Contexto: {n} tokens", "st_error": "Último error: {v}",
    "cb_not_allowed": "No permitido.", "cb_not_here": "No disponible aquí.",
    "cb_session_gone": "Esta sesión ya no existe.", "cb_model": "Modelo cambiado.",
    "cb_topic_gone": "Este tema ya no existe.", "cb_unknown": "Acción desconocida.",
    "cb_done": "Ya está hecho.", "cb_error": "Error: {error}", "running": " · en curso",
    "no_session_here": "Ninguna sesión aquí.",
    "stop_first": "Harness sigue trabajando: primero /stop, luego /close.", "archived": "🗄 <b>{title}</b> archivada.",
    "archived_kept": "🗄 Archivada (Telegram no ha eliminado este hilo: elimínalo a mano).",
    "done_no_text": "✅ Terminado (sin respuesta de texto).",
    "private_only": "Lo siento, este asistente es privado: solo responde a su propietario.",
    "link_private": "Abre el enlace desde un chat privado con el bot.",
    "link_who": "No se te ha podido identificar: envía el enlace de nuevo desde tu cuenta.",
    "linked": ("<b>Vinculado a Harness Maxxing.</b>\nEscribe aquí para iniciar una sesión (pregunto en qué tema); "
               "responde a un mensaje para continuar su sesión. Las alertas llegan aquí también. /help lista los "
               "comandos."),
    "linked_threads": ("<b>Vinculado a Harness Maxxing.</b>\nCada sesión abierta tiene su propio hilo. "
                       "Escribe aquí (el chat principal) para iniciar una sesión nueva. /help lista los comandos."),
    "ev_gone": "Esta notificación ya no existe.", "ev_no_sessions": "Las sesiones no están disponibles.",
    "ev_opened": "Abierto: {name}", "ev_started": "Sesión iniciada.",
    "where_last": "↩ Continuar: {title}",
    "continued": "↩ <b>{title}</b> · {where}",
    "reply_hint": "\n<i>Responde a este mensaje para escribir en esta sesión.</i>",
    "card": "↩ <b>{title}</b> · {where}\n<i>Responde a este mensaje para continuar esta sesión.</i>",
    "recent": "Sesiones recientes: toca una y responde al mensaje que llegue:",
    "no_recent": "Ninguna sesión por ahora: simplemente escribe un mensaje.",
    "no_target": "¿Qué sesión? Responde a uno de sus mensajes (o /sessions).",
    "about": "<i>{title}</i>",
    "seen_btn": "✓ Visto", "seen": "✓ Visto", "resolved": "✅ Resuelto", "cb_seen": "Marcado como visto.",
    "open_btn": "Abrir",
    "agent_intro": "🤖 <b>{name}</b> publica sus resultados aquí. Escribe aquí para encargarle una tarea.",
    "agent_started": "⏳ {name} se pone a ello.",
    "agent_skipped": "{name} no se ha iniciado: {reason}.",
    "agent_command": "Los comandos funcionan en los hilos de sesión. Aquí cada mensaje es una tarea para {name}.",
    "agent_new_chat": "🆕 Nueva conversación con {name}: responde a este mensaje para empezarla.",
    "approval_ask": "🔐 <b>{name}</b> pide permiso antes de hacer esto:\n<code>{what}</code>",
    "approval_btn_allow": "✅ Permitir", "approval_btn_deny": "❌ Denegar",
    "approval_allow": "✅ Permitido", "approval_deny": "❌ Denegado",
    "approval_timeout": "⏱ Sin respuesta a tiempo, denegado", "approval_expired": "⏹ Caducado (el turno se ha detenido)",
    "approval_cut": "Solo se muestra una parte: abre la solicitud en Harness para permitirla.",
    "alert_cut": "…(cortado, ábrelo para verlo todo)",
})
WORDS["de"].update({
    "help": ("<b>Harness Maxxing</b>\n\n"
             "Schreib eine Nachricht (Text, Sprachnachricht, Foto oder Datei): Ich frage, in welches Thema, dann "
             "antwortet Harness hier. <b>Antworte</b> auf eine beliebige Nachricht einer Sitzung, um sie "
             "fortzusetzen. Jede Sitzung ist auch in der Weboberfläche, und die Warnungen (Server, Anmeldungen, "
             "geplante Jobs, Agenten) kommen ebenfalls hier an.\n\n"
             "/new [Titel] - neue Sitzung (du wählst ihr Thema)\n"
             "/sessions - eine letzte Sitzung fortsetzen\n"
             "/stop - den laufenden Durchlauf stoppen\n"
             "/close - die Sitzung archivieren\n"
             "/model [id] - das Modell wählen\n"
             "/status - Zustand, Modell, Kosten, Warteschlange\n\n"
             "<i>/stop, /close, /model und /status wirken auf die Sitzung der Nachricht, auf die du antwortest, "
             "sonst auf die letzte, in die du geschrieben hast.</i>"),
    "help_threads": ("<b>Harness Maxxing</b> - hier: {here}\n\n"
                     "Jede offene Sitzung der Weboberfläche hat hier ihren eigenen Thread (dieselbe Unterhaltung, in "
                     "beide Richtungen). Schreib im Thread einer Sitzung, um dort mit Harness zu sprechen; schreib im "
                     "Hauptchat (oder erstelle einen Thread), um eine neue Sitzung zu starten - du wählst ihr Thema. "
                     "/close (oder das Archivieren der Sitzung in der Weboberfläche) schließt sie: Der Thread "
                     "verschwindet, die Unterhaltung bleibt in der Weboberfläche.\n\n"
                     "/new [Titel] - neue Sitzung (eigener Thread)\n"
                     "/sessions - die offenen Sitzungen auflisten\n"
                     "/stop - den laufenden Durchlauf stoppen\n"
                     "/close - diese Sitzung schließen (archiviert, Thread gelöscht)\n"
                     "/model [id] - das Modell wählen\n"
                     "/status - Zustand, Modell, Kosten, Warteschlange"),
    "main_chat": "Hauptchat", "general": "Allgemein",
    "untitled": "Ohne Titel", "default": "Standard",
    "cmd_new": "Neue Sitzung starten", "cmd_sessions": "Letzte Sitzungen",
    "cmd_stop": "Laufenden Durchlauf stoppen", "cmd_close": "Sitzung archivieren",
    "cmd_model": "Modell der Sitzung wählen", "cmd_status": "Sitzungsstatus: Zustand, Modell, Kosten, Warteschlange",
    "cmd_help": "Was dieser Bot kann",
    "queued": "⏳ In der Warteschlange - Harness arbeitet noch an der vorherigen Nachricht.",
    "nothing_running": "Es läuft nichts.", "stopped": "⏹ Gestoppt.",
    "unsupported": "Diese Art von Nachricht wird noch nicht unterstützt - sende Text, ein Foto oder eine Datei.",
    "edited": "Bearbeitungen werden nicht an Harness gesendet - sende eine neue Nachricht.",
    "no_sessions": "⚠️ Sitzungen sind auf diesem Server noch nicht verfügbar.",
    "save_failed": "⚠️ Die Datei konnte nicht gespeichert werden: {error}",
    "save_failed_some": "⚠️ {names} konnte nicht gespeichert werden: {error}",
    "voice_off": "🎤 Sprachnachrichten sind aus. Schalte sie in der Weboberfläche ein: Einstellungen → Stimme.",
    "voice_not_ready": "🎤 Sprachnachrichten sind nicht bereit ({reason}). Öffne Einstellungen → Stimme in der Weboberfläche.",
    "voice_download": "⚠️ Das Audio konnte nicht heruntergeladen werden: {error}",
    "voice_failed": "⚠️ Die Transkription ist fehlgeschlagen: {error}",
    "voice_empty": "🎤 Ich konnte in dieser Nachricht keine Sprache hören.",
    "restarted": "Harness wurde neu gestartet, während deine letzte Nachricht verarbeitet wurde: Sende sie bitte noch einmal.",
    "restarted_voice": "Harness wurde neu gestartet, während deine letzte Sprachnachricht verarbeitet wurde: Sende sie bitte noch einmal.",
    "model_set": "Modell gewählt: <b>{model}</b>.", "model_of": "Modell dieser Sitzung: {model}{note}",
    "model_last": " (letzte Antwort: {model})",
    "model_unknown": "Unbekanntes Modell „{model}“. Wähle eines von: {choices} (oder „default“).",
    "st_topic": "Thema: {v}", "st_state": "Zustand: {v}", "st_queued": " · {n} in der Warteschlange", "st_model": "Modell: {v}",
    "st_turns": "Durchläufe: {n} · Kosten {cost}", "st_context": "Kontext: {n} Tokens", "st_error": "Letzter Fehler: {v}",
    "cb_not_allowed": "Nicht erlaubt.", "cb_not_here": "Hier nicht verfügbar.",
    "cb_session_gone": "Diese Sitzung gibt es nicht mehr.", "cb_model": "Modell geändert.",
    "cb_topic_gone": "Dieses Thema gibt es nicht mehr.", "cb_unknown": "Unbekannte Aktion.",
    "cb_done": "Schon erledigt.", "cb_error": "Fehler: {error}", "running": " · läuft",
    "no_session_here": "Keine Sitzung hier.",
    "stop_first": "Harness arbeitet noch - erst /stop, dann /close.", "archived": "🗄 <b>{title}</b> archiviert.",
    "archived_kept": "🗄 Archiviert (Telegram hat diesen Thread nicht gelöscht - lösche ihn von Hand).",
    "done_no_text": "✅ Fertig (keine Textantwort).",
    "private_only": "Tut mir leid, das ist ein privater Assistent - er antwortet nur seinem Besitzer.",
    "link_private": "Öffne den Link in einem privaten Chat mit dem Bot.",
    "link_who": "Du konntest nicht erkannt werden - sende den Link noch einmal von deinem Konto.",
    "linked": ("<b>Mit Harness Maxxing verbunden.</b>\nSchreib hier, um eine Sitzung zu starten (ich frage, in "
               "welches Thema); antworte auf eine Nachricht, um ihre Sitzung fortzusetzen. Warnungen kommen auch "
               "hier an. /help listet die Befehle auf."),
    "linked_threads": ("<b>Mit Harness Maxxing verbunden.</b>\nJede offene Sitzung bekommt ihren eigenen Thread. "
                       "Schreib hier (im Hauptchat), um eine neue Sitzung zu starten. /help listet die Befehle auf."),
    "ev_gone": "Diese Benachrichtigung gibt es nicht mehr.", "ev_no_sessions": "Sitzungen sind nicht verfügbar.",
    "ev_opened": "Geöffnet: {name}", "ev_started": "Sitzung gestartet.",
    "where_last": "↩ Fortsetzen: {title}",
    "continued": "↩ <b>{title}</b> · {where}",
    "reply_hint": "\n<i>Antworte auf diese Nachricht, um in dieser Sitzung zu schreiben.</i>",
    "card": "↩ <b>{title}</b> · {where}\n<i>Antworte auf diese Nachricht, um diese Sitzung fortzusetzen.</i>",
    "recent": "Letzte Sitzungen - tippe eine an und antworte dann auf die Nachricht, die kommt:",
    "no_recent": "Noch keine Sitzung - schreib einfach eine Nachricht.",
    "no_target": "Welche Sitzung? Antworte auf eine ihrer Nachrichten (oder /sessions).",
    "about": "<i>{title}</i>",
    "seen_btn": "✓ Gesehen", "seen": "✓ Gesehen", "resolved": "✅ Behoben", "cb_seen": "Als gesehen markiert.",
    "open_btn": "Öffnen",
    "agent_intro": "🤖 <b>{name}</b> postet seine Ergebnisse hier. Schreib hier, um ihm eine Aufgabe zu geben.",
    "agent_started": "⏳ {name} kümmert sich darum.",
    "agent_skipped": "{name} ist nicht gestartet: {reason}.",
    "agent_command": "Befehle funktionieren in Sitzungs-Threads. Hier ist jede Nachricht eine Aufgabe für {name}.",
    "agent_new_chat": "🆕 Neue Unterhaltung mit {name}: Antworte auf diese Nachricht, um sie zu beginnen.",
    "approval_ask": "🔐 <b>{name}</b> fragt, bevor er das tut:\n<code>{what}</code>",
    "approval_btn_allow": "✅ Erlauben", "approval_btn_deny": "❌ Ablehnen",
    "approval_allow": "✅ Erlaubt", "approval_deny": "❌ Abgelehnt",
    "approval_timeout": "⏱ Keine rechtzeitige Antwort, abgelehnt", "approval_expired": "⏹ Abgelaufen (der Durchlauf wurde gestoppt)",
    "approval_cut": "Nur ein Teil wird angezeigt: Öffne die Anfrage in Harness, um sie zu erlauben.",
    "alert_cut": "…(gekürzt, öffne es, um alles zu sehen)",
})
WORDS["zh"].update({
    "help": ("<b>Harness Maxxing</b>\n\n"
             "发一条消息（文字、语音、照片或文件）：我会问放在哪个主题，然后 Harness 在这里回答。"
             "<b>回复</b>某个会话的任意一条消息即可继续该会话。所有会话也都在网页界面中，"
             "提醒（服务器、登录、定时任务、智能体）也会发到这里。\n\n"
             "/new [标题] - 新会话（由你选择主题）\n"
             "/sessions - 继续最近的会话\n"
             "/stop - 停止正在运行的回合\n"
             "/close - 归档会话\n"
             "/model [id] - 选择模型\n"
             "/status - 状态、模型、费用、队列\n\n"
             "<i>/stop、/close、/model 和 /status 作用于你所回复消息的会话，否则作用于你最后发过消息的会话。</i>"),
    "help_threads": ("<b>Harness Maxxing</b> - 当前位置：{here}\n\n"
                     "网页界面中每个打开的会话在这里都有自己的话题（同一个对话，双向同步）。"
                     "在会话的话题中发消息即可与 Harness 对话；在主聊天中发消息（或新建话题）即可开始新会话，"
                     "由你选择主题。/close（或在网页界面中归档会话）会关闭它：话题消失，对话保留在网页界面中。\n\n"
                     "/new [标题] - 新会话（独立话题）\n"
                     "/sessions - 列出打开的会话\n"
                     "/stop - 停止正在运行的回合\n"
                     "/close - 关闭此会话（归档，删除话题）\n"
                     "/model [id] - 选择模型\n"
                     "/status - 状态、模型、费用、队列"),
    "main_chat": "主聊天", "general": "常规",
    "untitled": "无标题", "default": "默认",
    "cmd_new": "开始新会话", "cmd_sessions": "最近的会话",
    "cmd_stop": "停止正在运行的回合", "cmd_close": "归档会话",
    "cmd_model": "选择会话的模型", "cmd_status": "会话状态：状态、模型、费用、队列",
    "cmd_help": "这个机器人能做什么",
    "queued": "⏳ 已排队，Harness 还在处理上一条消息。",
    "nothing_running": "没有正在运行的内容。", "stopped": "⏹ 已停止。",
    "unsupported": "暂不支持这种消息，请发送文字、照片或文件。",
    "edited": "编辑后的内容不会发送给 Harness，请发送一条新消息。",
    "no_sessions": "⚠️ 此服务器上暂时无法使用会话。",
    "save_failed": "⚠️ 无法保存文件：{error}",
    "save_failed_some": "⚠️ 无法保存 {names}：{error}",
    "voice_off": "🎤 语音消息已关闭。请在网页界面中开启：设置 → 语音。",
    "voice_not_ready": "🎤 语音消息尚未就绪（{reason}）。请在网页界面中打开设置 → 语音。",
    "voice_download": "⚠️ 无法下载音频：{error}",
    "voice_failed": "⚠️ 转写失败：{error}",
    "voice_empty": "🎤 这条消息里没有听到语音。",
    "restarted": "Harness 在处理你上一条消息时重启了：请重新发送。",
    "restarted_voice": "Harness 在处理你上一条语音时重启了：请重新发送。",
    "model_set": "模型已设为 <b>{model}</b>。", "model_of": "此会话的模型：{model}{note}",
    "model_last": "（上次回答：{model}）",
    "model_unknown": "未知模型“{model}”。请从以下选择：{choices}（或“default”）。",
    "st_topic": "主题：{v}", "st_state": "状态：{v}", "st_queued": " · {n} 条排队中", "st_model": "模型：{v}",
    "st_turns": "回合：{n} · 费用 {cost}", "st_context": "上下文：{n} 个 token", "st_error": "最近的错误：{v}",
    "cb_not_allowed": "不允许。", "cb_not_here": "此处不可用。",
    "cb_session_gone": "此会话已不存在。", "cb_model": "模型已更改。",
    "cb_topic_gone": "此主题已不存在。", "cb_unknown": "未知操作。",
    "cb_done": "已经完成。", "cb_error": "错误：{error}", "running": " · 运行中",
    "no_session_here": "这里没有会话。",
    "stop_first": "Harness 还在工作，请先 /stop，再 /close。", "archived": "🗄 <b>{title}</b> 已归档。",
    "archived_kept": "🗄 已归档（Telegram 没有删除这个话题，请手动删除）。",
    "done_no_text": "✅ 已完成（没有文字回复）。",
    "private_only": "抱歉，这是私人助手，只回答它的所有者。",
    "link_private": "请在与机器人的私聊中打开链接。",
    "link_who": "无法识别你的身份，请用你的账号重新发送链接。",
    "linked": ("<b>已关联 Harness Maxxing。</b>\n在这里发消息即可开始会话（我会问放在哪个主题）；"
               "回复某条消息即可继续它的会话。提醒也会发到这里。/help 列出所有命令。"),
    "linked_threads": ("<b>已关联 Harness Maxxing。</b>\n每个打开的会话都有自己的话题。"
                       "在这里（主聊天）发消息即可开始新会话。/help 列出所有命令。"),
    "ev_gone": "此通知已不存在。", "ev_no_sessions": "会话不可用。",
    "ev_opened": "已打开：{name}", "ev_started": "会话已开始。",
    "where_last": "↩ 继续：{title}",
    "continued": "↩ <b>{title}</b> · {where}",
    "reply_hint": "\n<i>回复这条消息即可在此会话中发言。</i>",
    "card": "↩ <b>{title}</b> · {where}\n<i>回复这条消息即可继续此会话。</i>",
    "recent": "最近的会话：点一个，然后回复随后出现的消息：",
    "no_recent": "还没有会话，直接发一条消息即可。",
    "no_target": "哪个会话？请回复它的某条消息（或 /sessions）。",
    "about": "<i>{title}</i>",
    "seen_btn": "✓ 已读", "seen": "✓ 已读", "resolved": "✅ 已解决", "cb_seen": "已标记为已读。",
    "open_btn": "打开",
    "agent_intro": "🤖 <b>{name}</b> 会把结果发在这里。在这里发消息即可给它布置任务。",
    "agent_started": "⏳ {name} 正在处理。",
    "agent_skipped": "{name} 没有启动：{reason}。",
    "agent_command": "命令只在会话话题中有效。在这里，每条消息都是给 {name} 的任务。",
    "agent_new_chat": "🆕 与 {name} 的新对话：回复这条消息即可开始。",
    "approval_ask": "🔐 <b>{name}</b> 在执行以下操作前请求许可：\n<code>{what}</code>",
    "approval_btn_allow": "✅ 允许", "approval_btn_deny": "❌ 拒绝",
    "approval_allow": "✅ 已允许", "approval_deny": "❌ 已拒绝",
    "approval_timeout": "⏱ 未及时回答，已拒绝", "approval_expired": "⏹ 已过期（回合已停止）",
    "approval_cut": "只显示了一部分：请在 Harness 中打开该请求以允许它。",
    "alert_cut": "…（已截断，打开查看全部）",
})
WORDS["ja"].update({
    "help": ("<b>Harness Maxxing</b>\n\n"
             "メッセージ（テキスト、ボイスメッセージ、写真、ファイル）を送ってください。どのトピックにするかを"
             "確認してから、Harness がここで回答します。セッションのメッセージに<b>返信</b>すると、そのセッションを"
             "続けられます。すべてのセッションは Web UI にもあり、アラート（サーバー、サインイン、定期ジョブ、"
             "エージェント）もここに届きます。\n\n"
             "/new [タイトル] - 新しいセッション（トピックを選べます）\n"
             "/sessions - 最近のセッションを続ける\n"
             "/stop - 実行中のターンを停止\n"
             "/close - セッションをアーカイブ\n"
             "/model [id] - モデルを選ぶ\n"
             "/status - 状態、モデル、コスト、キュー\n\n"
             "<i>/stop、/close、/model、/status は、返信先メッセージのセッションに作用します。返信でない場合は、"
             "最後に書き込んだセッションに作用します。</i>"),
    "help_threads": ("<b>Harness Maxxing</b> - 現在地：{here}\n\n"
                     "Web UI で開いているセッションには、ここにそれぞれ専用のスレッドがあります（同じ会話で、"
                     "双方向です）。セッションのスレッドに書くと、そこで Harness と話せます。メインチャットに書く"
                     "（またはスレッドを作成する）と新しいセッションが始まり、トピックを選べます。/close（または "
                     "Web UI でのセッションのアーカイブ）でセッションを閉じます。スレッドは消えますが、会話は "
                     "Web UI に残ります。\n\n"
                     "/new [タイトル] - 新しいセッション（専用スレッド）\n"
                     "/sessions - 開いているセッションの一覧\n"
                     "/stop - 実行中のターンを停止\n"
                     "/close - このセッションを閉じる（アーカイブし、スレッドを削除）\n"
                     "/model [id] - モデルを選ぶ\n"
                     "/status - 状態、モデル、コスト、キュー"),
    "main_chat": "メインチャット", "general": "一般",
    "untitled": "無題", "default": "既定",
    "cmd_new": "新しいセッションを開始", "cmd_sessions": "最近のセッション",
    "cmd_stop": "実行中のターンを停止", "cmd_close": "セッションをアーカイブ",
    "cmd_model": "セッションのモデルを選ぶ", "cmd_status": "セッションの状況：状態、モデル、コスト、キュー",
    "cmd_help": "このボットにできること",
    "queued": "⏳ キューに追加しました。Harness は前のメッセージをまだ処理中です。",
    "nothing_running": "実行中のものはありません。", "stopped": "⏹ 停止しました。",
    "unsupported": "この種類のメッセージにはまだ対応していません。テキスト、写真、またはファイルを送ってください。",
    "edited": "編集内容は Harness に送信されません。新しいメッセージを送ってください。",
    "no_sessions": "⚠️ このサーバーではまだセッションを利用できません。",
    "save_failed": "⚠️ ファイルを保存できませんでした：{error}",
    "save_failed_some": "⚠️ {names} を保存できませんでした：{error}",
    "voice_off": "🎤 ボイスメッセージはオフです。Web UI でオンにしてください：設定 → 音声。",
    "voice_not_ready": "🎤 ボイスメッセージの準備ができていません（{reason}）。Web UI で設定 → 音声を開いてください。",
    "voice_download": "⚠️ 音声をダウンロードできませんでした：{error}",
    "voice_failed": "⚠️ 文字起こしに失敗しました：{error}",
    "voice_empty": "🎤 このメッセージから音声を聞き取れませんでした。",
    "restarted": "最後のメッセージの処理中に Harness が再起動しました。もう一度送信してください。",
    "restarted_voice": "最後のボイスメッセージの処理中に Harness が再起動しました。もう一度送信してください。",
    "model_set": "モデルを <b>{model}</b> に設定しました。", "model_of": "このセッションのモデル：{model}{note}",
    "model_last": "（前回の回答：{model}）",
    "model_unknown": "不明なモデル「{model}」です。次から選んでください：{choices}（または「default」）。",
    "st_topic": "トピック：{v}", "st_state": "状態：{v}", "st_queued": " · {n} 件待機中", "st_model": "モデル：{v}",
    "st_turns": "ターン：{n} · コスト {cost}", "st_context": "コンテキスト：{n} トークン", "st_error": "直近のエラー：{v}",
    "cb_not_allowed": "許可されていません。", "cb_not_here": "ここでは利用できません。",
    "cb_session_gone": "このセッションはもう存在しません。", "cb_model": "モデルを変更しました。",
    "cb_topic_gone": "このトピックはもう存在しません。", "cb_unknown": "不明な操作です。",
    "cb_done": "すでに完了しています。", "cb_error": "エラー：{error}", "running": " · 実行中",
    "no_session_here": "ここにセッションはありません。",
    "stop_first": "Harness はまだ作業中です。先に /stop、その後 /close を実行してください。",
    "archived": "🗄 <b>{title}</b> をアーカイブしました。",
    "archived_kept": "🗄 アーカイブしました（Telegram がこのスレッドを削除しなかったため、手動で削除してください）。",
    "done_no_text": "✅ 完了（テキストの返信なし）。",
    "private_only": "申し訳ありません。これはプライベートなアシスタントで、所有者にのみ応答します。",
    "link_private": "ボットとのプライベートチャットからリンクを開いてください。",
    "link_who": "あなたを確認できませんでした。ご自身のアカウントからもう一度リンクを送信してください。",
    "linked": ("<b>Harness Maxxing と連携しました。</b>\nここに書くとセッションが始まります（どのトピックにするかを"
               "確認します）。メッセージに返信すると、そのセッションを続けられます。アラートもここに届きます。"
               "/help でコマンドの一覧を表示します。"),
    "linked_threads": ("<b>Harness Maxxing と連携しました。</b>\n開いているセッションにはそれぞれ専用のスレッドが"
                       "作られます。ここ（メインチャット）に書くと新しいセッションが始まります。/help でコマンドの"
                       "一覧を表示します。"),
    "ev_gone": "この通知はもう存在しません。", "ev_no_sessions": "セッションを利用できません。",
    "ev_opened": "開きました：{name}", "ev_started": "セッションを開始しました。",
    "where_last": "↩ 続ける：{title}",
    "continued": "↩ <b>{title}</b> · {where}",
    "reply_hint": "\n<i>このメッセージに返信すると、このセッションに書き込めます。</i>",
    "card": "↩ <b>{title}</b> · {where}\n<i>このメッセージに返信すると、このセッションを続けられます。</i>",
    "recent": "最近のセッション - 1 つタップし、届いたメッセージに返信してください：",
    "no_recent": "セッションはまだありません。メッセージを書くだけで始まります。",
    "no_target": "どのセッションですか？そのメッセージのいずれかに返信してください（または /sessions）。",
    "about": "<i>{title}</i>",
    "seen_btn": "✓ 確認済み", "seen": "✓ 確認済み", "resolved": "✅ 解決済み", "cb_seen": "確認済みにしました。",
    "open_btn": "開く",
    "agent_intro": "🤖 <b>{name}</b> はここに結果を投稿します。ここに書くとタスクを任せられます。",
    "agent_started": "⏳ {name} が対応中です。",
    "agent_skipped": "{name} は開始されませんでした：{reason}。",
    "agent_command": "コマンドはセッションのスレッドで使えます。ここでは、すべてのメッセージが {name} へのタスクになります。",
    "agent_new_chat": "🆕 {name} との新しい会話：このメッセージに返信すると始まります。",
    "approval_ask": "🔐 <b>{name}</b> が次の操作の前に確認を求めています：\n<code>{what}</code>",
    "approval_btn_allow": "✅ 許可", "approval_btn_deny": "❌ 拒否",
    "approval_allow": "✅ 許可しました", "approval_deny": "❌ 拒否しました",
    "approval_timeout": "⏱ 時間内に応答がなかったため拒否しました", "approval_expired": "⏹ 期限切れ（ターンが停止しました）",
    "approval_cut": "一部のみ表示されています。許可するには Harness でリクエストを開いてください。",
    "alert_cut": "…（省略されています。開くとすべて表示されます）",
})
AGENT_REASONS = {
    "en": {"disabled": "it is switched off", "budget": "its daily budget is reached",
           "limit": "the server's daily budget is reached",
           "busy": "its run in progress holds the rest of today's budget: try again once it is done",
           "rate": "too many runs in the last hour", "missing": "it no longer exists",
           "depth": "too many hops between agents"},
    "fr": {"disabled": "il est désactivé", "budget": "son budget du jour est atteint",
           "limit": "le budget du jour du serveur est atteint",
           "busy": "le tour en cours réserve le reste de son budget du jour : réessayez quand il aura fini",
           "rate": "trop de tours dans la dernière heure", "missing": "il n'existe plus",
           "depth": "trop d'allers-retours entre agents"},
    "es": {"disabled": "está desactivado", "budget": "ha alcanzado su presupuesto diario",
           "limit": "se ha alcanzado el presupuesto diario del servidor",
           "busy": "su ejecución en curso reserva el resto del presupuesto de hoy: inténtalo de nuevo cuando termine",
           "rate": "demasiadas ejecuciones en la última hora", "missing": "ya no existe",
           "depth": "demasiados saltos entre agentes"},
    "de": {"disabled": "er ist ausgeschaltet", "budget": "sein Tagesbudget ist erreicht",
           "limit": "das Tagesbudget des Servers ist erreicht",
           "busy": "sein laufender Durchlauf belegt den Rest des heutigen Budgets: Versuch es erneut, sobald er fertig ist",
           "rate": "zu viele Läufe in der letzten Stunde", "missing": "es gibt ihn nicht mehr",
           "depth": "zu viele Weitergaben zwischen Agenten"},
    "zh": {"disabled": "它已关闭", "budget": "它的每日预算已用完",
           "limit": "服务器的每日预算已用完",
           "busy": "它正在进行的运行占用了今天剩余的预算：等它完成后再试",
           "rate": "最近一小时内运行次数过多", "missing": "它已不存在",
           "depth": "智能体之间的转交次数过多"},
    "ja": {"disabled": "オフになっています", "budget": "1 日の予算に達しました",
           "limit": "サーバーの 1 日の予算に達しました",
           "busy": "実行中の処理が今日の残りの予算を確保しています。完了してからもう一度お試しください",
           "rate": "直近 1 時間の実行回数が多すぎます", "missing": "すでに存在しません",
           "depth": "エージェント間の受け渡しが多すぎます"},
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
    "es": "Este enlace ha caducado o no es válido: crea uno nuevo en Harness Maxxing → Ajustes → Telegram "
          "y ábrelo (o escanea su código QR).",
    "de": "Dieser Link ist abgelaufen oder ungültig - erstelle einen neuen in Harness Maxxing → Einstellungen → "
          "Telegram und öffne ihn (oder scanne seinen QR-Code).",
    "zh": "此链接已过期或无效，请在 Harness Maxxing → 设置 → Telegram 中新建一个，然后打开它（或扫描其二维码）。",
    "ja": "このリンクは期限切れか無効です。Harness Maxxing → 設定 → Telegram で新しいリンクを作成し、"
          "開いてください（または QR コードをスキャンしてください）。",
}
