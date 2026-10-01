/**
 * Turns the assistant off by writing `assistant_config/current` through Firestore security
 * rules, not IAM (design §9.4). Firestore IAM cannot be scoped to one document, so the
 * subscriber's service account holds no Firestore role at all. It signs in as a dedicated
 * password account whose `role` claim is `killswitch`, and the rules let that account do exactly
 * one thing: set `enabled` to false (and `disabledBy`) on the existing config document.
 *
 * Worst case if the account's password leaks: someone can switch the assistant off. They cannot
 * switch it on, change the model or caps, or read anything.
 */

const SIGN_IN = "https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword";
const FIRESTORE = "https://firestore.googleapis.com/v1";
const TIMEOUT_MS = 10_000;

export interface KillSwitchAccount {
  readonly email: string;
  /** From Secret Manager (the function's only IAM grant is accessor on that one secret). */
  readonly password: string;
}

export interface KillSwitchTarget {
  readonly projectId: string;
  /** The project's public Web API key (identifies the project to Firebase Auth; not a secret). */
  readonly apiKey: string;
}

export class KillSwitchError extends Error {
  constructor(
    readonly step: "sign_in" | "write",
    readonly status: number | null,
  ) {
    super(`kill switch ${step} failed${status === null ? "" : ` (HTTP ${String(status)})`}`);
    this.name = "KillSwitchError";
  }
}

export interface ConfigSwitch {
  disable(disabledBy: string): Promise<void>;
}

/** `ConfigSwitch` over the Firebase Auth and Firestore REST APIs. */
export class RulesScopedSwitch implements ConfigSwitch {
  constructor(
    private readonly target: KillSwitchTarget,
    private readonly account: KillSwitchAccount,
    private readonly doFetch: typeof fetch = fetch,
  ) {}

  async disable(disabledBy: string): Promise<void> {
    const idToken = await this.signIn();
    const doc = `${FIRESTORE}/projects/${encodeURIComponent(this.target.projectId)}/databases/(default)/documents/assistant_config/current`;
    const query = new URLSearchParams([
      ["updateMask.fieldPaths", "enabled"],
      ["updateMask.fieldPaths", "disabledBy"],
      ["currentDocument.exists", "true"],
    ]);
    const response = await this.send(`${doc}?${query.toString()}`, "PATCH", {
      Authorization: `Bearer ${idToken}`,
      body: {
        fields: { enabled: { booleanValue: false }, disabledBy: { stringValue: disabledBy } },
      },
    });
    if (!response.ok) throw new KillSwitchError("write", response.status);
  }

  private async signIn(): Promise<string> {
    const url = `${SIGN_IN}?key=${encodeURIComponent(this.target.apiKey)}`;
    const response = await this.send(url, "POST", {
      body: { email: this.account.email, password: this.account.password, returnSecureToken: true },
    });
    if (!response.ok) throw new KillSwitchError("sign_in", response.status);
    const body = (await response.json().catch(() => null)) as { idToken?: unknown } | null;
    if (typeof body?.idToken !== "string" || body.idToken === "") {
      throw new KillSwitchError("sign_in", response.status);
    }
    return body.idToken;
  }

  private async send(
    url: string,
    method: "POST" | "PATCH",
    { Authorization, body }: { Authorization?: string; body: unknown },
  ): Promise<Response> {
    try {
      return await this.doFetch(url, {
        method,
        headers: {
          "Content-Type": "application/json",
          ...(Authorization === undefined ? {} : { Authorization }),
        },
        body: JSON.stringify(body),
        redirect: "error",
        signal: AbortSignal.timeout(TIMEOUT_MS),
      });
    } catch {
      // Network errors carry the URL (with the API key) in some runtimes; keep them out of logs.
      throw new KillSwitchError(url.startsWith(SIGN_IN) ? "sign_in" : "write", null);
    }
  }
}
