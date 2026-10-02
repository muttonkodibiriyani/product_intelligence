import { initializeApp, type FirebaseOptions } from '@firebase/app';
import {
  browserLocalPersistence,
  indexedDBLocalPersistence,
  initializeAuth,
  onIdTokenChanged,
  sendPasswordResetEmail,
  signInWithEmailAndPassword,
  signOut as fbSignOut,
  type Auth,
  type User,
} from '@firebase/auth';

/**
 * Firebase Hosting serves the project's web config at this reserved URL, so no key is ever in
 * the source, the build or the client env. The web config identifies the project; it is not a
 * secret. Nothing else (no search or admin key) may be loaded into the client.
 */
export const FIREBASE_CONFIG_URL = '/__/firebase/init.json';

const CONFIG_FIELDS = [
  'apiKey',
  'authDomain',
  'projectId',
  'appId',
  'storageBucket',
  'messagingSenderId',
] as const;

/** Keeps only the known web-config fields, all strings; null when apiKey or projectId is missing. */
export function pickWebConfig(raw: unknown): FirebaseOptions | null {
  if (!raw || typeof raw !== 'object') return null;
  const out: Record<string, string> = {};
  for (const k of CONFIG_FIELDS) {
    const v = (raw as Record<string, unknown>)[k];
    if (typeof v === 'string' && v) out[k] = v;
  }
  return out.apiKey && out.projectId ? (out as FirebaseOptions) : null;
}

export async function loadWebConfig(
  f: typeof fetch = (...a) => fetch(...a),
): Promise<FirebaseOptions | null> {
  try {
    const res = await f(FIREBASE_CONFIG_URL, { credentials: 'omit', cache: 'no-store' });
    return res.ok ? pickWebConfig(await res.json()) : null;
  } catch {
    return null;
  }
}

export type Role = 'viewer' | 'admin';

export function roleOf(claims: Record<string, unknown>): Role | null {
  return claims.role === 'viewer' || claims.role === 'admin' ? claims.role : null;
}

export interface Session {
  email: string | null;
  role: Role | null;
  /** False when the token's claims could not be read (identity outage): the role is unknown, not absent. */
  verified: boolean;
}

/** The Firebase Auth instance plus the few calls the app makes. Token-only: no cookies anywhere. */
export function startAuth(config: FirebaseOptions) {
  const app = initializeApp(config);
  // Explicit persistence keeps the popup/redirect resolvers (and their iframes) out of the bundle.
  const auth: Auth = initializeAuth(app, {
    persistence: [indexedDBLocalPersistence, browserLocalPersistence],
  });

  return {
    /** Fires on sign-in, sign-out and every token refresh, so a changed role claim shows up. */
    watch(cb: (s: Session | null) => void): () => void {
      return onIdTokenChanged(auth, async (user: User | null) => {
        if (!user) return cb(null);
        try {
          const t = await user.getIdTokenResult();
          cb({ email: user.email, role: roleOf(t.claims), verified: true });
        } catch {
          // Token refresh failed (offline, identity service down): keep the user signed in, and
          // say the role is unknown rather than missing, so a viewer never sees "no access".
          cb({ email: user.email, role: null, verified: false });
        }
      });
    },
    /** Forces a token refresh; a new token fires `watch` again with the claims re-read. */
    async recheck(): Promise<void> {
      await auth.currentUser?.getIdToken(true);
    },
    async getToken(force: boolean): Promise<string | null> {
      return auth.currentUser ? auth.currentUser.getIdToken(force) : null;
    },
    signIn: (email: string, password: string) =>
      signInWithEmailAndPassword(auth, email, password).then(() => {}),
    sendReset: (email: string) => sendPasswordResetEmail(auth, email),
    signOut: () => fbSignOut(auth),
  };
}

export type AuthHandle = ReturnType<typeof startAuth>;

/** Firebase error codes mapped to the few messages the sign-in form shows. */
export function signInErrorKey(e: unknown): 'badCredentials' | 'tooMany' | 'network' | 'generic' {
  const code = (e as { code?: unknown } | null)?.code;
  if (
    code === 'auth/invalid-credential' ||
    code === 'auth/wrong-password' ||
    code === 'auth/user-not-found' ||
    code === 'auth/invalid-email'
  )
    return 'badCredentials';
  if (code === 'auth/too-many-requests') return 'tooMany';
  if (code === 'auth/network-request-failed') return 'network';
  return 'generic';
}

/**
 * A reset request's outcome. An unknown address reads as sent, so the form never tells anyone who
 * has an account; any other failure (too many requests, quota, network, a 403) is said, not hidden.
 */
export function resetOutcome(e: unknown): 'sent' | 'invalidEmail' | 'later' {
  const code = authCode(e);
  if (code === 'auth/user-not-found') return 'sent';
  if (code === 'auth/invalid-email' || code === 'auth/missing-email') return 'invalidEmail';
  return 'later';
}

/** The Firebase error code alone, safe to log: never the message, which can carry the address. */
export function authCode(e: unknown): string {
  const code = (e as { code?: unknown } | null)?.code;
  return typeof code === 'string' ? code : 'unknown';
}
