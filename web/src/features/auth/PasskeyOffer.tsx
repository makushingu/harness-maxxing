import * as React from "react";
import { Fingerprint, Smartphone } from "lucide-react";
import { useAddPasskey, useAuthMethods, useTotpSetup } from "@/lib/queries";
import { errorMessage } from "@/lib/api";
import { passkeyCancelled, passkeysSupported } from "@/lib/webauthn";
import { store } from "@/lib/utils";
import { useT } from "@/i18n";
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  toast,
} from "@/components/ui";
import type { TotpSetup } from "@/lib/types";
import { RecoveryCodesDialog, TotpSetupDialog } from "./TwoStepMethods";

/** Set by the sign-in page after a password sign-in: the next page offers a passkey (once per sign-in). */
export const OFFER_FLAG = "mx-offer-passkey";
const SNOOZE = "mx-passkey-offer-snooze"; // until (ms) or "never"
const SNOOZE_DAYS = 30;

export function markPasskeyOffer() {
  try {
    sessionStorage.setItem(OFFER_FLAG, "1");
  } catch {
    /* private mode: no offer */
  }
}

// Read once per page load: the component can mount more than once while the shell loads (lazy chunk, language
// chunk, Suspense); a flag taken by a first mount must still count for the next one.
let pending: boolean | undefined;

function takeOffer(): boolean {
  if (pending === undefined) {
    try {
      pending = sessionStorage.getItem(OFFER_FLAG) === "1";
      sessionStorage.removeItem(OFFER_FLAG);
    } catch {
      pending = false;
    }
  }
  return pending;
}

/** A passkey was made (here or in Settings): a later removal brings the offer back. */
export function resetPasskeyOffer() {
  store.set(SNOOZE, "");
}

function snoozed(): boolean {
  const v = store.get(SNOOZE);
  return v === "never" || (!!v && Date.now() < Number(v));
}

/** After a sign-in with the password, an offer to protect the next ones:
 *  - where passkeys work and none was made for this address: "sign in faster next time" (the passkey then signs in
 *    alone, Settings -> Security);
 *  - where they cannot (an IP address such as Tailscale's, plain http, a browser without passkeys) and no
 *    authenticator app is set: the app (a 6-digit code after the password).
 *  Later = again in 30 days, Do not ask again = never (this browser), closed without a choice = at the next password
 *  sign-in. */
export function PasskeyOffer() {
  const t = useT();
  const [wanted] = React.useState(() => takeOffer() && !snoozed());
  const { data: m } = useAuthMethods(wanted);
  const add = useAddPasskey();
  const totpSetup = useTotpSetup();
  const [setup, setSetup] = React.useState<TotpSetup | null>(null);
  const [closed, setClosedState] = React.useState(false);
  const setClosed = (v: boolean) => {
    if (v) pending = false; // answered: not again in this page load
    setClosedState(v);
  };
  const [codes, setCodes] = React.useState<string[] | null>(null);
  const here = m?.passkey_here;
  const keysHere = !!here?.ok && passkeysSupported();
  const mode: "passkey" | "totp" | null = !m
    ? null
    : keysHere
      ? m.passkeys.some((p) => here?.ok && p.rp_id === here.rp_id)
        ? null
        : "passkey"
      : m.totp.on
        ? null
        : "totp";
  const open = wanted && !closed && !!mode;
  const later = (never = false) => {
    store.set(
      SNOOZE,
      never ? "never" : String(Date.now() + SNOOZE_DAYS * 86400_000),
    );
    setClosed(true);
  };
  return (
    <>
      {/* closed without a choice (Escape, outside, the cross): not now - asked again at the next password sign-in */}
      <Dialog open={open} onOpenChange={(o) => !o && setClosed(true)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              {mode === "totp" ? (
                <Smartphone className="size-5 text-primary" />
              ) : (
                <Fingerprint className="size-5 text-primary" />
              )}
              {mode === "totp"
                ? t("twofa.offerAppTitle")
                : t("twofa.offerTitle")}
            </DialogTitle>
            <DialogDescription>
              {mode === "totp" ? t("twofa.offerAppDesc") : t("twofa.offerDesc")}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="gap-2 sm:justify-between">
            <Button variant="ghost" onClick={() => later(true)}>
              {t("twofa.offerNever")}
            </Button>
            <div className="flex gap-2">
              <Button variant="outline" onClick={() => later()}>
                {t("twofa.offerLater")}
              </Button>
              {mode === "totp" ? (
                <Button
                  loading={totpSetup.isPending}
                  onClick={() =>
                    totpSetup.mutate(undefined, {
                      onSuccess: (s) => {
                        setClosed(true);
                        setSetup(s);
                      },
                      onError: (e) => toast.error(errorMessage(e)),
                    })
                  }
                >
                  <Smartphone /> {t("twofa.appSetup")}
                </Button>
              ) : (
                <Button
                  loading={add.isPending}
                  onClick={() =>
                    add.mutate("", {
                      onSuccess: (r) => {
                        setClosed(true);
                        resetPasskeyOffer();
                        toast.success(
                          t("twofa.passkeyAdded", { name: r.passkey.name }),
                          t("twofa.offerDone"),
                        );
                        if (r.recovery_codes?.length)
                          setCodes(r.recovery_codes);
                      },
                      onError: (e) => {
                        if (!passkeyCancelled(e)) toast.error(errorMessage(e));
                      },
                    })
                  }
                >
                  <Fingerprint /> {t("twofa.offerCreate")}
                </Button>
              )}
            </div>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <TotpSetupDialog
        setup={setup}
        onClose={(c) => {
          setSetup(null);
          if (c?.length) setCodes(c);
        }}
      />
      <RecoveryCodesDialog codes={codes} onClose={() => setCodes(null)} />
    </>
  );
}
