"""Integration-style tests for the collector using mocked AWS clients."""
import sys
import os
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch, call
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import eol_collector


FAKE_EOL_RESPONSE = {
    "eolFrom": (date.today() + timedelta(days=30)).isoformat(),
    "isEoes": False,
    "isMaintained": True,
}


@pytest.fixture(autouse=True)
def clear_cache():
    eol_collector.EOL_CACHE.clear()
    eol_collector.SCAN_WARNINGS.clear()
    yield
    eol_collector.EOL_CACHE.clear()
    eol_collector.SCAN_WARNINGS.clear()


@patch("eol_collector.requests.get")
def test_fetch_eol_success(mock_get):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = FAKE_EOL_RESPONSE
    mock_get.return_value = mock_response

    result = eol_collector.fetch_eol("amazon-eks", "1.33")
    assert result == FAKE_EOL_RESPONSE
    mock_get.assert_called_once()


@patch("eol_collector.requests.get")
def test_fetch_eol_uses_cache(mock_get):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = FAKE_EOL_RESPONSE
    mock_get.return_value = mock_response

    eol_collector.fetch_eol("amazon-eks", "1.33")
    eol_collector.fetch_eol("amazon-eks", "1.33")
    # Second call should use cache — API only called once
    assert mock_get.call_count == 1


@patch("eol_collector.requests.get")
def test_fetch_eol_404_returns_none(mock_get):
    mock_response = MagicMock()
    mock_response.status_code = 404
    mock_get.return_value = mock_response

    result = eol_collector.fetch_eol("amazon-eks", "0.99")
    assert result is None


@patch("eol_collector.fetch_eol", return_value=FAKE_EOL_RESPONSE)
def test_collect_lambda(mock_fetch):
    client = MagicMock()
    client.get_paginator.return_value.paginate.return_value = [
        {"Functions": [
            {"FunctionArn": "arn:aws:lambda:us-east-1:123:function:my-fn", "FunctionName": "my-fn", "Runtime": "python3.12"},
            {"FunctionArn": "arn:aws:lambda:us-east-1:123:function:fn2", "FunctionName": "fn2", "Runtime": "nodejs20.x"},
        ]}
    ]
    session = MagicMock()
    session.client.return_value = client

    results = eol_collector.collect_lambda(session, "us-east-1", "123456789012")
    assert len(results) == 2
    assert results[0]["service_type"] == "Lambda"
    assert results[0]["version"] == "python3.12"
    assert results[0]["eol_status"] == "EXPIRING_SOON"


@patch("eol_collector.fetch_eol", return_value=FAKE_EOL_RESPONSE)
def test_collect_eks(mock_fetch):
    client = MagicMock()
    # EKS now uses get_paginator("list_clusters")
    client.get_paginator.return_value.paginate.return_value = [{"clusters": ["my-cluster"]}]
    client.describe_cluster.return_value = {
        "cluster": {"arn": "arn:aws:eks:us-east-1:123:cluster/my-cluster", "version": "1.33"}
    }
    session = MagicMock()
    session.client.return_value = client

    results = eol_collector.collect_eks(session, "us-east-1", "123456789012")
    assert len(results) == 1
    assert results[0]["service_type"] == "EKS"
    assert results[0]["version"] == "1.33"


@patch("eol_collector.fetch_eol", return_value=None)
def test_collect_lambda_unknown_runtime(mock_fetch):
    client = MagicMock()
    client.get_paginator.return_value.paginate.return_value = [
        {"Functions": [
            {"FunctionArn": "arn:aws:lambda:us-east-1:123:function:fn", "FunctionName": "fn", "Runtime": "provided.al2"},
        ]}
    ]
    session = MagicMock()
    session.client.return_value = client

    results = eol_collector.collect_lambda(session, "us-east-1", "123")
    # "provided" runtimes are skipped
    assert len(results) == 0


def _make_session(ec2_mock, ssm_mock=None):
    """Return a session mock that routes client() calls to the right mock."""
    session = MagicMock()
    ssm = ssm_mock or MagicMock()
    def _client(service, **kw):
        return ec2_mock if service == "ec2" else ssm
    session.client.side_effect = _client
    return session


def _wire_ec2_paginator(ec2_mock, instances):
    """Configure ec2_mock so get_paginator('describe_instances').paginate() returns instances."""
    pager = MagicMock()
    pager.paginate.return_value = [{"Reservations": [{"Instances": instances}]}]
    ec2_mock.get_paginator.return_value = pager


def _ec2_instance(iid="i-0abc", name="my-box", image_id="ami-001",
                  platform="Linux/UNIX", itype="t3.medium"):
    return {
        "InstanceId":      iid,
        "ImageId":         image_id,
        "InstanceType":    itype,
        "PlatformDetails": platform,
        "Tags":            [{"Key": "Name", "Value": name}],
    }


def _ami(image_id="ami-001", name="amzn2-ami-hvm", desc="Amazon Linux 2", dep_time=""):
    ami = {"ImageId": image_id, "Name": name, "Description": desc}
    if dep_time:
        ami["DeprecationTime"] = dep_time
    return ami


def _ssm_mock_with(instance_map: dict):
    """Return an SSM mock whose paginator yields InstanceInformationList from instance_map."""
    ssm = MagicMock()
    info_list = [
        {"InstanceId": iid, "PlatformName": name.split(" ")[0] if " " in name else name,
         "PlatformVersion": " ".join(name.split(" ")[1:]) if " " in name else ""}
        for iid, name in instance_map.items()
    ]
    ssm.get_paginator.return_value.paginate.return_value = [{"InstanceInformationList": info_list}]
    return ssm


def test_collect_ec2_amis_ssm_os_detection():
    """SSM-provided OS label (Amazon Linux 2) is used → EXPIRING_SOON."""
    iid = "i-0amzn2"
    ec2 = MagicMock()
    _wire_ec2_paginator(ec2, [_ec2_instance(iid=iid, name="web-prod-01", image_id="ami-amzn2")])
    ec2.describe_images.return_value = {"Images": [_ami(image_id="ami-amzn2", name="amzn2-ami-hvm-x86_64")]}

    ssm = MagicMock()
    ssm.get_paginator.return_value.paginate.return_value = [{
        "InstanceInformationList": [
            {
                "InstanceId": iid,
                "PlatformName": "Amazon Linux",
                "PlatformVersion": "2",
                "PlatformType": "Linux",
                "ComputerName": "web-prod-01",
                "PingStatus": "Online",
            }
        ]
    }]

    results = eol_collector.collect_ec2_amis(_make_session(ec2, ssm), "us-east-1", "123456789012")
    assert len(results) == 1
    r = results[0]
    assert r["service_type"] == "EC2"
    assert r["eol_status"] in ("EOL", "EXPIRING_SOON")
    assert r["eol_date"] == "2026-06-30"
    assert r["os_source"] == "SSM_INVENTORY"
    assert r["detection_source"] == "SSM_INVENTORY"
    assert r["confidence"] == "HIGH"
    assert r["ssm_managed"] is True
    assert r["ssm_platform_name"] == "Amazon Linux"
    assert r["ssm_platform_version"] == "2"
    assert r["ssm_platform_type"] == "Linux"
    assert r["ssm_computer_name"] == "web-prod-01"
    assert r["ssm_agent_status"] == "Online"
    assert r["instance_type"] == "t3.medium"
    assert "arn:aws:ec2:us-east-1:123456789012:instance/i-0amzn2" == r["resource_id"]


def test_collect_ec2_amis_ami_fallback_centos7():
    """No SSM data → falls back to AMI name pattern → CentOS 7 → EOL."""
    iid = "i-0centos"
    ec2 = MagicMock()
    _wire_ec2_paginator(ec2, [_ec2_instance(iid=iid, name="old-worker", image_id="ami-centos7")])
    ec2.describe_images.return_value = {
        "Images": [_ami(image_id="ami-centos7", name="CentOS-7-x86_64-GenericCloud", desc="CentOS 7")]
    }
    ssm = MagicMock()
    ssm.get_paginator.return_value.paginate.return_value = [{"InstanceInformationList": []}]

    results = eol_collector.collect_ec2_amis(_make_session(ec2, ssm), "us-east-1", "123456789012")
    assert len(results) == 1
    r = results[0]
    assert r["version"] == "CentOS 7"
    assert r["eol_status"] == "EOL"
    assert r["eol_date"] == "2024-06-30"
    assert r["os_source"] == "AMI_METADATA"
    assert r["detection_source"] == "AMI_METADATA"
    assert r["confidence"] == "MEDIUM"
    assert r["ssm_managed"] is False


def test_collect_ec2_amis_deprecated_ami():
    """AMI with past DeprecationTime and unknown OS → EOL."""
    iid = "i-0dep"
    ec2 = MagicMock()
    _wire_ec2_paginator(ec2, [_ec2_instance(iid=iid, name="old-box", image_id="ami-dep")])
    ec2.describe_images.return_value = {
        "Images": [_ami(image_id="ami-dep", name="custom-build-2022", desc="Internal image",
                        dep_time="2023-01-01T00:00:00Z")]
    }
    ssm = MagicMock()
    ssm.get_paginator.return_value.paginate.return_value = [{"InstanceInformationList": []}]

    results = eol_collector.collect_ec2_amis(_make_session(ec2, ssm), "us-east-1", "123456789012")
    assert len(results) == 1
    r = results[0]
    assert r["eol_status"] == "EOL"


def test_collect_ec2_amis_unknown_os():
    """Cannot detect OS, AMI not deprecated → UNKNOWN status."""
    iid = "i-0mystery"
    ec2 = MagicMock()
    _wire_ec2_paginator(ec2, [_ec2_instance(iid=iid, name="mystery-box", image_id="ami-xyz")])
    ec2.describe_images.return_value = {
        "Images": [_ami(image_id="ami-xyz", name="internal-custom-image", desc="Custom internal build")]
    }
    ssm = MagicMock()
    ssm.get_paginator.return_value.paginate.return_value = [{"InstanceInformationList": []}]

    results = eol_collector.collect_ec2_amis(_make_session(ec2, ssm), "us-east-1", "123456789012")
    assert len(results) == 1
    r = results[0]
    assert r["eol_status"] == "UNKNOWN"
    assert r["version"] == "Unknown OS"
    assert r["eol_date"] is None
    assert r["os_source"] == "UNKNOWN"
    assert r["detection_source"] == "UNKNOWN"
    assert r["confidence"] == "LOW"
    assert r["ssm_managed"] is False


def test_collect_ec2_amis_no_instances():
    """No running/stopped instances → empty list."""
    ec2 = MagicMock()
    _wire_ec2_paginator(ec2, [])
    ssm = MagicMock()
    ssm.get_paginator.return_value.paginate.return_value = [{"InstanceInformationList": []}]

    results = eol_collector.collect_ec2_amis(_make_session(ec2, ssm), "us-east-1", "123456789012")
    assert results == []


def test_detect_ec2_os_patterns():
    """_detect_ec2_os correctly identifies common OS patterns."""
    cases = [
        ("amzn2-ami-hvm-2.0.20240101.0-x86_64-gp2",                 "", "Linux/UNIX", "Amazon Linux 2",    "2026-06-30"),
        ("CentOS-7-x86_64-GenericCloud",                             "", "Linux/UNIX", "CentOS 7",          "2024-06-30"),
        ("ubuntu/images/hvm-ssd/ubuntu-22.04-amd64",                 "", "Linux/UNIX", "Ubuntu 22.04",      "2027-04-30"),
        ("ubuntu-24.04-server-cloudimg-amd64",                       "", "Linux/UNIX", "Ubuntu 24.04",      "2029-05-31"),
        ("al2023-ami-2023.0.20240101",                               "", "Linux/UNIX", "Amazon Linux 2023", "2028-03-15"),
        # Ubuntu codenames — the key improvement
        ("ubuntu/images/hvm-ssd/ubuntu-focal-20.04-amd64-server",    "", "Linux/UNIX", "Ubuntu 20.04",      "2025-05-31"),
        ("ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server",    "", "Linux/UNIX", "Ubuntu 22.04",      "2027-04-30"),
        ("ubuntu/images/hvm-ssd/ubuntu-noble-24.04-amd64-server",    "", "Linux/UNIX", "Ubuntu 24.04",      "2029-05-31"),
        ("ubuntu/images/hvm-ssd/ubuntu-bionic-18.04-amd64-server",   "", "Linux/UNIX", "Ubuntu 18.04",      "2023-04-30"),
        # SSM-style labels (PlatformName + PlatformVersion concatenated)
        ("CentOS Linux 7",  "CentOS Linux 7",  "", "CentOS 7",  "2024-06-30"),
        ("Debian GNU/Linux 11", "Debian GNU/Linux 11", "", "Debian 11", "2026-08-31"),
        ("Debian GNU/Linux 12", "Debian GNU/Linux 12", "", "Debian 12", "2028-06-30"),
    ]
    for ami_name, ami_desc, platform, expected_label, expected_eol in cases:
        label, eol = eol_collector._detect_ec2_os(ami_name, ami_desc, platform)
        assert label == expected_label, f"Pattern mismatch for '{ami_name}': got '{label}'"
        assert eol   == expected_eol,   f"EOL mismatch for '{ami_name}': got '{eol}'"


def test_collect_ec2_amis_recommendation_field():
    """collect_ec2_amis result includes recommendation and os_source fields."""
    iid = "i-0amzn2rec"
    ec2 = MagicMock()
    _wire_ec2_paginator(ec2, [_ec2_instance(iid=iid, name="web-server", image_id="ami-amzn2rec")])
    ec2.describe_images.return_value = {"Images": [_ami(image_id="ami-amzn2rec", name="amzn2-ami-hvm-2.0.20240101-x86_64-gp2")]}
    ssm = MagicMock()
    ssm.get_paginator.return_value.paginate.return_value = [{"InstanceInformationList": []}]

    results = eol_collector.collect_ec2_amis(_make_session(ec2, ssm), "us-east-1", "123456789012")
    assert len(results) == 1
    r = results[0]
    assert r["version"] == "Amazon Linux 2"
    assert r["os_source"] == "AMI_METADATA"
    assert r["detection_source"] == "AMI_METADATA"
    assert r["confidence"] == "MEDIUM"
    assert "Amazon Linux 2023" in r["recommendation"]
    assert r["image_name"] == "amzn2-ami-hvm-2.0.20240101-x86_64-gp2"


def test_collect_ec2_amis_unknown_recommendation():
    """UNKNOWN OS includes SSM-enable recommendation."""
    iid = "i-0unknown-rec"
    ec2 = MagicMock()
    _wire_ec2_paginator(ec2, [_ec2_instance(iid=iid, name="mystery", image_id="ami-custom")])
    ec2.describe_images.return_value = {"Images": [_ami(image_id="ami-custom", name="internal-build-2022", desc="Custom internal build")]}
    ssm = MagicMock()
    ssm.get_paginator.return_value.paginate.return_value = [{"InstanceInformationList": []}]

    results = eol_collector.collect_ec2_amis(_make_session(ec2, ssm), "us-east-1", "123456789012")
    r = results[0]
    assert r["eol_status"] == "UNKNOWN"
    assert r["os_source"] == "UNKNOWN"
    assert r["confidence"] == "LOW"
    assert "SSM Inventory" in r["recommendation"]


def test_ssm_os_map_centos_linux_normalization():
    """SSM 'CentOS Linux 7' should normalize to 'CentOS 7' via pattern detection."""
    ssm = MagicMock()
    ssm.get_paginator.return_value.paginate.return_value = [{
        "InstanceInformationList": [
            {"InstanceId": "i-0centos", "PlatformName": "CentOS Linux", "PlatformVersion": "7"},
        ]
    }]
    session = MagicMock()
    session.client.return_value = ssm

    result, unavailable = eol_collector._ssm_os_map(session, "us-east-1")
    assert unavailable is False
    assert result.get("i-0centos")["os_label"] == "CentOS 7"


def test_ssm_os_map_debian_gnu_normalization():
    """SSM 'Debian GNU/Linux 11' should normalize to 'Debian 11'."""
    ssm = MagicMock()
    ssm.get_paginator.return_value.paginate.return_value = [{
        "InstanceInformationList": [
            {"InstanceId": "i-0debian", "PlatformName": "Debian GNU/Linux", "PlatformVersion": "11"},
        ]
    }]
    session = MagicMock()
    session.client.return_value = ssm

    result, unavailable = eol_collector._ssm_os_map(session, "us-east-1")
    assert unavailable is False
    assert result.get("i-0debian")["os_label"] == "Debian 11"


def test_collect_ec2_amis_ssm_permission_missing_falls_back_with_warning():
    """SSM access errors do not fail EC2 scan; AMI metadata is used with a warning."""
    iid = "i-0amzn2-no-ssm"
    ec2 = MagicMock()
    _wire_ec2_paginator(ec2, [_ec2_instance(iid=iid, name="web-server", image_id="ami-amzn2")])
    ec2.describe_images.return_value = {"Images": [_ami(image_id="ami-amzn2", name="amzn2-ami-hvm-2.0.20240101-x86_64-gp2")]}
    ssm = MagicMock()
    ssm.get_paginator.side_effect = eol_collector.ClientError(
        {"Error": {"Code": "AccessDeniedException", "Message": "not authorized"}},
        "DescribeInstanceInformation",
    )

    results = eol_collector.collect_ec2_amis(_make_session(ec2, ssm), "us-east-1", "123456789012")

    assert len(results) == 1
    r = results[0]
    assert r["version"] == "Amazon Linux 2"
    assert r["os_source"] == "AMI_METADATA"
    assert r["confidence"] == "MEDIUM"
    assert r["ssm_managed"] is False
    assert r["ssm_inventory_unavailable"] is True
    assert r["scan_warning"] == eol_collector.SSM_INVENTORY_WARNING


def test_collect_codebuild_project_environment_metadata():
    client = MagicMock()
    client.get_paginator.return_value.paginate.return_value = [{"projects": ["legacy-build"]}]
    client.batch_get_projects.return_value = {"projects": [{
        "name": "legacy-build",
        "arn": "arn:aws:codebuild:us-east-1:123456789012:project/legacy-build",
        "environment": {
            "image": "aws/codebuild/standard:5.0",
            "type": "LINUX_CONTAINER",
            "computeType": "BUILD_GENERAL1_SMALL",
            "privilegedMode": True,
        },
    }]}
    session = MagicMock()
    session.client.return_value = client

    results = eol_collector.collect_codebuild(session, "us-east-1", "123456789012")

    assert len(results) == 1
    r = results[0]
    assert r["service_type"] == "CodeBuild"
    assert r["version"] == "aws/codebuild/standard:5.0"
    assert r["detection_source"] == "CODEBUILD_PROJECT_ENVIRONMENT"
    assert r["confidence"] == "HIGH"
    assert r["eol_status"] == "LIFECYCLE_NOT_TRACKED"
    assert r["compute_type"] == "BUILD_GENERAL1_SMALL"
    assert r["privileged_mode"] is True


def test_collect_codebuild_access_denied_records_scan_warning():
    eol_collector.SCAN_WARNINGS.clear()
    client = MagicMock()
    client.get_paginator.side_effect = eol_collector.ClientError(
        {"Error": {"Code": "AccessDeniedException", "Message": "not authorized"}},
        "ListProjects",
    )
    session = MagicMock()
    session.client.return_value = client

    assert eol_collector.collect_codebuild(session, "us-east-1", "123456789012") == []
    assert eol_collector.get_scan_warnings() == [{
        "code": "CODEBUILD_ACCESS_DENIED",
        "message": "CodeBuild scan skipped because read permission is missing.",
    }]


def test_collect_elastic_beanstalk_environment_metadata():
    client = MagicMock()
    client.get_paginator.return_value.paginate.return_value = [{"Environments": [{
        "EnvironmentName": "prod-web",
        "ApplicationName": "web",
        "EnvironmentArn": "arn:aws:elasticbeanstalk:us-east-1:123456789012:environment/web/prod-web",
        "PlatformArn": "arn:aws:elasticbeanstalk:us-east-1::platform/Python 3.8 running on 64bit Amazon Linux 2/3.4.1",
        "SolutionStackName": "64bit Amazon Linux 2 v3.4.1 running Python 3.8",
        "Status": "Ready",
    }]}]
    session = MagicMock()
    session.client.return_value = client

    results = eol_collector.collect_elastic_beanstalk(session, "us-east-1", "123456789012")

    assert len(results) == 1
    r = results[0]
    assert r["service_type"] == "ElasticBeanstalk"
    assert r["resource_type"] == "Elastic Beanstalk Environment"
    assert r["detection_source"] == "ELASTIC_BEANSTALK_ENVIRONMENT"
    assert r["confidence"] == "HIGH"
    assert r["application_name"] == "web"
    assert r["environment_status"] == "Ready"


def test_collect_emr_release_label_metadata():
    client = MagicMock()
    client.get_paginator.return_value.paginate.return_value = [{"Clusters": [{"Id": "j-123", "Name": "analytics"}]}]
    client.describe_cluster.return_value = {"Cluster": {
        "Id": "j-123",
        "Name": "analytics",
        "ClusterArn": "arn:aws:elasticmapreduce:us-east-1:123456789012:cluster/j-123",
        "ReleaseLabel": "emr-6.10.0",
        "Status": {"State": "WAITING"},
        "Applications": [{"Name": "Spark"}, {"Name": "Hive"}],
    }}
    session = MagicMock()
    session.client.return_value = client

    results = eol_collector.collect_emr(session, "us-east-1", "123456789012")

    assert len(results) == 1
    r = results[0]
    assert r["service_type"] == "EMR"
    assert r["version"] == "emr-6.10.0"
    assert r["detection_source"] == "EMR_CLUSTER"
    assert r["confidence"] == "HIGH"
    assert r["applications"] == "Spark, Hive"


@patch("eol_collector.fetch_eol", return_value=None)
def test_collect_glue_deeper_job_metadata(mock_fetch):
    client = MagicMock()
    client.get_paginator.return_value.paginate.return_value = [{"Jobs": [{
        "Name": "etl-daily",
        "GlueVersion": "4.0",
        "WorkerType": "G.1X",
        "Command": {"Name": "glueetl", "PythonVersion": "3", "ScriptLocation": "s3://scripts/etl.py"},
    }]}]
    session = MagicMock()
    session.client.return_value = client

    results = eol_collector.collect_glue(session, "us-east-1", "123456789012")

    assert len(results) == 1
    r = results[0]
    assert r["service_type"] == "Glue"
    assert r["version"] == "Glue 4.0 / Python 3"
    assert r["detection_source"] == "GLUE_JOB_CONFIG"
    assert r["confidence"] == "HIGH"
    assert r["worker_type"] == "G.1X"
    assert r["command_name"] == "glueetl"


@patch("eol_collector.fetch_eol", return_value=None)
def test_collect_msk_deeper_cluster_metadata(mock_fetch):
    client = MagicMock()
    client.get_paginator.return_value.paginate.return_value = [{"ClusterInfoList": [{
        "ClusterArn": "arn:aws:kafka:us-east-1:123456789012:cluster/events/abc",
        "ClusterName": "events",
        "CurrentVersion": "K13V1IB3VIYZZH",
        "State": "ACTIVE",
        "Provisioned": {
            "NumberOfBrokerNodes": 3,
            "CurrentBrokerSoftwareInfo": {"KafkaVersion": "3.7.0"},
        },
    }]}]
    session = MagicMock()
    session.client.return_value = client

    results = eol_collector.collect_msk(session, "us-east-1", "123456789012")

    assert len(results) == 1
    r = results[0]
    assert r["service_type"] == "MSK"
    assert r["version"] == "3.7.0"
    assert r["detection_source"] == "MSK_CLUSTER_INFO"
    assert r["confidence"] == "HIGH"
    assert r["broker_node_count"] == 3


def test_collect_cloudfront_functions_global_only():
    session = MagicMock()
    assert eol_collector.collect_cloudfront_functions(session, "ap-south-1", "123456789012") == []

    client = MagicMock()
    client.list_functions.return_value = {"FunctionList": {"Items": [{
        "Name": "viewer-rewrite",
        "Status": "LIVE",
        "FunctionMetadata": {
            "FunctionARN": "arn:aws:cloudfront::123456789012:function/viewer-rewrite",
            "Stage": "LIVE",
        },
        "FunctionConfig": {"Runtime": "cloudfront-js-2.0"},
    }]}}
    session.client.return_value = client

    results = eol_collector.collect_cloudfront_functions(session, "us-east-1", "123456789012")

    assert len(results) == 1
    r = results[0]
    assert r["service_type"] == "CloudFrontFunctions"
    assert r["region"] == "global"
    assert r["version"] == "cloudfront-js-2.0"
    assert r["detection_source"] == "CLOUDFRONT_FUNCTION"


def test_collect_ecr_metadata_unknown_lifecycle():
    pushed = datetime(2026, 1, 2)
    client = MagicMock()
    client.get_paginator.side_effect = [
        MagicMock(paginate=MagicMock(return_value=[{"repositories": [{"repositoryName": "app"}]}])),
        MagicMock(paginate=MagicMock(return_value=[{"imageDetails": [{
            "imageDigest": "sha256:abc",
            "imageTags": ["latest"],
            "imagePushedAt": pushed,
        }]}])),
    ]
    session = MagicMock()
    session.client.return_value = client

    results = eol_collector.collect_ecr(session, "us-east-1", "123456789012")

    assert len(results) == 1
    r = results[0]
    assert r["service_type"] == "ECR"
    assert r["eol_status"] == "LIFECYCLE_NOT_TRACKED"
    assert r["detection_source"] == "ECR_IMAGE_METADATA"
    assert r["confidence"] == "LOW"
    assert r["repository_name"] == "app"
    assert r["image_tag"] == "latest"
    assert "ECR" in r["classification_reason"]


def _make_rds_client(instances=None, clusters=None):
    """Return a mock RDS client whose paginators yield the given instances/clusters."""
    client = MagicMock()
    inst_pager    = MagicMock()
    cluster_pager = MagicMock()
    inst_pager.paginate.return_value    = [{"DBInstances": instances or []}]
    cluster_pager.paginate.return_value = [{"DBClusters":  clusters  or []}]
    def _pager(name):
        return cluster_pager if "cluster" in name else inst_pager
    client.get_paginator.side_effect = _pager
    return client


def _rds_instance(identifier="mydb", engine="mysql", version="5.7.44",
                  arn="arn:aws:rds:us-east-1:123:db:mydb"):
    return {
        "DBInstanceArn":        arn,
        "DBInstanceIdentifier": identifier,
        "Engine":               engine,
        "EngineVersion":        version,
    }


def _rds_cluster(identifier="mycluster", engine="aurora-mysql", version="8.0.32",
                 arn="arn:aws:rds:us-east-1:123:cluster:mycluster"):
    return {
        "DBClusterArn":        arn,
        "DBClusterIdentifier": identifier,
        "Engine":              engine,
        "EngineVersion":       version,
    }


@patch("eol_collector.fetch_eol")
def test_collect_rds_expiring_soon(mock_fetch):
    """RDS MySQL 8.0 EXPIRING_SOON → correct fields emitted."""
    from datetime import date, timedelta
    eol_date = (date.today() + timedelta(days=90)).isoformat()
    mock_fetch.return_value = {"eolFrom": eol_date, "isEoes": False, "support": None}

    client  = _make_rds_client(instances=[_rds_instance(version="8.0.35")])
    session = MagicMock()
    session.client.return_value = client

    results = eol_collector.collect_rds(session, "us-east-1", "123456789012")
    assert len(results) == 1
    r = results[0]
    assert r["service_type"] == "RDS_mysql"
    assert r["eol_status"]   == "EXPIRING_SOON"
    assert r["engine"]       == "mysql"
    assert "8.4" in r["recommendation"]
    assert r["final_eol_date"] == eol_date


@patch("eol_collector.fetch_eol")
def test_collect_rds_extended_support(mock_fetch):
    """RDS MySQL 5.7: standard support past, extended support active → EXTENDED_SUPPORT."""
    from datetime import date, timedelta
    std_end  = (date.today() - timedelta(days=300)).isoformat()
    final_eol = (date.today() + timedelta(days=400)).isoformat()
    mock_fetch.return_value = {
        "support": std_end,
        "eolFrom": final_eol,
        "isEoes":  True,
    }

    client  = _make_rds_client(instances=[_rds_instance(version="5.7.44")])
    session = MagicMock()
    session.client.return_value = client

    results = eol_collector.collect_rds(session, "us-east-1", "123456789012")
    assert len(results) == 1
    r = results[0]
    assert r["eol_status"]      == "EXTENDED_SUPPORT"
    assert r["support_end_date"] == std_end
    assert r["final_eol_date"]   == final_eol
    assert "extended support charges" in r["recommendation"]


@patch("eol_collector.fetch_eol")
def test_collect_rds_aurora_postgresql(mock_fetch):
    """Aurora PostgreSQL cluster → Aurora_PostgreSQL service_type with correct fields."""
    from datetime import date, timedelta
    std_end   = (date.today() - timedelta(days=100)).isoformat()
    final_eol = (date.today() + timedelta(days=500)).isoformat()
    mock_fetch.return_value = {"support": std_end, "eolFrom": final_eol, "isEoes": True}

    client  = _make_rds_client(clusters=[_rds_cluster(engine="aurora-postgresql", version="13.8")])
    session = MagicMock()
    session.client.return_value = client

    results = eol_collector.collect_rds(session, "us-east-1", "123456789012")
    assert len(results) == 1
    r = results[0]
    assert r["service_type"]  == "Aurora_PostgreSQL"
    assert r["eol_status"]    == "EXTENDED_SUPPORT"
    assert "16" in r["recommendation"]


@patch("eol_collector.fetch_eol")
def test_collect_rds_postgresql_major_version(mock_fetch):
    """RDS PostgreSQL version '14.12' must look up lifecycle key '14', not '14.12'."""
    from datetime import date, timedelta
    eol_date = (date.today() + timedelta(days=200)).isoformat()
    mock_fetch.return_value = {"eolFrom": eol_date, "isEoes": False, "support": None}

    client  = _make_rds_client(instances=[_rds_instance(engine="postgres", version="14.12")])
    session = MagicMock()
    session.client.return_value = client

    eol_collector.collect_rds(session, "us-east-1", "123456789012")
    # fetch_eol must be called with major="14", not "14.12"
    mock_fetch.assert_called_once_with("amazon-rds-postgresql", "14")


@patch("eol_collector.fetch_eol")
def test_collect_rds_instance_metadata_fields(mock_fetch):
    """RDS DB instance includes db_instance_class, db_instance_status, multi_az."""
    from datetime import date, timedelta
    eol_date = (date.today() + timedelta(days=300)).isoformat()
    mock_fetch.return_value = {"eolFrom": eol_date, "isEoes": False, "support": None}

    instance = {
        **_rds_instance(version="8.0.35"),
        "DBInstanceClass":  "db.t3.medium",
        "DBInstanceStatus": "available",
        "MultiAZ":          True,
    }
    client  = _make_rds_client(instances=[instance])
    session = MagicMock()
    session.client.return_value = client

    results = eol_collector.collect_rds(session, "us-east-1", "123456789012")
    r = results[0]
    assert r["db_instance_class"]  == "db.t3.medium"
    assert r["db_instance_status"] == "available"
    assert r["multi_az"] is True


def _make_eks_client(cluster_names, cluster_details):
    """Return a mock EKS client for collect_eks tests."""
    client = MagicMock()
    client.get_paginator.return_value.paginate.return_value = [{"clusters": cluster_names}]
    def _describe(name):
        return {"cluster": cluster_details.get(name, {})}
    client.describe_cluster.side_effect = lambda name: _describe(name)
    return client


@patch("eol_collector.fetch_eol", return_value={"eolFrom": "2027-10-01", "isEoes": False})
def test_collect_eks_metadata_fields(mock_fetch):
    """EKS result includes platform_version, cluster_status, endpoint access, support dates."""
    from datetime import datetime, timezone
    created = datetime(2023, 1, 15, tzinfo=timezone.utc)
    detail = {
        "arn":             "arn:aws:eks:us-east-1:123:cluster/prod",
        "name":            "prod",
        "version":         "1.29",
        "status":          "ACTIVE",
        "platformVersion": "eks.5",
        "createdAt":       created,
        "resourcesVpcConfig": {
            "endpointPublicAccess":  True,
            "endpointPrivateAccess": False,
        },
    }
    client  = _make_eks_client(["prod"], {"prod": detail})
    session = MagicMock()
    session.client.return_value = client

    results = eol_collector.collect_eks(session, "us-east-1", "123456789012")
    assert len(results) == 1
    r = results[0]
    assert r["service_type"]           == "EKS"
    assert r["version"]                == "1.29"
    assert r["platform_version"]       == "eks.5"
    assert r["cluster_status"]         == "ACTIVE"
    assert r["endpoint_public_access"] is True
    assert r["endpoint_private_access"] is False
    assert "2023" in r["created_at"]


@patch("eol_collector.fetch_eol")
def test_collect_eks_expiring_soon_recommendation(mock_fetch):
    """EKS EXPIRING_SOON → recommendation mentions upgrade."""
    from datetime import date, timedelta
    eol_date = (date.today() + timedelta(days=60)).isoformat()
    mock_fetch.return_value = {"eolFrom": eol_date, "isEoes": False, "support": None}

    detail = {
        "arn": "arn:aws:eks:us-east-1:123:cluster/old",
        "name": "old",
        "version": "1.27",
        "status": "ACTIVE",
        "platformVersion": "eks.4",
        "resourcesVpcConfig": {},
    }
    client  = _make_eks_client(["old"], {"old": detail})
    session = MagicMock()
    session.client.return_value = client

    results = eol_collector.collect_eks(session, "us-east-1", "123456789012")
    r = results[0]
    assert r["eol_status"]   == "EXPIRING_SOON"
    assert "1.27" in r["recommendation"]
    assert r["support_end_date"] is None  # no separate support date for expiring_soon
    assert r["final_eol_date"]   == eol_date


@patch("eol_collector.fetch_eol")
def test_collect_eks_extended_support(mock_fetch):
    """EKS with isEoes=True and past standard support → EXTENDED_SUPPORT."""
    from datetime import date, timedelta
    std_end   = (date.today() - timedelta(days=100)).isoformat()
    final_eol = (date.today() + timedelta(days=400)).isoformat()
    mock_fetch.return_value = {"support": std_end, "eolFrom": final_eol, "isEoes": True}

    detail = {
        "arn": "arn:aws:eks:us-east-1:123:cluster/ext",
        "name": "ext",
        "version": "1.25",
        "status": "ACTIVE",
        "platformVersion": "eks.6",
        "resourcesVpcConfig": {},
    }
    client  = _make_eks_client(["ext"], {"ext": detail})
    session = MagicMock()
    session.client.return_value = client

    results = eol_collector.collect_eks(session, "us-east-1", "123456789012")
    r = results[0]
    assert r["eol_status"]      == "EXTENDED_SUPPORT"
    assert r["support_end_date"] == std_end
    assert r["final_eol_date"]   == final_eol
    assert "Extended Support" in r["recommendation"]


@patch("eol_collector.fetch_eol", return_value=None)
def test_collect_eks_unknown_version(mock_fetch):
    """EKS with no lifecycle data → UNKNOWN."""
    detail = {
        "arn": "arn:aws:eks:us-east-1:123:cluster/unk",
        "name": "unk",
        "version": "1.99",
        "status": "ACTIVE",
        "platformVersion": "eks.1",
        "resourcesVpcConfig": {},
    }
    client  = _make_eks_client(["unk"], {"unk": detail})
    session = MagicMock()
    session.client.return_value = client

    results = eol_collector.collect_eks(session, "us-east-1", "123456789012")
    r = results[0]
    assert r["eol_status"] == "UNKNOWN"
    assert r["recommendation"] == ""


def test_storage_save_adds_ttl_and_scanned_at(tmp_path):
    """FileBackend.save_resources should stamp ttl-equivalent scanned_at on every record."""
    import os
    os.environ["STORAGE_BACKEND"] = "file"
    os.environ["EOL_DATA_DIR"] = str(tmp_path)

    # Re-import to pick up new env
    import importlib
    import storage as stor
    importlib.reload(stor)

    backend = stor.FileBackend()
    items = [{"resource_id": "arn:test", "service_type": "Lambda", "eol_status": "SUPPORTED", "days_to_eol": 365}]
    written = backend.save_resources(items)

    assert written == 1
    saved = backend.get_resources()
    assert len(saved) == 1
    assert "scanned_at" in saved[0]

    # Cleanup env
    os.environ.pop("STORAGE_BACKEND", None)
    os.environ.pop("EOL_DATA_DIR", None)


def test_file_storage_replace_resources_for_account_removes_stale_rows(tmp_path):
    import os
    os.environ["STORAGE_BACKEND"] = "file"
    os.environ["EOL_DATA_DIR"] = str(tmp_path)

    import importlib
    import storage as stor
    importlib.reload(stor)

    backend = stor.FileBackend()
    first_scan = [
        {"workspace_id": "ws-a", "account_id": "conn-a", "scan_id": "scan-1", "resource_id": f"arn:{i}", "service_type": "Lambda", "eol_status": "SUPPORTED"}
        for i in range(24)
    ]
    second_scan = [
        {"workspace_id": "ws-a", "account_id": "conn-a", "scan_id": "scan-2", "resource_id": f"arn:{i}", "service_type": "Lambda", "eol_status": "SUPPORTED"}
        for i in range(21)
    ]
    other_workspace = [
        {"workspace_id": "ws-b", "account_id": "conn-b", "scan_id": "scan-x", "resource_id": "arn:other", "service_type": "EC2", "eol_status": "SUPPORTED"}
    ]

    backend.replace_resources_for_account("ws-a", "conn-a", first_scan)
    backend.replace_resources_for_account("ws-b", "conn-b", other_workspace)
    backend.replace_resources_for_account("ws-a", "conn-a", second_scan)

    saved = backend.get_resources()
    current = [r for r in saved if r.get("workspace_id") == "ws-a" and r.get("account_id") == "conn-a"]
    assert len(current) == 21
    assert {r.get("scan_id") for r in current} == {"scan-2"}
    assert len([r for r in saved if r.get("workspace_id") == "ws-b"]) == 1

    os.environ.pop("STORAGE_BACKEND", None)
    os.environ.pop("EOL_DATA_DIR", None)


# ── ElastiCache Valkey + Redis slug routing ───────────────────────────────────

def _make_elasticache_client(clusters):
    client = MagicMock()
    client.get_paginator.return_value.paginate.return_value = [{"CacheClusters": clusters}]
    return client


@patch("eol_collector.fetch_eol", return_value={"eolFrom": "2026-08-01", "isEoes": False})
def test_collect_elasticache_redis_uses_redis_slug(mock_fetch):
    """Redis engine → amazon-elasticache-redis slug, engine field present."""
    session = MagicMock()
    session.client.return_value = _make_elasticache_client([{
        "CacheClusterId": "my-redis",
        "Engine": "redis",
        "EngineVersion": "7.0.7",
    }])

    results = eol_collector.collect_elasticache(session, "us-east-1", "123456789012")

    assert len(results) == 1
    r = results[0]
    assert r["engine"] == "redis"
    assert r["eol_status"] == "EXPIRING_SOON"
    mock_fetch.assert_called_once_with("amazon-elasticache-redis", "7.0")


@patch("eol_collector.fetch_eol", return_value={"eolFrom": "2028-01-01", "isEoes": False})
def test_collect_elasticache_valkey_uses_valkey_slug(mock_fetch):
    """Valkey engine → amazon-elasticache-valkey slug, not skipped."""
    session = MagicMock()
    session.client.return_value = _make_elasticache_client([{
        "CacheClusterId": "my-valkey",
        "Engine": "valkey",
        "EngineVersion": "7.2.6",
    }])

    results = eol_collector.collect_elasticache(session, "us-east-1", "123456789012")

    assert len(results) == 1
    r = results[0]
    assert r["engine"] == "valkey"
    assert r["service_type"] == "ElastiCache"
    assert r["eol_status"] == "SUPPORTED"
    mock_fetch.assert_called_once_with("amazon-elasticache-valkey", "7.2")


def test_collect_elasticache_valkey_not_skipped():
    """Valkey clusters (Engine='valkey') are collected, not silently skipped."""
    with patch("eol_collector.fetch_eol", return_value=None):
        session = MagicMock()
        session.client.return_value = _make_elasticache_client([
            {"CacheClusterId": "v1", "Engine": "valkey",    "EngineVersion": "7.2.6"},
            {"CacheClusterId": "r1", "Engine": "redis",     "EngineVersion": "6.2.14"},
            {"CacheClusterId": "m1", "Engine": "memcached", "EngineVersion": "1.6.22"},
        ])
        results = eol_collector.collect_elasticache(session, "us-east-1", "123456789012")
    # valkey + redis collected; memcached skipped (not in scope)
    assert len(results) == 2
    assert {r["engine"] for r in results} == {"valkey", "redis"}


# ── OpenSearch legacy Elasticsearch-mode slug routing ─────────────────────────

def _make_opensearch_client(domains):
    client = MagicMock()
    client.list_domain_names.return_value = {"DomainNames": [{"DomainName": d["DomainName"]} for d in domains]}
    client.describe_domains.return_value = {"DomainStatusList": domains}
    return client


@patch("eol_collector.fetch_eol", return_value={"eolFrom": "2025-01-01", "isEoes": True})
def test_collect_opensearch_modern_uses_opensearch_slug(mock_fetch):
    """OpenSearch_ prefix → amazon-opensearch slug, engine_mode=OpenSearch."""
    session = MagicMock()
    session.client.return_value = _make_opensearch_client([{
        "ARN": "arn:aws:es:us-east-1:123:domain/modern",
        "DomainName": "modern",
        "EngineVersion": "OpenSearch_2.17",
    }])

    results = eol_collector.collect_opensearch(session, "us-east-1", "123456789012")

    assert len(results) == 1
    r = results[0]
    assert r["version"] == "2.17"
    assert r["engine_mode"] == "OpenSearch"
    mock_fetch.assert_called_once_with("amazon-opensearch", "2.17")


@patch("eol_collector.fetch_eol", return_value={"eolFrom": "2023-08-01", "isEoes": True})
def test_collect_opensearch_elasticsearch_legacy_uses_elasticsearch_slug(mock_fetch):
    """Elasticsearch_ prefix → amazon-elasticsearch slug, engine_mode=Elasticsearch."""
    session = MagicMock()
    session.client.return_value = _make_opensearch_client([{
        "ARN": "arn:aws:es:us-east-1:123:domain/legacy",
        "DomainName": "legacy",
        "EngineVersion": "Elasticsearch_7.10",
    }])

    results = eol_collector.collect_opensearch(session, "us-east-1", "123456789012")

    assert len(results) == 1
    r = results[0]
    assert r["version"] == "7.10"
    assert r["engine_mode"] == "Elasticsearch"
    assert r["eol_status"] == "EOL"
    mock_fetch.assert_called_once_with("amazon-elasticsearch", "7.10")


@patch("eol_collector.fetch_eol", return_value=None)
def test_collect_opensearch_elasticsearch_unknown_when_no_eol_data(mock_fetch):
    """Elasticsearch_ domain with no endoflife.date data → UNKNOWN, correct slug was tried."""
    session = MagicMock()
    session.client.return_value = _make_opensearch_client([{
        "ARN": "arn:aws:es:us-east-1:123:domain/old",
        "DomainName": "old",
        "EngineVersion": "Elasticsearch_6.8",
    }])

    results = eol_collector.collect_opensearch(session, "us-east-1", "123456789012")

    assert len(results) == 1
    r = results[0]
    assert r["version"] == "6.8"
    assert r["engine_mode"] == "Elasticsearch"
    assert r["eol_status"] == "UNKNOWN"
    mock_fetch.assert_called_once_with("amazon-elasticsearch", "6.8")


# ── Amazon MQ collector ───────────────────────────────────────────────────────

def _make_mq_client(summaries, details):
    """Return a mock MQ client. details is a dict keyed by BrokerId."""
    client = MagicMock()
    client.list_brokers.return_value = {"BrokerSummaries": summaries}
    client.describe_broker.side_effect = lambda BrokerId: details[BrokerId]
    return client


@patch("eol_collector.fetch_eol", return_value={"eolFrom": "2026-08-01", "isEoes": False})
def test_collect_amazon_mq_activemq_uses_activemq_slug(mock_fetch):
    """ActiveMQ broker → amazon-mq-activemq slug, correct fields."""
    session = MagicMock()
    session.client.return_value = _make_mq_client(
        summaries=[{"BrokerId": "b-111"}],
        details={"b-111": {
            "BrokerId":                "b-111",
            "BrokerName":              "prod-activemq",
            "BrokerArn":               "arn:aws:mq:us-east-1:123:broker:b-111",
            "BrokerState":             "RUNNING",
            "EngineType":              "ACTIVEMQ",
            "EngineVersion":           "5.17.6",
            "DeploymentMode":          "SINGLE_INSTANCE",
            "AutoMinorVersionUpgrade": True,
        }},
    )

    results = eol_collector.collect_amazon_mq(session, "us-east-1", "123456789012")

    assert len(results) == 1
    r = results[0]
    assert r["service_type"]   == "AmazonMQ"
    assert r["engine_type"]    == "ACTIVEMQ"
    assert r["version"]        == "5.17.6"
    assert r["eol_status"]     == "EXPIRING_SOON"
    assert r["broker_id"]      == "b-111"
    assert r["broker_state"]   == "RUNNING"
    assert r["deployment_mode"] == "SINGLE_INSTANCE"
    assert r["auto_minor_version_upgrade"] is True
    assert r["detection_source"] == "AMAZON_MQ_BROKER_DETAIL"
    mock_fetch.assert_called_once_with("amazon-mq-activemq", "5.17")


@patch("eol_collector.fetch_eol", return_value={"eolFrom": "2027-06-01", "isEoes": False})
def test_collect_amazon_mq_rabbitmq_uses_rabbitmq_slug(mock_fetch):
    """RabbitMQ broker → amazon-mq-rabbitmq slug."""
    session = MagicMock()
    session.client.return_value = _make_mq_client(
        summaries=[{"BrokerId": "b-222"}],
        details={"b-222": {
            "BrokerId":                "b-222",
            "BrokerName":              "prod-rabbit",
            "BrokerArn":               "arn:aws:mq:us-east-1:123:broker:b-222",
            "BrokerState":             "RUNNING",
            "EngineType":              "RABBITMQ",
            "EngineVersion":           "3.11.28",
            "DeploymentMode":          "CLUSTER_MULTI_AZ",
            "AutoMinorVersionUpgrade": False,
        }},
    )

    results = eol_collector.collect_amazon_mq(session, "us-east-1", "123456789012")

    assert len(results) == 1
    r = results[0]
    assert r["engine_type"] == "RABBITMQ"
    assert r["version"]     == "3.11.28"
    assert r["eol_status"]  == "SUPPORTED"
    mock_fetch.assert_called_once_with("amazon-mq-rabbitmq", "3.11")


@patch("eol_collector.fetch_eol", return_value=None)
def test_collect_amazon_mq_unknown_when_no_eol_data(mock_fetch):
    """No lifecycle data → UNKNOWN with advisory recommendation, not crash."""
    session = MagicMock()
    session.client.return_value = _make_mq_client(
        summaries=[{"BrokerId": "b-333"}],
        details={"b-333": {
            "BrokerId":    "b-333",
            "BrokerName":  "legacy-mq",
            "BrokerArn":   "arn:aws:mq:us-east-1:123:broker:b-333",
            "BrokerState": "RUNNING",
            "EngineType":  "ACTIVEMQ",
            "EngineVersion": "5.15.14",
            "DeploymentMode": "SINGLE_INSTANCE",
            "AutoMinorVersionUpgrade": False,
        }},
    )

    results = eol_collector.collect_amazon_mq(session, "us-east-1", "123456789012")

    assert len(results) == 1
    r = results[0]
    assert r["eol_status"] == "UNKNOWN"
    assert "Amazon MQ" in r["recommendation"]
    assert r["eol_date"]   is None


def test_collect_amazon_mq_access_denied_records_warning():
    """AccessDenied on list_brokers → AMAZON_MQ_ACCESS_DENIED warning, empty result."""
    eol_collector.SCAN_WARNINGS.clear()
    client = MagicMock()
    client.list_brokers.side_effect = eol_collector.ClientError(
        {"Error": {"Code": "ForbiddenException", "Message": "not authorized"}},
        "ListBrokers",
    )
    session = MagicMock()
    session.client.return_value = client

    results = eol_collector.collect_amazon_mq(session, "us-east-1", "123456789012")

    assert results == []
    warnings = eol_collector.get_scan_warnings()
    assert any(w["code"] == "AMAZON_MQ_ACCESS_DENIED" for w in warnings)


def test_collect_amazon_mq_describe_failure_skips_broker():
    """describe_broker failure on one broker is skipped; scan continues for others."""
    with patch("eol_collector.fetch_eol", return_value={"eolFrom": "2027-01-01"}):
        client = MagicMock()
        client.list_brokers.return_value = {
            "BrokerSummaries": [{"BrokerId": "b-fail"}, {"BrokerId": "b-ok"}]
        }
        good_detail = {
            "BrokerId": "b-ok", "BrokerName": "ok-broker",
            "BrokerArn": "arn:aws:mq:us-east-1:123:broker:b-ok",
            "BrokerState": "RUNNING", "EngineType": "RABBITMQ",
            "EngineVersion": "3.12.1", "DeploymentMode": "SINGLE_INSTANCE",
            "AutoMinorVersionUpgrade": True,
        }
        def _describe(BrokerId):
            if BrokerId == "b-fail":
                raise eol_collector.ClientError(
                    {"Error": {"Code": "NotFoundException", "Message": "not found"}},
                    "DescribeBroker",
                )
            return good_detail
        client.describe_broker.side_effect = _describe
        session = MagicMock()
        session.client.return_value = client

        results = eol_collector.collect_amazon_mq(session, "us-east-1", "123456789012")

    assert len(results) == 1
    assert results[0]["broker_id"] == "b-ok"


# ── AWS DMS collector ─────────────────────────────────────────────────────────

def _make_dms_client(instances):
    """Return a mock DMS client whose paginator yields the given replication instances."""
    client = MagicMock()
    client.get_paginator.return_value.paginate.return_value = [
        {"ReplicationInstances": instances}
    ]
    return client


def _dms_instance(identifier="dms-prod", engine_version="3.5.4",
                  arn="arn:aws:dms:us-east-1:123:ri:dms-prod",
                  inst_class="dms.r5.large", status="available",
                  auto_minor=True, multi_az=False, publicly=False, storage=100):
    return {
        "ReplicationInstanceIdentifier": identifier,
        "ReplicationInstanceArn":        arn,
        "EngineVersion":                 engine_version,
        "ReplicationInstanceClass":      inst_class,
        "ReplicationInstanceStatus":     status,
        "AutoMinorVersionUpgrade":       auto_minor,
        "MultiAZ":                       multi_az,
        "PubliclyAccessible":            publicly,
        "AllocatedStorage":              storage,
    }


@patch("eol_collector.fetch_eol", return_value={"eolFrom": "2026-09-01", "isEoes": False})
def test_collect_dms_instance_fields_and_slug(mock_fetch):
    """DMS instance collected with correct fields and major.minor slug lookup."""
    session = MagicMock()
    session.client.return_value = _make_dms_client([_dms_instance()])

    results = eol_collector.collect_dms(session, "us-east-1", "123456789012")

    assert len(results) == 1
    r = results[0]
    assert r["service_type"]                == "DMS"
    assert r["version"]                     == "3.5.4"
    assert r["resource_name"]               == "dms-prod"
    assert r["detection_source"]            == "DMS_REPLICATION_INSTANCE"
    assert r["resource_type"]               == "DMS Replication Instance"
    assert r["replication_instance_class"]  == "dms.r5.large"
    assert r["replication_instance_status"] == "available"
    assert r["auto_minor_version_upgrade"]  is True
    assert r["multi_az"]                    is False
    assert r["publicly_accessible"]         is False
    assert r["allocated_storage"]           == 100
    mock_fetch.assert_called_once_with("aws-dms", "3.5")


@patch("eol_collector.fetch_eol", return_value={"eolFrom": "2026-08-15", "isEoes": False})
def test_collect_dms_expiring_soon_recommendation(mock_fetch):
    """DMS EXPIRING_SOON → recommendation includes engine version."""
    session = MagicMock()
    session.client.return_value = _make_dms_client([_dms_instance(engine_version="3.4.7")])

    results = eol_collector.collect_dms(session, "us-east-1", "123456789012")

    r = results[0]
    assert r["eol_status"] == "EXPIRING_SOON"
    assert "3.4.7" in r["recommendation"]
    mock_fetch.assert_called_once_with("aws-dms", "3.4")


@patch("eol_collector.fetch_eol", return_value=None)
def test_collect_dms_unknown_when_no_eol_data(mock_fetch):
    """No lifecycle data → UNKNOWN with advisory recommendation, no crash."""
    session = MagicMock()
    session.client.return_value = _make_dms_client([_dms_instance(engine_version="3.1.4")])

    results = eol_collector.collect_dms(session, "us-east-1", "123456789012")

    assert len(results) == 1
    r = results[0]
    assert r["eol_status"] == "UNKNOWN"
    assert "AWS DMS" in r["recommendation"]
    assert r["eol_date"]   is None


def test_collect_dms_access_denied_records_warning():
    """AccessDenied on describe_replication_instances → DMS_ACCESS_DENIED warning, empty result."""
    eol_collector.SCAN_WARNINGS.clear()
    client = MagicMock()
    client.get_paginator.side_effect = eol_collector.ClientError(
        {"Error": {"Code": "AccessDeniedException", "Message": "not authorized"}},
        "DescribeReplicationInstances",
    )
    session = MagicMock()
    session.client.return_value = client

    results = eol_collector.collect_dms(session, "us-east-1", "123456789012")

    assert results == []
    warnings = eol_collector.get_scan_warnings()
    assert any(w["code"] == "DMS_ACCESS_DENIED" for w in warnings)


@patch("eol_collector.fetch_eol", return_value=None)
def test_collect_dms_missing_engine_version_does_not_crash(mock_fetch):
    """Instance with no EngineVersion → UNKNOWN, version field shows 'Unknown version'."""
    session = MagicMock()
    session.client.return_value = _make_dms_client([{
        "ReplicationInstanceIdentifier": "dms-noversion",
        "ReplicationInstanceArn":        "arn:aws:dms:us-east-1:123:ri:dms-noversion",
        "ReplicationInstanceClass":      "dms.t3.medium",
        "ReplicationInstanceStatus":     "available",
        "AutoMinorVersionUpgrade":       False,
        "MultiAZ":                       False,
        "PubliclyAccessible":            False,
        # EngineVersion intentionally absent
    }])

    results = eol_collector.collect_dms(session, "us-east-1", "123456789012")

    assert len(results) == 1
    r = results[0]
    assert r["version"]    == "Unknown version"
    assert r["eol_status"] == "UNKNOWN"
    mock_fetch.assert_not_called()


@patch("eol_collector.fetch_eol", return_value={"eolFrom": "2028-01-01", "isEoes": False})
def test_collect_dms_arn_fallback_when_no_arn(mock_fetch):
    """When ReplicationInstanceArn is absent, ARN is constructed from region/account/identifier."""
    session = MagicMock()
    inst = _dms_instance(identifier="my-inst", arn="")
    inst.pop("ReplicationInstanceArn", None)
    session.client.return_value = _make_dms_client([inst])

    results = eol_collector.collect_dms(session, "us-east-1", "123456789012")

    r = results[0]
    assert "arn:aws:dms:us-east-1:123456789012:ri:my-inst" == r["resource_id"]


# ── Amazon MWAA collector ─────────────────────────────────────────────────────

def _make_mwaa_client(env_names, env_details):
    """Return a mock MWAA client. env_details is a dict keyed by environment name."""
    client = MagicMock()
    client.list_environments.return_value = {"Environments": env_names}
    client.get_environment.side_effect = lambda Name: {"Environment": env_details[Name]}
    return client


def _mwaa_env(name="prod-airflow", airflow_version="2.8.1",
              arn="arn:aws:airflow:us-east-1:123:environment/prod-airflow",
              status="AVAILABLE", env_class="mw1.small",
              webserver_mode="PUBLIC_ONLY", max_workers=10, min_workers=1,
              schedulers=2):
    return {
        "Name":                name,
        "Arn":                 arn,
        "AirflowVersion":      airflow_version,
        "Status":              status,
        "EnvironmentClass":    env_class,
        "WebserverAccessMode": webserver_mode,
        "MaxWorkers":          max_workers,
        "MinWorkers":          min_workers,
        "Schedulers":          schedulers,
    }


@patch("eol_collector.fetch_eol", return_value={"eolFrom": "2026-09-01", "isEoes": False})
def test_collect_mwaa_environment_fields_and_slug(mock_fetch):
    """MWAA environment collected with correct fields; major.minor slug lookup via apache-airflow."""
    session = MagicMock()
    session.client.return_value = _make_mwaa_client(
        env_names=["prod-airflow"],
        env_details={"prod-airflow": _mwaa_env()},
    )

    results = eol_collector.collect_mwaa(session, "us-east-1", "123456789012")

    assert len(results) == 1
    r = results[0]
    assert r["service_type"]         == "MWAA"
    assert r["version"]              == "2.8.1"
    assert r["airflow_version"]      == "2.8.1"
    assert r["resource_name"]        == "prod-airflow"
    assert r["detection_source"]     == "MWAA_ENVIRONMENT"
    assert r["resource_type"]        == "MWAA Environment"
    assert r["environment_class"]    == "mw1.small"
    assert r["environment_status"]   == "AVAILABLE"
    assert r["webserver_access_mode"] == "PUBLIC_ONLY"
    assert r["max_workers"]          == 10
    assert r["min_workers"]          == 1
    assert r["schedulers"]           == 2
    assert r["eol_status"]           == "EXPIRING_SOON"
    mock_fetch.assert_called_once_with("apache-airflow", "2.8")


@patch("eol_collector.fetch_eol", return_value={"eolFrom": "2026-08-10", "isEoes": False})
def test_collect_mwaa_expiring_soon_recommendation(mock_fetch):
    """MWAA EXPIRING_SOON → recommendation includes Airflow version."""
    session = MagicMock()
    session.client.return_value = _make_mwaa_client(
        env_names=["staging"],
        env_details={"staging": _mwaa_env(name="staging", airflow_version="2.7.3",
                                          arn="arn:aws:airflow:us-east-1:123:environment/staging")},
    )

    results = eol_collector.collect_mwaa(session, "us-east-1", "123456789012")

    r = results[0]
    assert r["eol_status"]   == "EXPIRING_SOON"
    assert "2.7.3" in r["recommendation"]
    mock_fetch.assert_called_once_with("apache-airflow", "2.7")


@patch("eol_collector.fetch_eol", return_value=None)
def test_collect_mwaa_unknown_when_no_eol_data(mock_fetch):
    """No lifecycle data → UNKNOWN with advisory recommendation, no crash."""
    session = MagicMock()
    session.client.return_value = _make_mwaa_client(
        env_names=["old-env"],
        env_details={"old-env": _mwaa_env(name="old-env", airflow_version="1.10.15",
                                          arn="arn:aws:airflow:us-east-1:123:environment/old-env")},
    )

    results = eol_collector.collect_mwaa(session, "us-east-1", "123456789012")

    assert len(results) == 1
    r = results[0]
    assert r["eol_status"] == "UNKNOWN"
    assert "MWAA" in r["recommendation"]
    assert r["eol_date"] is None


def test_collect_mwaa_access_denied_records_warning():
    """AccessDenied on list_environments → MWAA_ACCESS_DENIED warning, empty result."""
    eol_collector.SCAN_WARNINGS.clear()
    client = MagicMock()
    client.list_environments.side_effect = eol_collector.ClientError(
        {"Error": {"Code": "AccessDeniedException", "Message": "not authorized"}},
        "ListEnvironments",
    )
    session = MagicMock()
    session.client.return_value = client

    results = eol_collector.collect_mwaa(session, "us-east-1", "123456789012")

    assert results == []
    warnings = eol_collector.get_scan_warnings()
    assert any(w["code"] == "MWAA_ACCESS_DENIED" for w in warnings)


def test_collect_mwaa_get_environment_failure_skips_env():
    """get_environment failure on one env is skipped; scan continues for others."""
    with patch("eol_collector.fetch_eol", return_value={"eolFrom": "2027-06-01"}):
        client = MagicMock()
        client.list_environments.return_value = {"Environments": ["bad-env", "good-env"]}
        good = _mwaa_env(name="good-env", airflow_version="2.9.2",
                         arn="arn:aws:airflow:us-east-1:123:environment/good-env")

        def _get(Name):
            if Name == "bad-env":
                raise eol_collector.ClientError(
                    {"Error": {"Code": "ResourceNotFoundException", "Message": "not found"}},
                    "GetEnvironment",
                )
            return {"Environment": good}

        client.get_environment.side_effect = _get
        session = MagicMock()
        session.client.return_value = client

        results = eol_collector.collect_mwaa(session, "us-east-1", "123456789012")

    assert len(results) == 1
    assert results[0]["resource_name"] == "good-env"


@patch("eol_collector.fetch_eol", return_value=None)
def test_collect_mwaa_missing_airflow_version_does_not_crash(mock_fetch):
    """Environment with no AirflowVersion → UNKNOWN, version='Unknown version', fetch_eol not called."""
    env = {
        "Name":             "noversion-env",
        "Arn":              "arn:aws:airflow:us-east-1:123:environment/noversion-env",
        "Status":           "AVAILABLE",
        "EnvironmentClass": "mw1.medium",
        # AirflowVersion intentionally absent
    }
    session = MagicMock()
    session.client.return_value = _make_mwaa_client(
        env_names=["noversion-env"],
        env_details={"noversion-env": env},
    )

    results = eol_collector.collect_mwaa(session, "us-east-1", "123456789012")

    assert len(results) == 1
    r = results[0]
    assert r["version"]    == "Unknown version"
    assert r["eol_status"] == "UNKNOWN"
    mock_fetch.assert_not_called()


@patch("eol_collector.fetch_eol", return_value={"eolFrom": "2028-06-01", "isEoes": False})
def test_collect_mwaa_arn_fallback_when_no_arn(mock_fetch):
    """When Arn is absent, resource_id is constructed from region/account/name."""
    env = _mwaa_env(name="my-env", arn="")
    env.pop("Arn", None)
    session = MagicMock()
    session.client.return_value = _make_mwaa_client(
        env_names=["my-env"],
        env_details={"my-env": env},
    )

    results = eol_collector.collect_mwaa(session, "us-east-1", "123456789012")

    r = results[0]
    assert r["resource_id"] == "arn:aws:airflow:us-east-1:123456789012:environment/my-env"


# ── ECS Fargate collector ─────────────────────────────────────────────────────

def _make_ecs_client(clusters, services_by_cluster):
    """
    clusters: list of cluster ARNs
    services_by_cluster: dict { cluster_arn: [service_dict, ...] }
    """
    client = MagicMock()

    # list_clusters paginator
    cluster_pager = MagicMock()
    cluster_pager.paginate.return_value = [{"clusterArns": clusters}]

    # list_services paginator — keyed by cluster kwarg
    def _svc_pager(name):
        return cluster_pager if name == "list_clusters" else MagicMock(
            paginate=MagicMock(return_value=[
                {"serviceArns": [s["serviceArn"] for s in services_by_cluster.get(
                    # resolved via side_effect below
                    "", []
                )]}
            ])
        )

    # Simpler: track paginate calls by cluster kwarg
    svc_pager = MagicMock()

    def _list_svc_paginate(**kwargs):
        cluster = kwargs.get("cluster", "")
        svcs = services_by_cluster.get(cluster, [])
        return [{"serviceArns": [s["serviceArn"] for s in svcs]}]

    svc_pager.paginate.side_effect = _list_svc_paginate

    def _get_paginator(name):
        if name == "list_clusters":
            return cluster_pager
        return svc_pager

    client.get_paginator.side_effect = _get_paginator

    # describe_services
    all_services = {s["serviceArn"]: s for svcs in services_by_cluster.values() for s in svcs}

    def _describe(cluster, services):
        return {"services": [all_services[a] for a in services if a in all_services]}

    client.describe_services.side_effect = _describe
    return client


def _fargate_svc(name="web-svc", platform_version="1.4.0",
                 cluster_arn="arn:aws:ecs:us-east-1:123:cluster/prod",
                 launch_type="FARGATE", platform_family="LINUX",
                 status="ACTIVE", running=2, desired=2):
    return {
        "serviceName":    name,
        "serviceArn":     f"arn:aws:ecs:us-east-1:123:service/prod/{name}",
        "launchType":     launch_type,
        "platformVersion": platform_version,
        "platformFamily": platform_family,
        "status":         status,
        "runningCount":   running,
        "desiredCount":   desired,
    }


def test_collect_ecs_fargate_current_platform_supported():
    """Fargate service on 1.4.0 → SUPPORTED, all metadata fields present."""
    cluster_arn = "arn:aws:ecs:us-east-1:123:cluster/prod"
    svc = _fargate_svc(platform_version="1.4.0")
    session = MagicMock()
    session.client.return_value = _make_ecs_client(
        clusters=[cluster_arn],
        services_by_cluster={cluster_arn: [svc]},
    )

    results = eol_collector.collect_ecs_fargate(session, "us-east-1", "123456789012")

    assert len(results) == 1
    r = results[0]
    assert r["service_type"]     == "ECSFargate"
    assert r["version"]          == "1.4.0"
    assert r["platform_version"] == "1.4.0"
    assert r["platform_family"]  == "LINUX"
    assert r["cluster_name"]     == "prod"
    assert r["eol_status"]       == "SUPPORTED"
    assert r["eol_date"]         is None
    assert r["detection_source"] == "ECS_SERVICE"
    assert r["resource_type"]    == "ECS Fargate Service"
    assert r["running_count"]    == 2
    assert r["desired_count"]    == 2


def test_collect_ecs_fargate_retired_platform_eol():
    """Fargate service on 1.3.0 (retired April 2022) → EOL with migration recommendation."""
    cluster_arn = "arn:aws:ecs:us-east-1:123:cluster/legacy"
    svc = _fargate_svc(name="legacy-svc", platform_version="1.3.0", cluster_arn=cluster_arn)
    session = MagicMock()
    session.client.return_value = _make_ecs_client(
        clusters=[cluster_arn],
        services_by_cluster={cluster_arn: [svc]},
    )

    results = eol_collector.collect_ecs_fargate(session, "us-east-1", "123456789012")

    assert len(results) == 1
    r = results[0]
    assert r["eol_status"] == "EOL"
    assert r["eol_date"]   == "2022-04-01"
    assert "1.3.0" in r["recommendation"]
    assert "1.4.0" in r["recommendation"]


def test_collect_ecs_fargate_latest_lifecycle_not_tracked():
    """Fargate service pinned to LATEST → LIFECYCLE_NOT_TRACKED + pin recommendation."""
    cluster_arn = "arn:aws:ecs:us-east-1:123:cluster/dev"
    svc = _fargate_svc(name="dev-svc", platform_version="LATEST", cluster_arn=cluster_arn)
    session = MagicMock()
    session.client.return_value = _make_ecs_client(
        clusters=[cluster_arn],
        services_by_cluster={cluster_arn: [svc]},
    )

    results = eol_collector.collect_ecs_fargate(session, "us-east-1", "123456789012")

    assert len(results) == 1
    r = results[0]
    assert r["eol_status"] == "LIFECYCLE_NOT_TRACKED"
    assert "LATEST" in r["classification_reason"]
    assert "1.4.0" in r["recommendation"]


def test_collect_ecs_fargate_non_fargate_services_excluded():
    """EC2 launch-type ECS services are excluded; only Fargate services are collected."""
    cluster_arn = "arn:aws:ecs:us-east-1:123:cluster/mixed"
    fargate_svc = _fargate_svc(name="fg-svc", platform_version="1.4.0", cluster_arn=cluster_arn)
    ec2_svc = {
        "serviceName": "ec2-svc",
        "serviceArn":  f"arn:aws:ecs:us-east-1:123:service/mixed/ec2-svc",
        "launchType":  "EC2",
        "platformVersion": None,
        "platformFamily": None,
        "status": "ACTIVE",
        "runningCount": 1,
        "desiredCount": 1,
    }
    session = MagicMock()
    session.client.return_value = _make_ecs_client(
        clusters=[cluster_arn],
        services_by_cluster={cluster_arn: [fargate_svc, ec2_svc]},
    )

    results = eol_collector.collect_ecs_fargate(session, "us-east-1", "123456789012")

    assert len(results) == 1
    assert results[0]["resource_name"] == "fg-svc"


def test_collect_ecs_fargate_access_denied_records_warning():
    """AccessDenied on list_clusters → ECS_ACCESS_DENIED warning, empty result."""
    eol_collector.SCAN_WARNINGS.clear()
    client = MagicMock()
    client.get_paginator.side_effect = eol_collector.ClientError(
        {"Error": {"Code": "AccessDeniedException", "Message": "not authorized"}},
        "ListClusters",
    )
    session = MagicMock()
    session.client.return_value = client

    results = eol_collector.collect_ecs_fargate(session, "us-east-1", "123456789012")

    assert results == []
    warnings = eol_collector.get_scan_warnings()
    assert any(w["code"] == "ECS_ACCESS_DENIED" for w in warnings)


def test_collect_ecs_fargate_cluster_list_services_failure_continues():
    """list_services failure for one cluster is skipped; other clusters still scanned."""
    cluster_ok  = "arn:aws:ecs:us-east-1:123:cluster/ok"
    cluster_bad = "arn:aws:ecs:us-east-1:123:cluster/bad"
    ok_svc = _fargate_svc(name="ok-svc", platform_version="1.4.0", cluster_arn=cluster_ok)

    client = MagicMock()

    cluster_pager = MagicMock()
    cluster_pager.paginate.return_value = [{"clusterArns": [cluster_bad, cluster_ok]}]

    svc_pager = MagicMock()

    def _list_svc_paginate(**kwargs):
        if kwargs.get("cluster") == cluster_bad:
            raise eol_collector.ClientError(
                {"Error": {"Code": "ClusterNotFoundException", "Message": "not found"}},
                "ListServices",
            )
        return [{"serviceArns": [ok_svc["serviceArn"]]}]

    svc_pager.paginate.side_effect = _list_svc_paginate

    def _get_paginator(name):
        return cluster_pager if name == "list_clusters" else svc_pager

    client.get_paginator.side_effect = _get_paginator
    client.describe_services.return_value = {"services": [ok_svc]}
    session = MagicMock()
    session.client.return_value = client

    results = eol_collector.collect_ecs_fargate(session, "us-east-1", "123456789012")

    assert len(results) == 1
    assert results[0]["resource_name"] == "ok-svc"


def test_collect_ecs_fargate_unknown_platform_version():
    """Unrecognised platform version → UNKNOWN with advisory recommendation."""
    cluster_arn = "arn:aws:ecs:us-east-1:123:cluster/future"
    svc = _fargate_svc(name="future-svc", platform_version="2.0.0", cluster_arn=cluster_arn)
    session = MagicMock()
    session.client.return_value = _make_ecs_client(
        clusters=[cluster_arn],
        services_by_cluster={cluster_arn: [svc]},
    )

    results = eol_collector.collect_ecs_fargate(session, "us-east-1", "123456789012")

    assert len(results) == 1
    r = results[0]
    assert r["eol_status"]  == "UNKNOWN"
    assert "2.0.0" in r["classification_reason"]
    assert "ECS" in r["recommendation"]


def test_collect_ecs_fargate_capacity_provider_strategy_detected():
    """Service using FARGATE_SPOT capacity provider (no launchType) is still collected."""
    cluster_arn = "arn:aws:ecs:us-east-1:123:cluster/spot"
    svc = {
        "serviceName":    "spot-svc",
        "serviceArn":     "arn:aws:ecs:us-east-1:123:service/spot/spot-svc",
        "launchType":     "",            # not set when using capacity provider strategy
        "platformVersion": "1.4.0",
        "platformFamily": "LINUX",
        "status":         "ACTIVE",
        "runningCount":   3,
        "desiredCount":   3,
        "capacityProviderStrategy": [
            {"capacityProvider": "FARGATE_SPOT", "weight": 1, "base": 0}
        ],
    }
    session = MagicMock()
    session.client.return_value = _make_ecs_client(
        clusters=[cluster_arn],
        services_by_cluster={cluster_arn: [svc]},
    )

    results = eol_collector.collect_ecs_fargate(session, "us-east-1", "123456789012")

    assert len(results) == 1
    r = results[0]
    assert r["eol_status"]  == "SUPPORTED"
    assert r["launch_type"] == "FARGATE"  # fallback label when launchType field is empty


# ── SageMaker Notebook collector ──────────────────────────────────────────────

def _make_sagemaker_client(nb_names, nb_details):
    """nb_details is a dict keyed by notebook name."""
    client = MagicMock()
    pager = MagicMock()
    pager.paginate.return_value = [{"NotebookInstances": [{"NotebookInstanceName": n} for n in nb_names]}]
    client.get_paginator.return_value = pager
    client.describe_notebook_instance.side_effect = lambda NotebookInstanceName: nb_details[NotebookInstanceName]
    return client


def _nb_detail(name="ml-notebook", platform="notebook-al2023-v1",
               arn="arn:aws:sagemaker:us-east-1:123:notebook-instance/ml-notebook",
               status="InService", instance_type="ml.t3.medium",
               volume_gb=50, direct_inet="Enabled", root_access="Enabled",
               role_arn="arn:aws:iam::123:role/SageMakerRole"):
    return {
        "NotebookInstanceName": name,
        "NotebookInstanceArn":  arn,
        "NotebookInstanceStatus": status,
        "InstanceType":         instance_type,
        "PlatformIdentifier":   platform,
        "VolumeSizeInGB":       volume_gb,
        "DirectInternetAccess": direct_inet,
        "RootAccess":           root_access,
        "RoleArn":              role_arn,
    }


def test_collect_sagemaker_notebook_al2023_supported():
    """AL2023 notebook → SUPPORTED with all metadata fields."""
    session = MagicMock()
    session.client.return_value = _make_sagemaker_client(
        nb_names=["ml-notebook"],
        nb_details={"ml-notebook": _nb_detail()},
    )

    results = eol_collector.collect_sagemaker_notebooks(session, "us-east-1", "123456789012")

    assert len(results) == 1
    r = results[0]
    assert r["service_type"]             == "SageMakerNotebook"
    assert r["version"]                  == "notebook-al2023-v1"
    assert r["platform_identifier"]      == "notebook-al2023-v1"
    assert r["resource_name"]            == "ml-notebook"
    assert r["detection_source"]         == "SAGEMAKER_NOTEBOOK_INSTANCE"
    assert r["resource_type"]            == "SageMaker Notebook Instance"
    assert r["notebook_instance_status"] == "InService"
    assert r["instance_type"]            == "ml.t3.medium"
    assert r["volume_size_in_gb"]        == 50
    assert r["eol_status"]               == "SUPPORTED"
    assert r["eol_date"]                 is None


def test_collect_sagemaker_notebook_al2_expiring():
    """AL2 notebook platform → EOL or EXPIRING_SOON (AL2 support ends 2026-06-30)."""
    session = MagicMock()
    session.client.return_value = _make_sagemaker_client(
        nb_names=["al2-nb"],
        nb_details={"al2-nb": _nb_detail(
            name="al2-nb", platform="notebook-al2-v2",
            arn="arn:aws:sagemaker:us-east-1:123:notebook-instance/al2-nb",
        )},
    )

    results = eol_collector.collect_sagemaker_notebooks(session, "us-east-1", "123456789012")

    assert len(results) == 1
    r = results[0]
    assert r["platform_identifier"] == "notebook-al2-v2"
    assert r["eol_date"]            == "2026-06-30"
    assert r["eol_status"]          in ("EOL", "EXPIRING_SOON")
    assert "al2-v2" in r["recommendation"]
    assert "al2023" in r["recommendation"]


def test_collect_sagemaker_notebook_al1_eol():
    """AL1 notebook platform (retired Dec 2023) → EOL."""
    session = MagicMock()
    session.client.return_value = _make_sagemaker_client(
        nb_names=["legacy-nb"],
        nb_details={"legacy-nb": _nb_detail(
            name="legacy-nb", platform="notebook-al1-v1",
            arn="arn:aws:sagemaker:us-east-1:123:notebook-instance/legacy-nb",
        )},
    )

    results = eol_collector.collect_sagemaker_notebooks(session, "us-east-1", "123456789012")

    assert len(results) == 1
    r = results[0]
    assert r["eol_status"] == "EOL"
    assert r["eol_date"]   == "2023-12-31"
    assert "al1-v1" in r["recommendation"]


def test_collect_sagemaker_notebook_missing_platform_unknown():
    """No PlatformIdentifier → UNKNOWN, version='Unknown platform', no crash."""
    detail = {
        "NotebookInstanceName": "old-nb",
        "NotebookInstanceArn":  "arn:aws:sagemaker:us-east-1:123:notebook-instance/old-nb",
        "NotebookInstanceStatus": "InService",
        "InstanceType":         "ml.m5.large",
        # PlatformIdentifier absent
    }
    session = MagicMock()
    session.client.return_value = _make_sagemaker_client(
        nb_names=["old-nb"],
        nb_details={"old-nb": detail},
    )

    results = eol_collector.collect_sagemaker_notebooks(session, "us-east-1", "123456789012")

    assert len(results) == 1
    r = results[0]
    assert r["version"]    == "Unknown platform"
    assert r["eol_status"] == "UNKNOWN"
    assert "PlatformIdentifier" in r["classification_reason"]


def test_collect_sagemaker_notebook_access_denied_records_warning():
    """AccessDenied on list_notebook_instances → SAGEMAKER_ACCESS_DENIED warning, empty result."""
    eol_collector.SCAN_WARNINGS.clear()
    client = MagicMock()
    client.get_paginator.side_effect = eol_collector.ClientError(
        {"Error": {"Code": "AccessDeniedException", "Message": "not authorized"}},
        "ListNotebookInstances",
    )
    session = MagicMock()
    session.client.return_value = client

    results = eol_collector.collect_sagemaker_notebooks(session, "us-east-1", "123456789012")

    assert results == []
    warnings = eol_collector.get_scan_warnings()
    assert any(w["code"] == "SAGEMAKER_ACCESS_DENIED" for w in warnings)


def test_collect_sagemaker_notebook_describe_failure_skips_one():
    """describe_notebook_instance failure on one notebook → skipped, other collected."""
    detail_ok = _nb_detail(name="good-nb", platform="notebook-al2023-v1",
                           arn="arn:aws:sagemaker:us-east-1:123:notebook-instance/good-nb")

    client = MagicMock()
    pager = MagicMock()
    pager.paginate.return_value = [{"NotebookInstances": [
        {"NotebookInstanceName": "bad-nb"},
        {"NotebookInstanceName": "good-nb"},
    ]}]
    client.get_paginator.return_value = pager

    def _describe(NotebookInstanceName):
        if NotebookInstanceName == "bad-nb":
            raise eol_collector.ClientError(
                {"Error": {"Code": "ValidationException", "Message": "not found"}},
                "DescribeNotebookInstance",
            )
        return detail_ok

    client.describe_notebook_instance.side_effect = _describe
    session = MagicMock()
    session.client.return_value = client

    results = eol_collector.collect_sagemaker_notebooks(session, "us-east-1", "123456789012")

    assert len(results) == 1
    assert results[0]["resource_name"] == "good-nb"


def test_collect_sagemaker_notebook_arn_fallback():
    """When NotebookInstanceArn is absent, resource_id is constructed from region/account/name."""
    detail = _nb_detail(name="my-nb", platform="notebook-al2023-v1", arn="")
    detail.pop("NotebookInstanceArn", None)
    session = MagicMock()
    session.client.return_value = _make_sagemaker_client(
        nb_names=["my-nb"],
        nb_details={"my-nb": detail},
    )

    results = eol_collector.collect_sagemaker_notebooks(session, "us-east-1", "123456789012")

    r = results[0]
    assert r["resource_id"] == "arn:aws:sagemaker:us-east-1:123456789012:notebook-instance/my-nb"


# ── Elastic Beanstalk real platform retirement scoring ────────────────────────

def _make_eb_client(envs, platform_details=None):
    """
    envs: list of environment dicts for the describe_environments paginator.
    platform_details: dict {PlatformArn: PlatformDescription dict} for describe_platform_version.
                      Pass None to leave describe_platform_version unset (returns MagicMock).
                      Pass {} to simulate describe returning empty PlatformDescription.
    """
    client = MagicMock()
    client.get_paginator.return_value.paginate.return_value = [{"Environments": envs}]
    if platform_details is not None:
        def _describe(PlatformArn):
            pd = platform_details.get(PlatformArn, {})
            return {"PlatformDescription": pd}
        client.describe_platform_version.side_effect = _describe
    return client


def _eb_env(name="prod-web", app="web",
            arn="arn:aws:elasticbeanstalk:us-east-1:123:environment/web/prod-web",
            platform_arn="arn:aws:elasticbeanstalk:us-east-1::platform/Python 3.11 running on 64bit Amazon Linux 2023/4.0.2",
            stack="64bit Amazon Linux 2023 v4.0.2 running Python 3.11",
            status="Ready"):
    return {
        "EnvironmentName": name,
        "ApplicationName": app,
        "EnvironmentArn":  arn,
        "PlatformArn":     platform_arn,
        "SolutionStackName": stack,
        "Status":          status,
        "EnvironmentId":   "e-abc123",
        "Health":          "Green",
        "Tier":            {"Name": "WebServer"},
        "VersionLabel":    "v1",
    }


def test_collect_elastic_beanstalk_retired_platform_eol():
    """API PlatformLifecycleState=retired → EOL with migrate recommendation."""
    arn = "arn:aws:elasticbeanstalk:us-east-1::platform/Python 3.6 running on 64bit Amazon Linux/2.16.2"
    env = _eb_env(name="legacy-env", platform_arn=arn,
                  stack="64bit Amazon Linux v2.16.2 running Python 3.6")
    session = MagicMock()
    session.client.return_value = _make_eb_client(
        envs=[env],
        platform_details={arn: {
            "PlatformLifecycleState": "retired",
            "PlatformBranchName":     "Python 3.6 running on 64bit Amazon Linux",
        }},
    )

    results = eol_collector.collect_elastic_beanstalk(session, "us-east-1", "123456789012")

    assert len(results) == 1
    r = results[0]
    assert r["eol_status"]             == "EOL"
    assert r["platform_lifecycle_state"] == "retired"
    assert r["confidence"]             == "HIGH"
    assert "retired" in r["classification_reason"]
    assert "AL2023" in r["recommendation"]


def test_collect_elastic_beanstalk_deprecated_platform_needs_inspection():
    """API PlatformLifecycleState=deprecated → NEEDS_INSPECTION with migration advisory."""
    arn = "arn:aws:elasticbeanstalk:us-east-1::platform/Python 3.8 running on 64bit Amazon Linux 2/3.4.1"
    env = _eb_env(name="old-env", platform_arn=arn,
                  stack="64bit Amazon Linux 2 v3.4.1 running Python 3.8")
    session = MagicMock()
    session.client.return_value = _make_eb_client(
        envs=[env],
        platform_details={arn: {
            "PlatformLifecycleState": "deprecated",
            "PlatformBranchName":     "Python 3.8 running on 64bit Amazon Linux 2",
        }},
    )

    results = eol_collector.collect_elastic_beanstalk(session, "us-east-1", "123456789012")

    assert len(results) == 1
    r = results[0]
    assert r["eol_status"]             == "NEEDS_INSPECTION"
    assert r["platform_lifecycle_state"] == "deprecated"
    assert r["confidence"]             == "HIGH"
    assert "deprecated" in r["classification_reason"]
    assert "AL2023" in r["recommendation"]


def test_collect_elastic_beanstalk_supported_platform_api():
    """API PlatformLifecycleState=supported → SUPPORTED + HIGH confidence + all fields."""
    arn = "arn:aws:elasticbeanstalk:us-east-1::platform/Python 3.11 running on 64bit Amazon Linux 2023/4.0.2"
    env = _eb_env(platform_arn=arn)
    session = MagicMock()
    session.client.return_value = _make_eb_client(
        envs=[env],
        platform_details={arn: {
            "PlatformLifecycleState": "supported",
            "PlatformBranchName":     "Python 3.11 running on 64bit Amazon Linux 2023",
        }},
    )

    results = eol_collector.collect_elastic_beanstalk(session, "us-east-1", "123456789012")

    assert len(results) == 1
    r = results[0]
    assert r["service_type"]             == "ElasticBeanstalk"
    assert r["eol_status"]               == "SUPPORTED"
    assert r["confidence"]               == "HIGH"
    assert r["platform_lifecycle_state"] == "supported"
    assert r["platform_branch_name"]     == "Python 3.11 running on 64bit Amazon Linux 2023"
    assert r["application_name"]         == "web"
    assert r["environment_id"]           == "e-abc123"
    assert r["health"]                   == "Green"
    assert r["tier"]                     == "WebServer"


def test_collect_elastic_beanstalk_al2023_fallback_no_arn():
    """No platform ARN, AL2023 in stack → SUPPORTED via OS fallback, MEDIUM confidence."""
    env = _eb_env(platform_arn="", stack="64bit Amazon Linux 2023 v4.0.2 running Node.js 20")
    session = MagicMock()
    session.client.return_value = _make_eb_client(envs=[env], platform_details={})

    results = eol_collector.collect_elastic_beanstalk(session, "us-east-1", "123456789012")

    assert len(results) == 1
    r = results[0]
    assert r["eol_status"] == "SUPPORTED"
    assert r["confidence"] == "MEDIUM"
    assert "AL2023" in r["classification_reason"]


def test_collect_elastic_beanstalk_al2_fallback_expiring():
    """No platform ARN, AL2 in stack → EOL or EXPIRING_SOON (AL2 support ends 2026-06-30)."""
    env = _eb_env(platform_arn="", stack="64bit Amazon Linux 2 v3.4.1 running Python 3.8")
    session = MagicMock()
    session.client.return_value = _make_eb_client(envs=[env], platform_details={})

    results = eol_collector.collect_elastic_beanstalk(session, "us-east-1", "123456789012")

    assert len(results) == 1
    r = results[0]
    assert r["eol_status"] in ("EOL", "EXPIRING_SOON")
    assert r["eol_date"]   == "2026-06-30"
    assert r["confidence"] == "MEDIUM"
    assert "AL2023" in r["recommendation"]


def test_collect_elastic_beanstalk_describe_failure_uses_os_fallback():
    """describe_platform_version failure → falls back to OS classification, confidence MEDIUM."""
    arn = "arn:aws:elasticbeanstalk:us-east-1::platform/Python 3.8/3.4.1"
    env = _eb_env(platform_arn=arn, stack="64bit Amazon Linux 2023 v4.0.2 running Python 3.11")
    client = MagicMock()
    client.get_paginator.return_value.paginate.return_value = [{"Environments": [env]}]
    client.describe_platform_version.side_effect = eol_collector.ClientError(
        {"Error": {"Code": "AccessDeniedException", "Message": "not authorized"}},
        "DescribePlatformVersion",
    )
    session = MagicMock()
    session.client.return_value = client

    results = eol_collector.collect_elastic_beanstalk(session, "us-east-1", "123456789012")

    assert len(results) == 1
    r = results[0]
    assert r["eol_status"] == "SUPPORTED"   # AL2023 in stack → SUPPORTED
    assert r["confidence"] == "MEDIUM"       # fallback, not API-confirmed


def test_collect_elastic_beanstalk_access_denied_records_warning():
    """AccessDenied on describe_environments → ELASTIC_BEANSTALK_ACCESS_DENIED, empty result."""
    eol_collector.SCAN_WARNINGS.clear()
    client = MagicMock()
    client.get_paginator.side_effect = eol_collector.ClientError(
        {"Error": {"Code": "AccessDeniedException", "Message": "not authorized"}},
        "DescribeEnvironments",
    )
    session = MagicMock()
    session.client.return_value = client

    results = eol_collector.collect_elastic_beanstalk(session, "us-east-1", "123456789012")

    assert results == []
    warnings = eol_collector.get_scan_warnings()
    assert any(w["code"] == "ELASTIC_BEANSTALK_ACCESS_DENIED" for w in warnings)


# ── AWS Batch collector ───────────────────────────────────────────────────────

def _make_batch_client(compute_envs):
    """Return a mock Batch client for collect_batch tests."""
    client = MagicMock()
    client.get_paginator.return_value.paginate.return_value = [{"computeEnvironments": compute_envs}]
    return client


def _batch_ce(name="batch-ce", ce_type="MANAGED", state="ENABLED", status="VALID",
              cr_type="EC2", image_type="ECS_AL2023", image_id="",
              instance_types=None, min_vcpus=0, max_vcpus=256,
              arn="arn:aws:batch:us-east-1:123:compute-environment/batch-ce"):
    ec2_config = [{"imageType": image_type}] if image_type else []
    return {
        "computeEnvironmentName": name,
        "computeEnvironmentArn":  arn,
        "type":                   ce_type,
        "state":                  state,
        "status":                 status,
        "statusReason":           "",
        "serviceRole":            "arn:aws:iam::123:role/AWSBatchServiceRole",
        "computeResources": {
            "type":               cr_type,
            "allocationStrategy": "BEST_FIT_PROGRESSIVE",
            "minvCpus":           min_vcpus,
            "maxvCpus":           max_vcpus,
            "desiredvCpus":       0,
            "instanceTypes":      instance_types or ["optimal"],
            "imageId":            image_id,
            "ec2Configuration":   ec2_config,
        },
    }


def test_collect_batch_al2023_ecs_supported():
    """ECS_AL2023 imageType → SUPPORTED with all metadata fields."""
    session = MagicMock()
    session.client.return_value = _make_batch_client([_batch_ce(image_type="ECS_AL2023")])

    results = eol_collector.collect_batch(session, "us-east-1", "123456789012")

    assert len(results) == 1
    r = results[0]
    assert r["service_type"]              == "AWSBatch"
    assert r["version"]                   == "ECS_AL2023"
    assert r["image_type"]                == "ECS_AL2023"
    assert r["eol_status"]                == "SUPPORTED"
    assert r["eol_date"]                  is None
    assert r["days_to_eol"]               is None
    assert r["confidence"]                == "HIGH"
    assert r["detection_source"]          == "BATCH_COMPUTE_ENVIRONMENT"
    assert r["resource_type"]             == "AWS Batch Compute Environment"
    assert r["compute_environment_name"]  == "batch-ce"
    assert r["state"]                     == "ENABLED"
    assert r["max_vcpus"]                 == 256


def test_collect_batch_al2_ecs_eol():
    """ECS_AL2 imageType → EOL or EXPIRING_SOON (AL2 support ends 2026-06-30)."""
    ce = _batch_ce(name="al2-ce", image_type="ECS_AL2",
                   arn="arn:aws:batch:us-east-1:123:compute-environment/al2-ce")
    session = MagicMock()
    session.client.return_value = _make_batch_client([ce])

    results = eol_collector.collect_batch(session, "us-east-1", "123456789012")

    assert len(results) == 1
    r = results[0]
    assert r["image_type"]  == "ECS_AL2"
    assert r["eol_date"]    == "2026-06-30"
    assert r["eol_status"]  in ("EOL", "EXPIRING_SOON")
    assert r["confidence"]  == "HIGH"
    assert "AL2023" in r["recommendation"]


def test_collect_batch_al2_eks_eol():
    """EKS_AL2 imageType → EOL or EXPIRING_SOON (AL2 EKS-optimized AMI follows AL2 support end)."""
    ce = _batch_ce(name="eks-al2-ce", image_type="EKS_AL2",
                   arn="arn:aws:batch:us-east-1:123:compute-environment/eks-al2-ce")
    session = MagicMock()
    session.client.return_value = _make_batch_client([ce])

    results = eol_collector.collect_batch(session, "us-east-1", "123456789012")

    assert len(results) == 1
    r = results[0]
    assert r["image_type"]  == "EKS_AL2"
    assert r["eol_date"]    == "2026-06-30"
    assert r["eol_status"]  in ("EOL", "EXPIRING_SOON")
    assert r["confidence"]  == "HIGH"


def test_collect_batch_custom_image_id_needs_inspection():
    """Custom image_id without imageType → NEEDS_INSPECTION, no fake EOL assigned."""
    ce = _batch_ce(name="custom-ce", image_type="", image_id="ami-0abc123def456789",
                   arn="arn:aws:batch:us-east-1:123:compute-environment/custom-ce")
    session = MagicMock()
    session.client.return_value = _make_batch_client([ce])

    results = eol_collector.collect_batch(session, "us-east-1", "123456789012")

    assert len(results) == 1
    r = results[0]
    assert r["eol_status"]  == "NEEDS_INSPECTION"
    assert r["eol_date"]    is None
    assert r["image_id"]    == "ami-0abc123def456789"
    assert r["confidence"]  == "LOW"
    assert "Custom" in r["recommendation"]


def test_collect_batch_missing_compute_resources_no_crash():
    """Compute environment with no computeResources (UNMANAGED) → UNKNOWN, no crash."""
    ce = {
        "computeEnvironmentName": "unmanaged-ce",
        "computeEnvironmentArn":  "arn:aws:batch:us-east-1:123:compute-environment/unmanaged-ce",
        "type":                   "UNMANAGED",
        "state":                  "ENABLED",
        "status":                 "VALID",
        "statusReason":           "",
        "serviceRole":            "",
        # computeResources intentionally absent
    }
    session = MagicMock()
    session.client.return_value = _make_batch_client([ce])

    results = eol_collector.collect_batch(session, "us-east-1", "123456789012")

    assert len(results) == 1
    r = results[0]
    assert r["eol_status"] == "UNKNOWN"
    assert r["eol_date"]   is None


def test_collect_batch_access_denied_records_warning():
    """AccessDenied on describe_compute_environments → BATCH_ACCESS_DENIED warning, empty result."""
    eol_collector.SCAN_WARNINGS.clear()
    client = MagicMock()
    client.get_paginator.side_effect = eol_collector.ClientError(
        {"Error": {"Code": "AccessDeniedException", "Message": "not authorized"}},
        "DescribeComputeEnvironments",
    )
    session = MagicMock()
    session.client.return_value = client

    results = eol_collector.collect_batch(session, "us-east-1", "123456789012")

    assert results == []
    warnings = eol_collector.get_scan_warnings()
    assert any(w["code"] == "BATCH_ACCESS_DENIED" for w in warnings)


def test_collect_batch_multiple_environments_collected():
    """Multiple compute environments across AL2/AL2023 types are all collected."""
    ces = [
        _batch_ce(name="ce-al2023",  image_type="ECS_AL2023",
                  arn="arn:aws:batch:us-east-1:123:compute-environment/ce-al2023"),
        _batch_ce(name="ce-al2",     image_type="ECS_AL2",
                  arn="arn:aws:batch:us-east-1:123:compute-environment/ce-al2"),
        _batch_ce(name="ce-al2-gpu", image_type="ECS_AL2_NVIDIA",
                  arn="arn:aws:batch:us-east-1:123:compute-environment/ce-al2-gpu"),
    ]
    session = MagicMock()
    session.client.return_value = _make_batch_client(ces)

    results = eol_collector.collect_batch(session, "us-east-1", "123456789012")

    assert len(results) == 3
    statuses = {r["resource_name"]: r["eol_status"] for r in results}
    assert statuses["ce-al2023"]  == "SUPPORTED"
    assert statuses["ce-al2"]     in ("EOL", "EXPIRING_SOON")
    assert statuses["ce-al2-gpu"] in ("EOL", "EXPIRING_SOON")
