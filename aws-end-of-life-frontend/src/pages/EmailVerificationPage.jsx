import React, { useState, useEffect } from "react";
import { useNavigate, useSearchParams, Link } from "react-router-dom";
import { CheckCircle, XCircle, Loader2, Mail } from "lucide-react";
import axios from "axios";
import { API_BASE_URL } from "../utils/config";

export default function EmailVerificationPage() {
  const [searchParams] = useSearchParams();
  const navigate        = useNavigate();
  const token           = searchParams.get("token") || "";

  const [status,  setStatus]  = useState("idle"); // idle | verifying | success | error
  const [message, setMessage] = useState("");

  useEffect(() => {
    if (!token) {
      setStatus("error");
      setMessage("No verification token found in the URL. Check your email for the correct link.");
      return;
    }
    setStatus("verifying");
    axios
      .post(`${API_BASE_URL}/auth/verify-email`, { token }, { withCredentials: true })
      .then(() => {
        setStatus("success");
        setTimeout(() => navigate("/overview", { replace: true }), 2500);
      })
      .catch(err => {
        const code = err?.response?.data?.error || "UNKNOWN";
        if (code === "TOKEN_USED") {
          setMessage("This verification link has already been used.");
        } else if (code === "TOKEN_EXPIRED") {
          setMessage("This verification link has expired. Please sign up again to get a new one.");
        } else {
          setMessage(
            err?.response?.data?.message || "Verification failed. The link may be invalid."
          );
        }
        setStatus("error");
      });
  }, [token, navigate]);

  return (
    <div className="min-h-screen flex items-center justify-center px-4"
         style={{ background: "#F0F4F8" }}>
      <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-10 max-w-md w-full text-center">

        {status === "verifying" && (
          <>
            <Loader2 size={48} className="mx-auto mb-4 text-indigo-500 animate-spin" strokeWidth={1.5} />
            <h1 className="text-xl font-bold text-slate-900 mb-1">Verifying your email…</h1>
            <p className="text-sm text-slate-500">Please wait a moment.</p>
          </>
        )}

        {status === "success" && (
          <>
            <CheckCircle size={48} className="mx-auto mb-4 text-emerald-500" strokeWidth={1.5} />
            <h1 className="text-xl font-bold text-slate-900 mb-1">Email verified!</h1>
            <p className="text-sm text-slate-500">Redirecting you to the dashboard…</p>
          </>
        )}

        {status === "error" && (
          <>
            <XCircle size={48} className="mx-auto mb-4 text-red-400" strokeWidth={1.5} />
            <h1 className="text-xl font-bold text-slate-900 mb-2">Verification failed</h1>
            <p className="text-sm text-slate-600 mb-6 leading-relaxed">{message}</p>
            <Link
              to="/overview"
              className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-slate-900 text-white
                         text-sm font-semibold hover:bg-slate-700 transition-colors"
            >
              Back to home
            </Link>
          </>
        )}

        {status === "idle" && (
          <>
            <Mail size={48} className="mx-auto mb-4 text-slate-300" strokeWidth={1.5} />
            <h1 className="text-xl font-bold text-slate-900 mb-1">Check your email</h1>
            <p className="text-sm text-slate-500">
              We sent you a verification link. Click it to activate your account.
            </p>
          </>
        )}

      </div>
    </div>
  );
}
