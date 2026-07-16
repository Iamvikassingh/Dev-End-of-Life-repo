Amazon Inspector SBOM Generator Quick Start

Overview:
Amazon Inspector SBOM Generator (inspector-sbomgen) produces a software bill of materials (SBOM) for a resource you specify, such as a container image or local system directory. 

Inspector-sbomgen works by scanning for files known to contain information about installed packages. If one of these files is found the tool extracts package names, versions, and other metadata. This package metadata is then transformed into a CycloneDX v1.5 SBOM.

Usage:
- First make sure inspector-sbomgen has execute permissions:
    chmod +x inspector-sbomgen

- Next, try executing inspector-sbomgen's built in examples:
    ./inspector-sbomgen list-examples

If you have questions, comments, or technical issues related to inspector-sbomgen, feel encouraged to use the AWS resources below:
    https://repost.aws/knowledge-center/get-aws-help

Copyright 2023 Amazon.com, Inc. or its affiliates. All Rights Reserved
