import { authEnabled } from "../amplify-config";

export async function getJwt() {
  if (!authEnabled) return "";
  try {
    const { fetchAuthSession } = await import("aws-amplify/auth");
    const session = await fetchAuthSession();
    return session.tokens?.idToken?.toString() ?? "";
  } catch {
    return "";
  }
}
