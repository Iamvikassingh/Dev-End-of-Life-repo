import React, { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams, Link } from "react-router-dom";
import axios from "axios";
import { API_BASE_URL } from "../utils/config";
import { setMemberSession } from "../utils/workspace";
import { CheckCircle, Loader, AlertTriangle } from "lucide-react";

export default function MemberLoginCompletePage() {
  const [searchParams]  = useSearchParams();
  const navigate        = useNavigate();
  const called          = useRef(false);

  const [status, setStatus] = useState("loading"); // loading | success | error
  const [errorMsg, setErrorMsg] = useState("");

  useEffect(() => {
    if (called.current) return;
    called.current = true;

    const wsId  = searchParams.get("wsId");
    const token = searchParams.get("token");

    if (!wsId || !token) {
      setErrorMsg("Invalid or missing link parameters. Please request a new login link.");
      setStatus("error");
      return;
    }

    (async () => {
      try {
        const { data } = await axios.post(
          `${API_BASE_URL}/workspaces/${wsId}/members/complete-login`,
          { token },
          { timeout: 10000 },
        );
        setMemberSession(
          data.workspaceId,
          data.workspaceName,
          data.memberSessionToken,
          data.role,
          data.memberId,
          data.memberName,
          data.expiresAt,
        );
        setStatus("success");
        setTimeout(() => navigate("/dashboard"), 1500);
      } catch (e) {
        const code = e?.response?.data?.error?.code;
        const msg  = e?.response?.data?.error?.message;
        if (code === "LOGIN_TOKEN_USED") {
          setErrorMsg("This login link has already been used. Please request a new one.");
        } else if (code === "LOGIN_TOKEN_EXPIRED") {
          setErrorMsg("This login link has expired (links are valid for 15 minutes). Please request a new one.");
        } else {
          setErrorMsg(msg || "Something went wrong. The link may be invalid or expired.");
        }
        setStatus("error");
      }
    })();
  }, []); // eslint-disable-line

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 to-slate-100 flex items-center justify-center p-4">
      <div className="w-full max-w-sm rounded-2xl bg-white shadow-xl p-8 space-y-6 text-center">
        {status === "loading" && (
          <>
            <div className="flex justify-center">
              <Loader size={40} className="animate-spin text-blue-500" />
            </div>
            <div>
              <h1 className="text-xl font-bold text-slate-900">Signing you in…</h1>
              <p className="text-sm text-slate-500 mt-1">Verifying your login link.</p>
            </div>
          </>
        )}

        {status === "success" && (
          <>
            <div className="flex justify-center">
              <div className="rounded-full bg-green-50 p-4">
                <CheckCircle size={36} className="text-green-500" />
              </div>
            </div>
            <div>
              <h1 className="text-xl font-bold text-slate-900">You're in!</h1>
              <p className="text-sm text-slate-500 mt-1">Redirecting to your dashboard…</p>
            </div>
          </>
        )}

        {status === "error" && (
          <>
            <div className="flex justify-center">
              <div className="rounded-full bg-red-50 p-4">
                <AlertTriangle size={36} className="text-red-500" />
              </div>
            </div>
            <div className="space-y-2">
              <h1 className="text-xl font-bold text-slate-900">Link invalid</h1>
              <p className="text-sm text-slate-500">{errorMsg}</p>
            </div>
            <Link
              to="/member-login"
              className="inline-flex items-center justify-center w-full rounded-xl bg-blue-600 px-4 py-3 text-sm font-semibold text-white hover:bg-blue-700 transition-colors">
              Request a new login link
            </Link>
          </>
        )}
      </div>
    </div>
  );
}
