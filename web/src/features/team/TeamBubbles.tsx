// Team on every page (desktop, Settings -> Features -> team_page), the Messenger way: a round Team bubble at the
// bottom right opens the chat list; a chat opens in a small window docked at the bottom of the page (up to
// MAX_WINDOWS side by side); a minimized chat becomes a round head above the bubble, with its unread count, and a new
// message brings its chat's head up (Live.tsx). Which chats are open or minimized is kept per browser (store.ts).
import * as React from "react";
import { useNavigate } from "react-router";
import { Maximize2, MessageCircle, Minus, X } from "lucide-react";
import { useTeam, type TeamChat, type TeamState } from "@/lib/queries";
import { useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { Button, Tooltip } from "@/components/ui";
import { ChatView } from "./Chat";
import { TeamSide } from "./Side";
import { ChatAvatar, chatTitle } from "./people";
import { useTeamUI } from "./store";

const WIN =
  "flex h-[min(480px,calc(100dvh-5rem))] min-h-0 flex-col overflow-hidden rounded-t-xl border border-b-0 bg-background shadow-pop animate-in fade-in-0 slide-in-from-bottom-3 duration-200";

function Badge({ n }: { n: number }) {
  if (!n) return null;
  return (
    <span className="pointer-events-none absolute -top-1 -right-1 inline-flex h-[18px] min-w-[18px] items-center justify-center rounded-full bg-destructive px-1 text-[10.5px] font-semibold text-white tabular-nums ring-2 ring-background">
      {n > 99 ? "99+" : n}
    </span>
  );
}

/** Header buttons: minimize (chat windows), the full Team page (list window), close. */
function Tools({
  chat,
  onMin,
  onClose,
}: {
  chat: string | null;
  onMin?: () => void;
  onClose: () => void;
}) {
  const t = useT();
  const navigate = useNavigate();
  return (
    <div className="flex shrink-0 items-center">
      {onMin && (
        <Tooltip content={t("team.minimize")}>
          <Button
            size="icon-sm"
            variant="ghost"
            onClick={onMin}
            aria-label={t("team.minimize")}
          >
            <Minus />
          </Button>
        </Tooltip>
      )}
      {!onMin && (
        <Tooltip content={t("team.fullPage")}>
          <Button
            size="icon-sm"
            variant="ghost"
            onClick={() => {
              if (chat) useTeamUI.getState().close(chat);
              else useTeamUI.getState().setList(false);
              navigate(
                chat ? `/team?chat=${encodeURIComponent(chat)}` : "/team",
              );
            }}
            aria-label={t("team.fullPage")}
          >
            <Maximize2 className="size-3.5" />
          </Button>
        </Tooltip>
      )}
      <Tooltip content={t("common.close")}>
        <Button
          size="icon-sm"
          variant="ghost"
          onClick={onClose}
          aria-label={t("common.close")}
        >
          <X />
        </Button>
      </Tooltip>
    </div>
  );
}

function ChatWindow({ team, id }: { team: TeamState | undefined; id: string }) {
  const ui = useTeamUI();
  return (
    <section className={cn(WIN, "w-[352px]")} data-team-window={id}>
      <ChatView
        team={team}
        chatId={id}
        compact
        headerExtra={
          <Tools
            chat={id}
            onMin={() => ui.minimize(id)}
            onClose={() => ui.close(id)}
          />
        }
      />
    </section>
  );
}

function ListWindow({ team }: { team: TeamState | undefined }) {
  const t = useT();
  const ui = useTeamUI();
  return (
    <section className={cn(WIN, "w-[340px]")} data-team-window="list">
      <div className="flex min-h-[var(--header-h)] items-center gap-2 border-b py-1.5 pr-1.5 pl-3.5">
        <span className="flex-1 text-[14.5px] font-semibold">
          {t("team.title")}
        </span>
        <Tools chat={null} onClose={() => ui.setList(false)} />
      </div>
      <TeamSide team={team} active={null} onOpen={ui.openChat} compact />
    </section>
  );
}

function Head({ team, chat }: { team: TeamState | undefined; chat: TeamChat }) {
  const t = useT();
  const ui = useTeamUI();
  const title = chatTitle(team, chat);
  return (
    <div
      className="group/head relative animate-in zoom-in-50 fade-in-0 duration-200"
      data-team-head={chat.id}
    >
      <button
        type="button"
        onClick={() => ui.openChat(chat.id)}
        aria-label={title}
        className="relative flex size-12 items-center justify-center rounded-full bg-background shadow-pop transition-transform hover:scale-105 [&>span:first-child]:scale-[1.2]"
      >
        <ChatAvatar team={team} chat={chat} />
        <Badge n={chat.muted ? 0 : chat.unread} />
      </button>
      <span className="pointer-events-none absolute top-1/2 right-full mr-3 -translate-y-1/2 rounded-lg bg-popover px-2.5 py-1.5 text-[12.5px] font-medium whitespace-nowrap text-popover-foreground opacity-0 shadow-pop transition-opacity group-hover/head:opacity-100">
        {title}
      </span>
      <button
        type="button"
        onClick={() => ui.close(chat.id)}
        aria-label={t("team.closeChat")}
        title={t("team.closeChat")}
        className="absolute -top-1 -left-1 inline-flex size-5 items-center justify-center rounded-full border bg-background text-muted-foreground opacity-0 shadow-sm transition-opacity group-hover/head:opacity-100 hover:text-foreground focus-visible:opacity-100"
      >
        <X className="size-3" />
      </button>
    </div>
  );
}

export function TeamBubbles() {
  const t = useT();
  const { data: team } = useTeam();
  const ui = useTeamUI();
  const byId = React.useMemo(
    () => new Map((team?.chats || []).map((c) => [c.id, c])),
    [team?.chats],
  );
  // Chats that left (deleted, group left) drop out once the list is known.
  const docked = team ? ui.docked.filter((id) => byId.has(id)) : ui.docked;
  const heads = (team ? ui.heads.filter((id) => byId.has(id)) : []).map((id) =>
    byId.get(id)!,
  );
  const unread =
    team?.chats.reduce((n, c) => n + (c.muted ? 0 : c.unread), 0) || 0;
  return (
    <>
      <div
        className="pointer-events-none fixed right-[84px] bottom-0 z-40 flex flex-row-reverse items-end gap-3 [&>*]:pointer-events-auto"
        data-testid="team-windows"
      >
        {ui.list && <ListWindow team={team} />}
        {[...docked].reverse().map((id) => (
          <ChatWindow key={id} team={team} id={id} />
        ))}
      </div>
      <div
        className="pointer-events-none fixed right-4 bottom-4 z-40 flex flex-col-reverse items-center gap-2.5 [&>*]:pointer-events-auto"
        data-testid="team-heads"
      >
        <Tooltip
          content={ui.list ? t("nav.teamPanelClose") : t("nav.teamPanel")}
          side="left"
        >
          <button
            type="button"
            onClick={() => ui.setList(!ui.list)}
            aria-label={t("team.title")}
            aria-expanded={ui.list}
            className={cn(
              "relative flex size-[52px] items-center justify-center rounded-full shadow-pop transition-transform hover:scale-105",
              ui.list
                ? "bg-primary text-primary-foreground"
                : "border bg-background text-primary",
            )}
          >
            <MessageCircle className="size-6" />
            <Badge n={unread} />
          </button>
        </Tooltip>
        {heads.map((c) => (
          <Head key={c.id} team={team} chat={c} />
        ))}
      </div>
    </>
  );
}
