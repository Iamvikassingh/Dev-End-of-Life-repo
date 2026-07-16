"""
Lifecycle fallback layer tests.
All 10 cases from the spec — no real network calls, no AWS credentials.
"""
import importlib
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

# Ensure backend/ is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lifecycle"))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fresh_ts():
    return (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()


def _stale_ts():
    return (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()


def _expired_ts():
    return (datetime.now(timezone.utc) - timedelta(days=120)).isoformat()


def _make_cache(records=None):
    return {"version": 1, "records": records or []}


def _lambda_html(runtime="python3.9", dep_date="Nov 14, 2024", block_date="Feb 28, 2025"):
    """Minimal HTML that mimics the AWS Lambda runtimes page table."""
    return f"""
    <table>
      <tr><th>Name</th><th>Identifier</th><th>Deprecation</th><th>Block</th></tr>
      <tr>
        <td>Python 3.9</td>
        <td>{runtime}</td>
        <td>{dep_date}</td>
        <td>{block_date}</td>
      </tr>
    </table>
    """


def _eks_api_response(version="1.29", eol_std="2025-01-31", eol_ext="2026-01-31", status="STANDARD_SUPPORT"):
    return {
        "clusterVersions": [{
            "clusterVersion": version,
            "kubernetesPatchVersion": f"{version}.7",
            "releaseDate": datetime(2024, 1, 23, tzinfo=timezone.utc),
            "endOfStandardSupportDate": datetime.fromisoformat(f"{eol_std}T00:00:00+00:00"),
            "endOfExtendedSupportDate": datetime.fromisoformat(f"{eol_ext}T00:00:00+00:00"),
            "versionStatus": status,
        }]
    }


# ── 1. Feature flag disabled → existing behaviour preserved ───────────────────

class TestFeatureFlagDisabled(unittest.TestCase):

    def test_flag_off_no_discovery_called(self):
        """When LIFECYCLE_DISCOVERY_ENABLED is off, _lifecycle_fallback is never called."""
        import eol_collector
        importlib.reload(eol_collector)
        eol_collector._LIFECYCLE_DISCOVERY_ENABLED = False
        eol_collector.EOL_CACHE.clear()

        with patch("eol_collector.requests.get") as mock_get:
            mock_get.return_value = MagicMock(status_code=404)
            with patch("eol_collector._lifecycle_fallback") as mock_fallback:
                result = eol_collector.fetch_eol("aws-lambda", "python3.13")
                mock_fallback.assert_not_called()
                self.assertIsNone(result)

        eol_collector.EOL_CACHE.clear()


# ── 2. endoflife.date success → discovery not called ─────────────────────────

class TestEndoflifeDateSuccess(unittest.TestCase):

    def test_primary_hit_skips_fallback(self):
        import eol_collector
        eol_collector._LIFECYCLE_DISCOVERY_ENABLED = True
        eol_collector.EOL_CACHE.clear()

        eol_payload = {"eolFrom": "2025-10-01", "isEoes": False}
        with patch("eol_collector.requests.get") as mock_get:
            mock_get.return_value = MagicMock(status_code=200, json=lambda: eol_payload)
            with patch("eol_collector._lifecycle_fallback") as mock_fallback:
                result = eol_collector.fetch_eol("aws-lambda", "python3.11")
                mock_fallback.assert_not_called()
                self.assertEqual(result["eolFrom"], "2025-10-01")

        eol_collector.EOL_CACHE.clear()


# ── 3. Fresh discovered cache hit ─────────────────────────────────────────────

class TestFreshCacheHit(unittest.TestCase):

    def test_fresh_cache_returned_without_discovery(self):
        """Fresh cache record is returned; auto_discover_lifecycle is NOT called."""
        from lifecycle import cache as cache_mod

        lifecycle_payload = {"eolFrom": "2024-11-14", "isEoes": False,
                             "__meta": {"lifecycle_source": "aws_lambda_docs"}}
        fresh_record = {
            "product":        "aws-lambda",
            "version":        "python3.9",
            "lifecycle_data": lifecycle_payload,
            "discovered_at":  _fresh_ts(),
        }
        mock_cache = _make_cache([fresh_record])

        with patch.object(cache_mod, "load_discovered_cache", return_value=mock_cache):
            with patch("lifecycle.auto_discovery.auto_discover_lifecycle") as mock_disc:
                import eol_collector
                eol_collector._LIFECYCLE_DISCOVERY_ENABLED = True
                eol_collector.EOL_CACHE.clear()

                with patch("eol_collector.requests.get") as mock_get:
                    mock_get.return_value = MagicMock(status_code=404)
                    result = eol_collector.fetch_eol("aws-lambda", "python3.9")

                mock_disc.assert_not_called()
                self.assertIsNotNone(result)
                self.assertEqual(result["eolFrom"], "2024-11-14")

        eol_collector.EOL_CACHE.clear()


# ── 4. Stale cache + discovery success → cache updated ───────────────────────

class TestStaleCacheDiscoverySuccess(unittest.TestCase):

    def test_stale_cache_triggers_discovery_and_updates(self):
        from lifecycle import cache as cache_mod

        old_payload = {"eolFrom": "2024-11-14", "isEoes": False}
        stale_record = {
            "product":        "aws-lambda",
            "version":        "python3.9",
            "lifecycle_data": old_payload,
            "discovered_at":  _stale_ts(),
        }
        new_payload = {"eolFrom": "2024-11-14", "isEoes": False,
                       "__meta": {"lifecycle_source": "aws_lambda_docs", "confidence": "HIGH"}}

        upserted = []
        mock_cache = _make_cache([stale_record])

        def _mock_upsert(rec):
            upserted.append(rec)

        with patch.object(cache_mod, "load_discovered_cache", return_value=mock_cache), \
             patch.object(cache_mod, "upsert_discovered_record", side_effect=_mock_upsert), \
             patch.object(cache_mod, "save_discovered_cache"):
            with patch("lifecycle.auto_discovery.auto_discover_lifecycle", return_value=new_payload):
                import eol_collector
                eol_collector._LIFECYCLE_DISCOVERY_ENABLED = True
                eol_collector.EOL_CACHE.clear()

                with patch("eol_collector.requests.get") as mock_get:
                    mock_get.return_value = MagicMock(status_code=404)
                    result = eol_collector.fetch_eol("aws-lambda", "python3.9")

                self.assertEqual(len(upserted), 1)
                self.assertIsNotNone(result)
                self.assertIn("__meta", result)

        eol_collector.EOL_CACHE.clear()


# ── 5. Stale cache + discovery failure → stale returned ──────────────────────

class TestStaleCacheDiscoveryFailure(unittest.TestCase):

    def test_stale_used_when_discovery_fails(self):
        from lifecycle import cache as cache_mod

        stale_payload = {"eolFrom": "2024-11-14", "isEoes": False}
        stale_record  = {
            "product":        "aws-lambda",
            "version":        "python3.9",
            "lifecycle_data": stale_payload,
            "discovered_at":  _stale_ts(),
        }
        mock_cache = _make_cache([stale_record])

        with patch.object(cache_mod, "load_discovered_cache", return_value=mock_cache), \
             patch.object(cache_mod, "save_discovered_cache"):
            with patch("lifecycle.auto_discovery.auto_discover_lifecycle", return_value=None):
                import eol_collector
                eol_collector._LIFECYCLE_DISCOVERY_ENABLED = True
                eol_collector.EOL_CACHE.clear()

                with patch("eol_collector.requests.get") as mock_get:
                    mock_get.return_value = MagicMock(status_code=404)
                    result = eol_collector.fetch_eol("aws-lambda", "python3.9")

                self.assertIsNotNone(result)
                self.assertEqual(result["eolFrom"], "2024-11-14")

        eol_collector.EOL_CACHE.clear()


# ── 6. Lambda docs fixture → classifier-compatible record ─────────────────────

class TestLambdaDocsDiscovery(unittest.TestCase):

    def test_lambda_docs_returns_classifier_compatible_record(self):
        from lifecycle.auto_discovery import discover_lambda_from_docs
        from eol_collector import classify_status

        html = _lambda_html("python3.9", "Nov 14, 2024", "Feb 28, 2025")
        fake_get = lambda url, timeout=5: html  # noqa: E731

        result = discover_lambda_from_docs("python3.9", http_get=fake_get)
        self.assertIsNotNone(result)
        self.assertEqual(result["support"], "2024-11-14")
        self.assertEqual(result["eol"],     "2025-02-28")
        self.assertFalse(result["is_eoes"])

        # Must be classifier-compatible after to_classifier_shape
        from lifecycle.normalizer import to_classifier_shape
        shaped = to_classifier_shape("aws-lambda", "python3.9", result,
                                     {"id": "aws_lambda_docs", "confidence_base": "HIGH"})
        status, eol_date, days = classify_status(shaped)
        self.assertIn(status, ("EOL", "EXPIRING_SOON", "SUPPORTED"))
        self.assertIn("__meta", shaped)
        self.assertEqual(shaped["__meta"]["lifecycle_source"], "aws_lambda_docs")

    def test_lambda_docs_version_not_found_returns_none(self):
        from lifecycle.auto_discovery import discover_lambda_from_docs

        html = _lambda_html("python3.9")
        fake_get = lambda url, timeout=5: html  # noqa: E731

        result = discover_lambda_from_docs("python3.13", http_get=fake_get)
        self.assertIsNone(result)

    def test_lambda_docs_http_failure_returns_none(self):
        from lifecycle.auto_discovery import discover_lambda_from_docs

        result = discover_lambda_from_docs("python3.9", http_get=lambda url, timeout=5: None)
        self.assertIsNone(result)


# ── 7. EKS API fixture → UTC date normalization ───────────────────────────────

class TestEksApiDiscovery(unittest.TestCase):

    def test_eks_api_returns_utc_dates(self):
        from lifecycle.auto_discovery import discover_eks_from_api
        from eol_collector import classify_status
        from lifecycle.normalizer import to_classifier_shape

        mock_client = MagicMock()
        mock_client.describe_cluster_versions.return_value = _eks_api_response(
            "1.29", "2025-01-31", "2026-01-31", "STANDARD_SUPPORT"
        )
        mock_session = MagicMock()
        mock_session.client.return_value = mock_client

        result = discover_eks_from_api("1.29", boto3_session=mock_session)
        self.assertIsNotNone(result)
        # Dates must be YYYY-MM-DD (UTC)
        self.assertRegex(result["eol"], r"^\d{4}-\d{2}-\d{2}$")
        self.assertFalse(result["is_eoes"])
        self.assertEqual(result["eol"], "2025-01-31")

        # Classifier-compatible
        shaped = to_classifier_shape("amazon-eks", "1.29", result,
                                     {"id": "aws_eks_api", "confidence_base": "HIGH"})
        status, _, _ = classify_status(shaped)
        self.assertIn(status, ("EOL", "EXPIRING_SOON", "SUPPORTED", "EXTENDED_SUPPORT"))

    def test_eks_api_extended_support_sets_is_eoes(self):
        from lifecycle.auto_discovery import discover_eks_from_api

        mock_client = MagicMock()
        mock_client.describe_cluster_versions.return_value = _eks_api_response(
            "1.27", "2024-01-31", "2025-01-31", "EXTENDED_SUPPORT"
        )
        mock_session = MagicMock()
        mock_session.client.return_value = mock_client

        result = discover_eks_from_api("1.27", boto3_session=mock_session)
        self.assertIsNotNone(result)
        self.assertTrue(result["is_eoes"])
        self.assertEqual(result["eol"], "2025-01-31")  # ext EOL when is_eoes

    def test_eks_api_failure_returns_none(self):
        from lifecycle.auto_discovery import discover_eks_from_api
        from botocore.exceptions import ClientError

        mock_client = MagicMock()
        mock_client.describe_cluster_versions.side_effect = ClientError(
            {"Error": {"Code": "AccessDeniedException", "Message": "Denied"}}, "DescribeClusterVersions"
        )
        mock_session = MagicMock()
        mock_session.client.return_value = mock_client

        result = discover_eks_from_api("1.29", boto3_session=mock_session)
        self.assertIsNone(result)


# ── 8. Ubuntu month-only → None ───────────────────────────────────────────────

class TestUbuntuDiscovery(unittest.TestCase):

    def test_ubuntu_handler_always_returns_none(self):
        from lifecycle.auto_discovery import discover_ubuntu_from_vendor_docs

        result = discover_ubuntu_from_vendor_docs("22.04", http_get=lambda url, timeout=5: "<html>May 2025</html>")
        self.assertIsNone(result, "Ubuntu handler must return None for MVP (month-level precision)")

    def test_ubuntu_handler_returns_none_even_with_data(self):
        from lifecycle.auto_discovery import discover_ubuntu_from_vendor_docs

        html = "<tr><td>22.04</td><td>2027-04-30</td></tr>"
        result = discover_ubuntu_from_vendor_docs("22.04", http_get=lambda url, timeout=5: html)
        self.assertIsNone(result, "Ubuntu handler must return None for MVP")


# ── 9. No source / no match → None → UNKNOWN preserved ───────────────────────

class TestNoSourceNoMatch(unittest.TestCase):

    def test_unknown_product_returns_none(self):
        from lifecycle.auto_discovery import auto_discover_lifecycle

        # "codebuild" has no source in registry → discovery returns None
        result = auto_discover_lifecycle("codebuild", "aws/codebuild/standard:5.0")
        self.assertIsNone(result)

    def test_classify_status_unknown_from_none(self):
        from eol_collector import classify_status

        status, date_, days = classify_status(None)
        self.assertEqual(status, "UNKNOWN")
        self.assertIsNone(date_)
        self.assertIsNone(days)

    def test_feature_flag_off_preserves_unknown(self):
        import eol_collector
        eol_collector._LIFECYCLE_DISCOVERY_ENABLED = False
        eol_collector.EOL_CACHE.clear()

        with patch("eol_collector.requests.get") as mock_get:
            mock_get.return_value = MagicMock(status_code=404)
            result = eol_collector.fetch_eol("codebuild", "standard:5.0")
            self.assertIsNone(result)
            status, _, _ = eol_collector.classify_status(result)
            self.assertEqual(status, "UNKNOWN")

        eol_collector.EOL_CACHE.clear()


# ── 10. __meta appears in resource JSON via _lifecycle_fields ─────────────────

class TestLifecycleFieldsEnrichment(unittest.TestCase):

    def test_meta_fields_extracted(self):
        from eol_collector import _lifecycle_fields

        eol_data = {
            "eolFrom": "2024-11-14",
            "isEoes": False,
            "__meta": {
                "lifecycle_source": "aws_lambda_docs",
                "source_type":      "aws_official_docs",
                "source_url":       "https://docs.aws.amazon.com/...",
                "confidence":       "HIGH",
                "discovery_method": "discover_lambda_from_docs",
            },
        }
        fields = _lifecycle_fields(eol_data)
        self.assertEqual(fields["lifecycle_source"],  "aws_lambda_docs")
        self.assertEqual(fields["source_url"],         "https://docs.aws.amazon.com/...")
        self.assertEqual(fields["discovery_method"],   "discover_lambda_from_docs")
        self.assertEqual(fields["confidence"],         "HIGH")
        # HIGH confidence → review_required should NOT be set
        self.assertNotIn("review_required", fields)

    def test_medium_confidence_sets_review_required(self):
        from eol_collector import _lifecycle_fields

        eol_data = {"eolFrom": "2024-11-14", "isEoes": False,
                    "__meta": {"confidence": "MEDIUM", "lifecycle_source": "ubuntu_release_cycle"}}
        fields = _lifecycle_fields(eol_data)
        self.assertTrue(fields.get("review_required"))

    def test_no_meta_returns_endoflife_date_defaults(self):
        from eol_collector import _lifecycle_fields

        # Standard endoflife.date record — no __meta. Function now always
        # returns conservative defaults so the frontend can display source trust.
        eol_data = {"eolFrom": "2025-01-01", "isEoes": False}
        fields = _lifecycle_fields(eol_data)
        self.assertEqual(fields["lifecycle_source"], "ENDOFLIFE_DATE")
        self.assertEqual(fields["confidence"],       "MEDIUM")
        self.assertTrue(fields.get("review_required"),
                        "MEDIUM confidence should set review_required=True")

    def test_none_eol_data_returns_unknown_defaults(self):
        from eol_collector import _lifecycle_fields

        # None input means no lifecycle data found from any source.
        # Function returns UNKNOWN defaults rather than empty dict so callers
        # always have a lifecycle_source and confidence to display.
        fields = _lifecycle_fields(None)
        self.assertEqual(fields["lifecycle_source"], "UNKNOWN")
        self.assertEqual(fields["confidence"],       "UNKNOWN")
        self.assertTrue(fields.get("review_required"),
                        "UNKNOWN confidence should set review_required=True")


if __name__ == "__main__":
    unittest.main(verbosity=2)
